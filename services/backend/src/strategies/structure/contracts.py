from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ...models import Candle, MarketContext, Signal


@dataclass(frozen=True)
class StrategyRequest:
    symbol: str
    timeframe: str
    candles: List[Candle]
    market: MarketContext
    diagnostics: Optional[Dict[str, int]] = None


@dataclass(frozen=True)
class StrategyDecision:
    strategy_name: str
    should_open_trade: bool
    signal: Optional[Signal] = None
    diagnostics: Dict[str, int] = field(default_factory=dict)
    rejection_reason: Optional[str] = None
