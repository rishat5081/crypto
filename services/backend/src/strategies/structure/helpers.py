from __future__ import annotations

from typing import List, Optional

from ...indicators import ema, ema_series, support_resistance_zones, volume_profile
from ...models import Candle
from .types import MarketStructure


class StrategyHelperMixin:
    @staticmethod
    def _find_swing_points(candles: List[Candle], lookback: int = 20) -> tuple:
        window = candles[-lookback:] if len(candles) >= lookback else candles
        swing_high = max(c.high for c in window)
        swing_low = min(c.low for c in window)
        return (swing_high, swing_low)

    @staticmethod
    def _fibonacci_retracement_score(price: float, swing_high: float, swing_low: float, side: str) -> float:
        rng = swing_high - swing_low
        if rng <= 0:
            return 0.5
        depth = (swing_high - price) / rng if side == "LONG" else (price - swing_low) / rng
        if 0.382 <= depth <= 0.618:
            return 1.0
        if 0.236 <= depth < 0.382:
            return 0.8
        if 0.618 < depth <= 0.786:
            return 0.7
        return 0.4

    @staticmethod
    def _candle_quality_score(candles: List[Candle], side: str) -> float:
        if len(candles) < 2:
            return 0.3
        last = candles[-1]
        prev = candles[-2]
        last_body = abs(last.close - last.open)
        prev_body = abs(prev.close - prev.open)
        last_range = last.high - last.low
        if last_range <= 0:
            return 0.3
        if side == "LONG":
            is_engulfing = last.close > last.open and prev.close < prev.open and last_body > prev_body * 1.1
            if is_engulfing:
                return 1.0
            lower_wick = min(last.open, last.close) - last.low
            if lower_wick > 2 * last_body and last_body > 0:
                return 0.9
        else:
            is_engulfing = last.close < last.open and prev.close > prev.open and last_body > prev_body * 1.1
            if is_engulfing:
                return 1.0
            upper_wick = last.high - max(last.open, last.close)
            if upper_wick > 2 * last_body and last_body > 0:
                return 0.9
        if (side == "LONG" and last.close > last.open) or (side == "SHORT" and last.close < last.open):
            return 0.6
        return 0.3

    def _build_market_structure(self, candles: List[Candle], entry: float) -> MarketStructure:
        window = candles[-self.params.sr_zone_lookback :] if len(candles) > self.params.sr_zone_lookback else candles
        zones = [
            (level, touches)
            for level, touches in support_resistance_zones(
                window,
                lookback=self.params.sr_swing_lookback,
                merge_pct=self.params.sr_merge_pct,
            )
            if touches >= self.params.sr_min_touches
        ]
        zones_by_price = sorted(zones, key=lambda item: item[0])
        support = None
        resistance = None
        support_touches = 0
        resistance_touches = 0
        for level, touches in zones_by_price:
            if level <= entry:
                support = level
                support_touches = touches
                continue
            resistance = level
            resistance_touches = touches
            break

        hvn_support = None
        hvn_resistance = None
        profile = volume_profile(window, num_bins=20)
        for level, _volume in profile:
            if hvn_support is None and level <= entry:
                hvn_support = level
            if hvn_resistance is None and level >= entry:
                hvn_resistance = level
            if hvn_support is not None and hvn_resistance is not None:
                break

        recent_window_size = max(3, self.params.pullback_stop_lookback, self.params.structure_stop_lookback)
        recent_window = candles[-recent_window_size:] if len(candles) > recent_window_size else candles
        return MarketStructure(
            support=support,
            resistance=resistance,
            support_touches=support_touches,
            resistance_touches=resistance_touches,
            hvn_support=hvn_support,
            hvn_resistance=hvn_resistance,
            recent_swing_low=min((c.low for c in recent_window), default=None),
            recent_swing_high=max((c.high for c in recent_window), default=None),
        )

    @staticmethod
    def _strictly_aligned_with_trend(side: str, trend_bias: str) -> bool:
        return (side == "LONG" and trend_bias == "BULL") or (side == "SHORT" and trend_bias == "BEAR")

    def _macro_trend_bias(self, close_prices: List[float], entry: float, ema_fast_v: float, ema_slow_v: float) -> str:
        if not close_prices:
            return "NEUTRAL"
        trend_period = self.params.ema_trend if self.params.ema_trend > 0 and len(close_prices) >= self.params.ema_trend else self.params.ema_slow
        trend_ema = ema(close_prices, trend_period)
        slope_bars = max(1, self.params.ema_trend_slope_bars)
        slope = 0.0
        try:
            trend_series = ema_series(close_prices, trend_period)
            if len(trend_series) > slope_bars:
                slope = (trend_series[-1] - trend_series[-1 - slope_bars]) / max(entry, 1e-9)
        except ValueError:
            slope = (ema_fast_v - ema_slow_v) / max(entry, 1e-9)
        if entry >= trend_ema and ema_fast_v >= ema_slow_v and slope >= self.params.ema_trend_slope_min:
            return "BULL"
        if entry <= trend_ema and ema_fast_v <= ema_slow_v and slope <= -self.params.ema_trend_slope_min:
            return "BEAR"
        return "NEUTRAL"

    def _has_recent_ma_break(self, close_prices: List[float], side: str, period: int) -> bool:
        if period <= 1 or len(close_prices) < period + 1:
            return False
        try:
            ma_series = ema_series(close_prices, period)
        except ValueError:
            return False
        if len(ma_series) < 2:
            return False
        offset = len(close_prices) - len(ma_series)
        start = max(1, len(ma_series) - self.params.ma_break_lookback)
        for idx in range(start, len(ma_series)):
            prev_price = close_prices[offset + idx - 1]
            curr_price = close_prices[offset + idx]
            prev_ma = ma_series[idx - 1]
            curr_ma = ma_series[idx]
            if side == "LONG" and prev_price <= prev_ma and curr_price > curr_ma:
                return True
            if side == "SHORT" and prev_price >= prev_ma and curr_price < curr_ma:
                return True
        return False

    @staticmethod
    def _support_reference(structure: MarketStructure) -> Optional[float]:
        return structure.support if structure.support is not None else structure.hvn_support

    @staticmethod
    def _resistance_reference(structure: MarketStructure) -> Optional[float]:
        return structure.resistance if structure.resistance is not None else structure.hvn_resistance

    @staticmethod
    def _format_structure_level(level: Optional[float]) -> str:
        return "na" if level is None else f"{level:.2f}"

    def _is_near_structure(self, side: str, entry: float, atr_v: float, structure: MarketStructure) -> bool:
        if atr_v <= 0:
            return False
        reference = self._support_reference(structure) if side == "LONG" else self._resistance_reference(structure)
        return reference is not None and abs(entry - reference) / atr_v <= self.params.sr_entry_tolerance_atr

    def _has_reward_room(self, side: str, entry: float, atr_v: float, structure: MarketStructure) -> bool:
        if atr_v <= 0:
            return False
        target_reference = self._resistance_reference(structure) if side == "LONG" else self._support_reference(structure)
        if target_reference is None:
            return True
        return abs(target_reference - entry) / atr_v >= self.params.sr_min_room_atr

    def _is_rejection_against_entry(self, side: str, candles: List[Candle], atr_v: float, structure: MarketStructure) -> bool:
        if not candles or atr_v <= 0:
            return False
        last = candles[-1]
        candle_range = last.high - last.low
        if candle_range <= 0:
            return False
        body = abs(last.close - last.open)
        upper_wick = last.high - max(last.open, last.close)
        lower_wick = min(last.open, last.close) - last.low
        close_position = (last.close - last.low) / candle_range
        wick_threshold = max(body * self.params.rejection_wick_to_body_ratio, candle_range * 0.35)
        extreme_tolerance = atr_v * self.params.rejection_extreme_tolerance_atr
        near_recent_high = structure.recent_swing_high is not None and last.high >= (structure.recent_swing_high - extreme_tolerance)
        near_recent_low = structure.recent_swing_low is not None and last.low <= (structure.recent_swing_low + extreme_tolerance)
        near_resistance = (
            (self._resistance_reference(structure) is not None and last.high >= (self._resistance_reference(structure) - extreme_tolerance))
            or near_recent_high
        )
        near_support = (
            (self._support_reference(structure) is not None and last.low <= (self._support_reference(structure) + extreme_tolerance))
            or near_recent_low
        )
        if side == "LONG":
            return near_resistance and upper_wick >= wick_threshold and close_position <= self.params.rejection_close_position_threshold
        return near_support and lower_wick >= wick_threshold and close_position >= (1.0 - self.params.rejection_close_position_threshold)

    def _recent_breakdown_low(self, candles: List[Candle]) -> Optional[float]:
        if len(candles) < 2:
            return None
        lookback = max(2, self.params.breakdown_lookback, self.params.structure_break_lookback)
        window = candles[-(lookback + 1) : -1]
        return min((c.low for c in window), default=None)

    def _recent_breakout_high(self, candles: List[Candle]) -> Optional[float]:
        if len(candles) < 2:
            return None
        lookback = max(2, self.params.structure_break_lookback)
        window = candles[-(lookback + 1) : -1]
        return max((c.high for c in window), default=None)
