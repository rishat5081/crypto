import math

from src.models import Candle, MarketContext
from src.strategies import StrategyParameters


def _default_params(**overrides) -> StrategyParameters:
    defaults = dict(
        ema_fast=5,
        ema_slow=10,
        rsi_period=14,
        atr_period=14,
        atr_multiplier=1.5,
        risk_reward=2.0,
        min_atr_pct=0.001,
        max_atr_pct=0.05,
        funding_abs_limit=0.001,
        min_confidence=0.25,
        long_rsi_min=55,
        long_rsi_max=72,
        short_rsi_min=28,
        short_rsi_max=48,
        crossover_max_drift_atr=0.5,
        pullback_confirmation_slack_pct=0.0,
        volume_ratio_min=0.5,
    )
    defaults.update(overrides)
    return StrategyParameters(**defaults)


def _make_candles(prices, volume=100.0):
    candles = []
    for i, price in enumerate(prices):
        candles.append(
            Candle(
                open_time_ms=i * 60000,
                open=price * 0.999,
                high=price * 1.002,
                low=price * 0.998,
                close=price,
                volume=volume,
                close_time_ms=(i + 1) * 60000 - 1,
            )
        )
    return candles


def _neutral_market() -> MarketContext:
    return MarketContext(mark_price=100.0, funding_rate=0.0001, open_interest=1e6)


def _trending_up_candles(n: int = 50, start: float = 100.0, step: float = 0.5):
    candles = []
    price = start
    for i in range(n):
        open_price = price
        close = price + step
        high = close + step * 0.3
        low = open_price - step * 0.2
        candles.append(
            Candle(
                open_time_ms=i * 60000,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=100.0,
                close_time_ms=(i + 1) * 60000 - 1,
            )
        )
        price = close
    return candles


def _ranging_candles(n: int = 50, center: float = 100.0, amplitude: float = 1.0):
    candles = []
    for i in range(n):
        value = center + amplitude * math.sin(i * 0.5)
        open_price = value - 0.2
        close = value + 0.2
        high = max(open_price, close) + 0.1
        low = min(open_price, close) - 0.1
        candles.append(
            Candle(
                open_time_ms=i * 60000,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=100.0,
                close_time_ms=(i + 1) * 60000 - 1,
            )
        )
    return candles
