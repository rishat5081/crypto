from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.models import Signal
from src.trade_engine import TradeEngine


@dataclass
class CandidateSignal:
    signal: Signal
    trend_strength: float
    cost_r: float
    rr: float
    expectancy_r: float
    symbol_quality: float
    score: float


@dataclass
class ManagedTrade:
    signal: Signal
    engine: TradeEngine
    start_time: float
    timeframe_minutes: int
    max_wait_seconds: int
    last_seen_close_ms: int
    best_r: float
    original_risk: float
    bars_seen: int
    consecutive_adverse_bars: int
    moved_to_break_even: bool
    trailing_stop_active: bool
    consecutive_fetch_errors: int
    last_known_candles: Optional[List]
    binance_opened: bool
