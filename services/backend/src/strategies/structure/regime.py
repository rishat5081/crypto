from __future__ import annotations

from typing import List

from ...indicators import adx, bb_width
from ...models import Candle
from .types import MarketRegime


class RegimeDetector:
    """Classifies market regime using ADX + BB width + volatility ratio."""

    def __init__(
        self,
        adx_period: int = 14,
        adx_trending: float = 25.0,
        adx_ranging: float = 20.0,
        bb_period: int = 20,
        bb_std: float = 2.0,
        bb_width_volatile: float = 0.06,
        vol_ratio_volatile: float = 1.5,
    ):
        self.adx_period = adx_period
        self.adx_trending = adx_trending
        self.adx_ranging = adx_ranging
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.bb_width_volatile = bb_width_volatile
        self.vol_ratio_volatile = vol_ratio_volatile

    def detect(
        self,
        candles: List[Candle],
        close_prices: List[float],
        ema_fast_v: float = 0.0,
        ema_slow_v: float = 0.0,
    ) -> MarketRegime:
        min_adx_candles = 2 * self.adx_period + 1
        adx_val = 0.0
        if len(candles) >= min_adx_candles:
            adx_val = adx(candles, self.adx_period)

        bbw = 0.0
        if len(close_prices) >= self.bb_period:
            bbw = bb_width(close_prices, self.bb_period, self.bb_std)

        vol_ratio = 1.0
        if len(candles) > 20:
            recent_ranges = [(c.high - c.low) for c in candles[-20:]]
            avg_range = sum(recent_ranges) / len(recent_ranges)
            current_range = candles[-1].high - candles[-1].low
            if avg_range > 0:
                vol_ratio = current_range / avg_range

        if ema_fast_v > ema_slow_v * 1.001:
            trend_dir = "BULL"
        elif ema_fast_v < ema_slow_v * 0.999:
            trend_dir = "BEAR"
        else:
            trend_dir = "NEUTRAL"

        if vol_ratio > self.vol_ratio_volatile and bbw > self.bb_width_volatile:
            regime = "VOLATILE"
            confidence = min(1.0, (vol_ratio - self.vol_ratio_volatile) / self.vol_ratio_volatile + 0.5)
        elif adx_val >= self.adx_trending:
            regime = "TRENDING"
            confidence = min(1.0, (adx_val - self.adx_trending) / 25.0 + 0.5)
        elif adx_val <= self.adx_ranging:
            regime = "RANGING"
            confidence = min(1.0, (self.adx_ranging - adx_val) / self.adx_ranging + 0.5)
        else:
            regime = "RANGING"
            confidence = 0.4

        return MarketRegime(
            regime=regime,
            adx=adx_val,
            bb_width_val=bbw,
            trend_direction=trend_dir,
            confidence=confidence,
        )
