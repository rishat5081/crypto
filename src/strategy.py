from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .indicators import atr, ema, ema_series, rsi
from .models import Candle, MarketContext, Signal


@dataclass
class StrategyParameters:
    ema_fast: int
    ema_slow: int
    rsi_period: int
    atr_period: int
    atr_multiplier: float
    risk_reward: float
    min_atr_pct: float
    max_atr_pct: float
    funding_abs_limit: float
    min_confidence: float
    long_rsi_min: float
    long_rsi_max: float
    short_rsi_min: float
    short_rsi_max: float
    crossover_lookback: int = 5


class StrategyEngine:
    def __init__(self, params: StrategyParameters):
        self.params = params

    @classmethod
    def from_dict(cls, payload: Dict) -> "StrategyEngine":
        params = StrategyParameters(
            ema_fast=int(payload["ema_fast"]),
            ema_slow=int(payload["ema_slow"]),
            rsi_period=int(payload["rsi_period"]),
            atr_period=int(payload["atr_period"]),
            atr_multiplier=float(payload["atr_multiplier"]),
            risk_reward=float(payload["risk_reward"]),
            min_atr_pct=float(payload["min_atr_pct"]),
            max_atr_pct=float(payload["max_atr_pct"]),
            funding_abs_limit=float(payload["funding_abs_limit"]),
            min_confidence=float(payload["min_confidence"]),
            long_rsi_min=float(payload["long_rsi_min"]),
            long_rsi_max=float(payload["long_rsi_max"]),
            short_rsi_min=float(payload["short_rsi_min"]),
            short_rsi_max=float(payload["short_rsi_max"]),
            crossover_lookback=int(payload.get("crossover_lookback", 5)),
        )
        return cls(params)

    def evaluate(
        self,
        symbol: str,
        timeframe: str,
        candles: List[Candle],
        market: MarketContext,
    ) -> Optional[Signal]:
        needed = max(self.params.ema_slow, self.params.rsi_period + 1, self.params.atr_period + 1)
        if len(candles) < needed:
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
            return None

        # Crossover recency: require the EMA crossover happened within the
        # last ``crossover_lookback`` bars to avoid mid-trend stale entries.
        crossover_lookback = self.params.crossover_lookback
        fast_series = ema_series(close_prices, self.params.ema_fast)
        slow_series = ema_series(close_prices, self.params.ema_slow)

        # Align: ema_series for period P returns len(close)-P+1 values.
        # We need the last ``crossover_lookback + 1`` aligned pairs.
        fast_offset = self.params.ema_fast - 1
        slow_offset = self.params.ema_slow - 1
        # Map index i in close_prices -> fast_series[i - fast_offset], slow_series[i - slow_offset]
        n = len(close_prices)
        look = min(crossover_lookback + 1, len(fast_series), len(slow_series))
        recent_diffs = []
        for k in range(look):
            fi = len(fast_series) - look + k
            si = len(slow_series) - look + k
            recent_diffs.append(fast_series[fi] - slow_series[si])

        # Detect if a crossover happened recently
        bullish_cross = any(recent_diffs[j] <= 0 and recent_diffs[j + 1] > 0
                           for j in range(len(recent_diffs) - 1))
        bearish_cross = any(recent_diffs[j] >= 0 and recent_diffs[j + 1] < 0
                           for j in range(len(recent_diffs) - 1))

        side: Optional[str] = None
        if (
            ema_fast_v > ema_slow_v
            and bullish_cross
            and self.params.long_rsi_min <= rsi_v <= self.params.long_rsi_max
            and entry >= ema_fast_v
            and abs(market.funding_rate) <= self.params.funding_abs_limit
        ):
            side = "LONG"
        elif (
            ema_fast_v < ema_slow_v
            and bearish_cross
            and self.params.short_rsi_min <= rsi_v <= self.params.short_rsi_max
            and entry <= ema_fast_v
            and abs(market.funding_rate) <= self.params.funding_abs_limit
        ):
            side = "SHORT"

        if not side:
            return None

        sl_distance = atr_v * self.params.atr_multiplier
        if side == "LONG":
            stop_loss = entry - sl_distance
            take_profit = entry + (sl_distance * self.params.risk_reward)
        else:
            stop_loss = entry + sl_distance
            take_profit = entry - (sl_distance * self.params.risk_reward)

        trend_strength = abs(ema_fast_v - ema_slow_v) / entry if entry else 0.0
        trend_score = min(trend_strength / 0.002, 1.0)
        if side == "LONG":
            rsi_center = (self.params.long_rsi_min + self.params.long_rsi_max) / 2
            rsi_half = max((self.params.long_rsi_max - self.params.long_rsi_min) / 2, 1.0)
        else:
            rsi_center = (self.params.short_rsi_min + self.params.short_rsi_max) / 2
            rsi_half = max((self.params.short_rsi_max - self.params.short_rsi_min) / 2, 1.0)
        rsi_score = max(0.0, 1 - abs(rsi_v - rsi_center) / rsi_half)
        atr_mid = (self.params.min_atr_pct + self.params.max_atr_pct) / 2
        atr_half_range = max((self.params.max_atr_pct - self.params.min_atr_pct) / 2, 1e-9)
        vol_score = max(0.0, 1 - abs(atr_pct - atr_mid) / atr_half_range)
        funding_score = 1 - min(abs(market.funding_rate) / self.params.funding_abs_limit, 1.0)

        confidence = 0.25 + (0.35 * trend_score) + (0.15 * rsi_score) + (0.15 * vol_score) + (0.10 * funding_score)
        confidence = max(0.0, min(confidence, 0.99))

        if confidence < self.params.min_confidence:
            return None

        reason = (
            f"{side} trend setup | EMA({self.params.ema_fast}/{self.params.ema_slow})={ema_fast_v:.2f}/{ema_slow_v:.2f}, "
            f"RSI={rsi_v:.1f}, ATR%={atr_pct:.4f}, funding={market.funding_rate:.5f}"
        )
        return Signal(
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            entry=round(entry, 6),
            take_profit=round(take_profit, 6),
            stop_loss=round(stop_loss, 6),
            confidence=round(confidence, 4),
            reason=reason,
            signal_time_ms=last.close_time_ms,
        )

    def adaptive_tune_after_trade(self, trade_result: str) -> None:
        if trade_result == "LOSS":
            self.params.min_confidence = min(0.90, self.params.min_confidence + 0.01)
            return

        self.params.min_confidence = max(0.75, self.params.min_confidence - 0.005)
