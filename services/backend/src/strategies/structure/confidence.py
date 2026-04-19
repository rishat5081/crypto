from __future__ import annotations

from typing import List, Optional

from ...indicators import ema, macd_histogram_series
from ...models import Candle, MarketContext
from .types import MarketRegime


class StrategyConfidenceMixin:
    def _compute_confidence(
        self,
        side: str,
        signal_type: str,
        regime: MarketRegime,
        candles: List[Candle],
        close_prices: List[float],
        market: MarketContext,
        entry: float,
        atr_v: float,
        ema_fast_v: float,
        ema_slow_v: float,
        rsi_v: float,
        bb_vals: Optional[tuple] = None,
    ) -> float:
        trend_strength = abs(ema_fast_v - ema_slow_v) / entry if entry else 0.0
        regime_map = {
            ("TRENDING", "STRUCTURE"): 1.0,
            ("TRENDING", "CROSSOVER"): 1.0,
            ("TRENDING", "PULLBACK"): 1.0,
            ("TRENDING", "BREAKDOWN"): 1.0,
            ("TRENDING", "CONTINUATION"): 1.0,
            ("TRENDING", "SUPERTREND"): 1.0,
            ("RANGING", "BB_REVERSION"): 1.0,
            ("RANGING", "CROSSOVER"): 0.5,
            ("RANGING", "PULLBACK"): 0.5,
            ("RANGING", "CONTINUATION"): 0.4,
            ("RANGING", "SUPERTREND"): 0.6,
            ("VOLATILE", "BB_REVERSION"): 0.8,
            ("VOLATILE", "SUPERTREND"): 0.5,
        }
        regime_score = regime_map.get((regime.regime, signal_type), 0.3)
        if regime.regime == "VOLATILE" and signal_type not in ("BB_REVERSION", "SUPERTREND"):
            regime_score = 0.2

        if signal_type == "STRUCTURE":
            structure = self._build_market_structure(candles, entry)
            structure_near = self._is_near_structure(side, entry, atr_v, structure)
            reward_room = self._has_reward_room(side, entry, atr_v, structure)
            trend_component = min(trend_strength / max(self.params.structure_min_trend_strength, 1e-9), 1.0)
            structure_component = 1.0 if structure_near else (0.75 if reward_room else 0.45)
            candle_component = self._candle_quality_score(candles, side)
            structure_score = (0.45 * trend_component) + (0.35 * structure_component) + (0.20 * candle_component)
        elif signal_type == "PULLBACK":
            swing_high, swing_low = self._find_swing_points(candles)
            structure_score = self._fibonacci_retracement_score(entry, swing_high, swing_low, side)
        elif signal_type == "BB_REVERSION" and bb_vals:
            bb_upper, _bb_mid, bb_lower = bb_vals[:3]
            bb_range = bb_upper - bb_lower
            if bb_range > 0:
                if side == "LONG":
                    structure_score = min(1.0, (bb_lower - entry) / (bb_range * 0.1) + 0.8) if entry <= bb_lower else 0.5
                else:
                    structure_score = min(1.0, (entry - bb_upper) / (bb_range * 0.1) + 0.8) if entry >= bb_upper else 0.5
            else:
                structure_score = 0.5
        elif signal_type == "SUPERTREND":
            adx_score = min(regime.adx / 40.0, 1.0) if regime.adx > 0 else 0.3
            macd_score = 0.5
            try:
                hist = macd_histogram_series(close_prices)
                if len(hist) >= 2:
                    if (side == "LONG" and hist[-1] > hist[-2]) or (side == "SHORT" and hist[-1] < hist[-2]):
                        macd_score = 0.9
                    elif (side == "LONG" and hist[-1] > 0) or (side == "SHORT" and hist[-1] < 0):
                        macd_score = 0.7
            except (ValueError, IndexError):
                pass
            structure_score = 0.5 * adx_score + 0.5 * macd_score
        else:
            structure_score = min(trend_strength / 0.002, 1.0)

        candle_score = self._candle_quality_score(candles, side)
        sl_distance_atr = self.params.atr_multiplier if atr_v > 0 else 1.0
        stop_quality = max(0.0, min(1.0, 1.0 - (sl_distance_atr - 1.0) / 2.0))
        timing_score = 0.6 * candle_score + 0.4 * stop_quality
        volume_score = 0.5
        if len(candles) >= 20:
            recent_vols = [c.volume for c in candles[-20:]]
            avg_vol = sum(recent_vols) / len(recent_vols)
            if avg_vol > 0:
                volume_score = min(1.0, (candles[-1].volume / avg_vol) / 1.5)

        macro_aligned = 1.0
        if self.params.ema_trend > 0 and len(close_prices) >= self.params.ema_trend:
            ema_trend_v = ema(close_prices, self.params.ema_trend)
            macro_aligned = 1.0 if ((side == "LONG" and entry >= ema_trend_v) or (side == "SHORT" and entry <= ema_trend_v)) else 0.6
        if signal_type == "BB_REVERSION":
            macro_aligned = max(macro_aligned, 0.8)
        funding_score = 1.0 - min(abs(market.funding_rate) / max(self.params.funding_abs_limit, 1e-9), 1.0)
        context_score = 0.6 * macro_aligned + 0.4 * funding_score

        confidence = 0.05 + (0.25 * regime_score) + (0.30 * structure_score) + (0.20 * timing_score) + (0.10 * volume_score) + (0.15 * context_score)
        return max(0.0, min(confidence, 0.99))
