from __future__ import annotations

from typing import List, Optional

from ...models import Candle, MarketContext
from .types import MarketRegime, MarketStructure


class StrategyStructureSetupMixin:
    def _evaluate_trend_structure(
        self,
        candles: List[Candle],
        close_prices: List[float],
        market: MarketContext,
        regime: MarketRegime,
        entry: float,
        ema_fast_v: float,
        ema_slow_v: float,
        rsi_v: float,
        atr_v: float,
        trend_bias: str,
        structure: MarketStructure,
        note,
    ) -> Optional[tuple]:
        if regime.regime != "TRENDING":
            note("structure_requires_trending_regime")
            return None
        if abs(market.funding_rate) > self.params.funding_abs_limit:
            note("structure_funding_blocked")
            return None
        if len(candles) < 4 or atr_v <= 0:
            note("structure_not_enough_candles")
            return None
        if trend_bias not in ("BULL", "BEAR"):
            note("structure_requires_directional_trend")
            return None
        trend_strength = abs(ema_fast_v - ema_slow_v) / entry if entry else 0.0
        if trend_strength < self.params.structure_min_trend_strength:
            note("structure_trend_too_weak")
            return None

        last = candles[-1]
        prev = candles[-2]
        candle_range = last.high - last.low
        if candle_range <= 0:
            note("structure_invalid_candle")
            return None
        body = abs(last.close - last.open)
        body_ratio = body / candle_range
        close_position = (last.close - last.low) / candle_range
        upper_wick = last.high - max(last.open, last.close)
        near_ema = min(abs(last.low - ema_fast_v), abs(last.high - ema_fast_v)) / atr_v
        slack_pct = self.params.structure_confirmation_slack_pct
        avg_volume = 0.0
        if len(candles) >= 20:
            recent_volumes = [c.volume for c in candles[-20:]]
            avg_volume = sum(recent_volumes) / len(recent_volumes)
        relative_volume = (last.volume / avg_volume) if avg_volume > 0 else 1.0

        prior_structure = self._build_market_structure(candles[:-1], prev.close)
        prior_support = self._support_reference(prior_structure)
        prior_resistance = self._resistance_reference(prior_structure)
        recent_low = self._recent_breakdown_low(candles)
        recent_high = self._recent_breakout_high(candles)

        if trend_bias == "BULL":
            if not (self.params.long_rsi_min <= rsi_v <= self.params.long_rsi_max):
                note("structure_rsi_out_of_range")
                return None
            strong_bull_close = last.close > last.open and body_ratio >= self.params.structure_min_body_ratio and close_position >= (1.0 - self.params.structure_close_position_max)
            support_reference = self._support_reference(structure)
            near_support = self._is_near_structure("LONG", entry, atr_v, structure) or near_ema <= max(1.0, self.params.sr_entry_tolerance_atr)
            pulled_back = prev.low <= (ema_fast_v + (atr_v * self.params.structure_retest_tolerance_atr)) or prev.close <= ema_fast_v * (1 + slack_pct) or (support_reference is not None and prev.low <= (support_reference + (atr_v * self.params.structure_retest_tolerance_atr)))
            bullish_reclaim = strong_bull_close and entry >= prev.close * (1 - slack_pct) and entry >= ema_fast_v
            if near_support and pulled_back and bullish_reclaim:
                return ("LONG", "STRUCTURE", {"pattern": "support_bounce", "break_level": support_reference})
            break_reference = prior_resistance if prior_resistance is not None else recent_high
            broke_resistance_now = break_reference is not None and entry >= (break_reference + (atr_v * self.params.structure_break_min_atr)) and strong_bull_close
            prev_break_above = break_reference is not None and prev.close >= (break_reference + (atr_v * self.params.structure_break_min_atr))
            retest_resume = break_reference is not None and prev_break_above and last.low <= (break_reference + (atr_v * self.params.structure_retest_tolerance_atr)) and strong_bull_close and entry >= (break_reference + (atr_v * 0.05))
            if broke_resistance_now or retest_resume:
                return ("LONG", "STRUCTURE", {"pattern": "resistance_break", "break_level": break_reference})
            note("structure_long_not_confirmed")
            return None

        if not (self.params.short_rsi_min <= rsi_v <= self.params.short_rsi_max):
            note("structure_rsi_out_of_range")
            return None
        strong_bear_close = last.close < last.open and body_ratio >= self.params.structure_min_body_ratio and close_position <= self.params.structure_close_position_max
        wick_threshold = max(body * self.params.structure_short_rejection_wick_ratio_min, candle_range * 0.08)
        resistance_reference = self._resistance_reference(structure)
        near_resistance = self._is_near_structure("SHORT", entry, atr_v, structure) or near_ema <= max(1.0, self.params.sr_entry_tolerance_atr)
        bounced_up = prev.high >= (ema_fast_v - (atr_v * self.params.structure_retest_tolerance_atr)) or prev.close >= ema_fast_v * (1 - slack_pct) or (resistance_reference is not None and prev.high >= (resistance_reference - (atr_v * self.params.structure_retest_tolerance_atr)))
        bearish_reclaim = strong_bear_close and entry <= prev.close * (1 + slack_pct) and entry <= ema_fast_v
        if near_resistance and bounced_up and bearish_reclaim and upper_wick >= wick_threshold:
            return ("SHORT", "STRUCTURE", {"pattern": "resistance_reject", "break_level": resistance_reference})
        break_reference = prior_support if prior_support is not None else recent_low
        broke_support_now = break_reference is not None and entry <= (break_reference - (atr_v * self.params.structure_break_min_atr)) and strong_bear_close
        prev_break_below = break_reference is not None and prev.close <= (break_reference - (atr_v * self.params.structure_break_min_atr))
        retested_break = break_reference is not None and last.high <= (break_reference + (atr_v * self.params.structure_retest_tolerance_atr)) and last.high >= (break_reference - (atr_v * self.params.structure_retest_tolerance_atr))
        resumed_lower = strong_bear_close and entry <= prev.close * (1 + slack_pct)
        if (broke_support_now or (prev_break_below and retested_break and resumed_lower)) and relative_volume >= self.params.volume_ratio_min:
            return ("SHORT", "STRUCTURE", {"pattern": "support_break", "break_level": break_reference})
        note("structure_short_not_confirmed")
        return None
