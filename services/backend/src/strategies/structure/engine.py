from __future__ import annotations

from typing import Dict, List, Optional

from ...indicators import atr, ema, rsi
from ...models import Candle, MarketContext, Signal
from .confidence import StrategyConfidenceMixin
from .helpers import StrategyHelperMixin
from .legacy import StrategyLegacySetupMixin
from .levels import StrategyTradeLevelsMixin
from .regime import RegimeDetector
from .structure_logic import StrategyStructureSetupMixin
from .types import MarketRegime, MarketStructure, StrategyParameters, build_strategy_parameters


class StrategyEngine(
    StrategyHelperMixin,
    StrategyTradeLevelsMixin,
    StrategyConfidenceMixin,
    StrategyLegacySetupMixin,
    StrategyStructureSetupMixin,
):
    def __init__(self, params: StrategyParameters):
        self.params = params
        self.regime_detector = RegimeDetector(
            adx_period=params.adx_period,
            adx_trending=params.adx_trending_threshold,
            adx_ranging=params.adx_ranging_threshold,
            bb_period=params.bb_period,
            bb_std=params.bb_std,
            bb_width_volatile=params.bb_width_volatile_threshold,
            vol_ratio_volatile=params.vol_ratio_volatile_threshold,
        )

    @classmethod
    def from_dict(cls, payload: Dict) -> "StrategyEngine":
        return cls(build_strategy_parameters(payload))

    def evaluate(self, symbol: str, timeframe: str, candles: List[Candle], market: MarketContext, diagnostics: Optional[Dict[str, int]] = None) -> Optional[Signal]:
        def note(reason: str) -> None:
            if diagnostics is not None:
                diagnostics[reason] = int(diagnostics.get(reason, 0)) + 1

        needed = max(self.params.ema_slow, self.params.rsi_period + 1, self.params.atr_period + 1)
        if len(candles) < needed:
            note("not_enough_candles")
            return None
        close_prices = [c.close for c in candles]
        last = candles[-1]
        entry = last.close
        ema_fast_v = ema(close_prices, self.params.ema_fast)
        ema_slow_v = ema(close_prices, self.params.ema_slow)
        rsi_v = rsi(close_prices, self.params.rsi_period)
        atr_v = atr(candles, self.params.atr_period)
        atr_pct = atr_v / entry if entry else 0.0
        if atr_pct < self.params.min_atr_pct or atr_pct > self.params.max_atr_pct:
            note("atr_out_of_range")
            return None
        regime = self.regime_detector.detect(candles, close_prices, ema_fast_v, ema_slow_v)
        structure = self._build_market_structure(candles, entry)
        trend_bias = self._macro_trend_bias(close_prices, entry, ema_fast_v, ema_slow_v)
        if regime.regime != "TRENDING":
            note("regime_not_supported")
            return None
        result = self._evaluate_trend_structure(candles, close_prices, market, regime, entry, ema_fast_v, ema_slow_v, rsi_v, atr_v, trend_bias, structure, note)
        if not result:
            return None
        side, signal_type, extra = result
        if not self._strictly_aligned_with_trend(side, trend_bias):
            note("structure_trend_alignment_failed")
            return None
        if self._is_rejection_against_entry(side, candles, atr_v, structure):
            note("structure_rejection_against_entry")
            return None
        pattern = str((extra or {}).get("pattern") or "")
        ma_break_confirmed = self._has_recent_ma_break(close_prices, side, self.params.ema_fast) or self._has_recent_ma_break(close_prices, side, self.params.ema_slow) or (self.params.ema_trend > 0 and self._has_recent_ma_break(close_prices, side, self.params.ema_trend))
        if "break" not in pattern and not ma_break_confirmed:
            note("ma_break_not_confirmed")
            return None
        if not self._has_reward_room(side, entry, atr_v, structure):
            note("sr_room_too_tight")
            return None
        if len(candles) >= 20:
            avg_vol = sum(c.volume for c in candles[-20:]) / len(candles[-20:])
            if avg_vol > 0 and last.volume < avg_vol * self.params.volume_ratio_min:
                note("volume_too_low")
                return None
        candle_range = last.high - last.low
        if candle_range > 0:
            body_ratio = abs(last.close - last.open) / candle_range
            if (side == "LONG" and last.close < last.open and body_ratio > 0.6) or (side == "SHORT" and last.close > last.open and body_ratio > 0.6):
                note("reversal_candle_blocked")
                return None
        stop_loss, take_profit = self._build_trade_levels(side=side, signal_type=signal_type, entry=entry, atr_v=atr_v, structure=structure, extra=extra)
        if (side == "LONG" and not (stop_loss < entry < take_profit)) or (side == "SHORT" and not (take_profit < entry < stop_loss)):
            note("invalid_trade_levels")
            return None
        confidence = self._compute_confidence(side, signal_type, regime, candles, close_prices, market, entry, atr_v, ema_fast_v, ema_slow_v, rsi_v, extra.get("bb") if extra else None)
        if confidence < self.params.min_confidence:
            note("confidence_below_min")
            return None
        note("signal_generated")
        reason = (
            f"{side} {signal_type.lower()} | regime={regime.regime} | pattern={str((extra or {}).get('pattern') or 'unknown')} | "
            f"trend={trend_bias} | EMA({self.params.ema_fast}/{self.params.ema_slow})={ema_fast_v:.2f}/{ema_slow_v:.2f}, "
            f"RSI={rsi_v:.1f}, ATR%={atr_pct:.4f}, ADX={regime.adx:.1f}, "
            f"SR={self._format_structure_level(self._support_reference(structure))}/{self._format_structure_level(self._resistance_reference(structure))}, "
            f"funding={market.funding_rate:.5f}"
        )
        return Signal(symbol=symbol, timeframe=timeframe, side=side, entry=round(entry, 6), take_profit=round(take_profit, 6), stop_loss=round(stop_loss, 6), confidence=round(confidence, 4), reason=reason, signal_time_ms=last.close_time_ms)

    def adaptive_tune_after_trade(self, trade_result: str) -> None:
        if trade_result == "LOSS":
            self.params.min_confidence = min(0.80, self.params.min_confidence + 0.005)
            return
        self.params.min_confidence = max(0.55, self.params.min_confidence - 0.003)
