from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Candle:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time_ms: int


@dataclass(frozen=True)
class MarketContext:
    mark_price: float
    funding_rate: float
    open_interest: float

