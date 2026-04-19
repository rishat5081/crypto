from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class SignalSample:
    symbol: str
    timeframe: str
    side: str
    open_time_ms: int
    close_time_ms: int
    features: List[float]
    label: int
    pnl_r: float
    confidence: float
    signal_type: str = "UNKNOWN"
    regime: str = "UNKNOWN"


@dataclass
class FoldResult:
    fold_index: int
    threshold: float
    trades: int
    wins: int
    losses: int
    win_rate: float
    expectancy_r: float


@dataclass
class WalkForwardResult:
    strategy: Dict
    tested_signals: int
    total_selected_trades: int
    wins: int
    losses: int
    win_rate: float
    expectancy_r: float
    folds: List[FoldResult]
    per_market: List[Dict]
    tested_thresholds: List[float]
    per_signal_type: List[Dict] = field(default_factory=list)
    per_regime: List[Dict] = field(default_factory=list)


def signal_type_from_reason(reason: str) -> str:
    upper = str(reason or "").upper()
    if "STRUCTURE" in upper:
        return "STRUCTURE"
    if "CONTINUATION" in upper:
        return "CONTINUATION"
    if "BB_REVERSION" in upper:
        return "BB_REVERSION"
    if "SUPERTREND" in upper:
        return "SUPERTREND"
    if "PULLBACK" in upper:
        return "PULLBACK"
    if "CROSSOVER" in upper:
        return "CROSSOVER"
    if "MOMENTUM" in upper:
        return "MOMENTUM"
    return "UNKNOWN"


def regime_from_reason(reason: str) -> str:
    upper = str(reason or "").upper()
    marker = "REGIME="
    if marker not in upper:
        return "UNKNOWN"
    token = upper.split(marker, 1)[1].split("|", 1)[0].split(",", 1)[0].strip()
    return token or "UNKNOWN"
