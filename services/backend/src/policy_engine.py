from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List

from .models import ClosedTrade


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""
    details: Dict[str, object] | None = None


@dataclass(frozen=True)
class SliceStats:
    trades: int
    wins: int
    losses: int
    win_rate: float
    expectancy_r: float


class SmartPolicyEngine:
    def __init__(
        self,
        *,
        enabled: bool = True,
        min_trades_for_setup_eval: int = 5,
        setup_pause_cycles: int = 20,
        negative_expectancy_pause: bool = True,
        min_setup_win_rate: float = 0.0,
    ) -> None:
        self.enabled = enabled
        self.min_trades_for_setup_eval = max(1, int(min_trades_for_setup_eval))
        self.setup_pause_cycles = max(1, int(setup_pause_cycles))
        self.negative_expectancy_pause = bool(negative_expectancy_pause)
        self.min_setup_win_rate = float(min_setup_win_rate)
        self.slice_recent_trades: Dict[str, List[ClosedTrade]] = defaultdict(list)
        self.slice_cooldowns: Dict[str, int] = {}

    @staticmethod
    def slice_key(signal_type: str, side: str) -> str:
        return f"{str(signal_type or '').upper()}|{str(side or '').upper()}"

    @staticmethod
    def stats(trades: List[ClosedTrade]) -> SliceStats:
        count = len(trades)
        wins = sum(1 for t in trades if t.result == "WIN")
        losses = count - wins
        win_rate = (wins / count) if count else 0.0
        expectancy_r = (sum(float(t.pnl_r) for t in trades) / count) if count else 0.0
        return SliceStats(
            trades=count,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            expectancy_r=expectancy_r,
        )

    def record_trade(self, signal_type: str, side: str, trade: ClosedTrade, window_size: int = 20) -> Dict[str, object]:
        key = self.slice_key(signal_type, side)
        bucket = self.slice_recent_trades[key]
        bucket.append(trade)
        if len(bucket) > window_size:
            del bucket[:-window_size]

        stats = self.stats(bucket)
        if not self.enabled or stats.trades < self.min_trades_for_setup_eval:
            return {"slice_key": key, "paused": False, "stats": stats}

        should_pause = False
        if self.negative_expectancy_pause and stats.expectancy_r < 0:
            should_pause = True
        if self.min_setup_win_rate > 0 and stats.win_rate < self.min_setup_win_rate:
            should_pause = True

        if should_pause:
            self.slice_cooldowns[key] = max(self.slice_cooldowns.get(key, 0), self.setup_pause_cycles)

        return {"slice_key": key, "paused": should_pause, "stats": stats}

    def evaluate_candidate(self, signal_type: str, side: str) -> PolicyDecision:
        if not self.enabled:
            return PolicyDecision(True)
        key = self.slice_key(signal_type, side)
        cooldown = int(self.slice_cooldowns.get(key, 0))
        if cooldown > 0:
            return PolicyDecision(
                False,
                reason="SETUP_SIDE_PAUSED",
                details={
                    "slice_key": key,
                    "cooldown_cycles_left": cooldown,
                },
            )
        return PolicyDecision(True)

    def tick(self) -> List[Dict[str, object]]:
        cleared: List[Dict[str, object]] = []
        for key in list(self.slice_cooldowns.keys()):
            next_value = int(self.slice_cooldowns[key]) - 1
            if next_value <= 0:
                del self.slice_cooldowns[key]
                cleared.append({"slice_key": key})
            else:
                self.slice_cooldowns[key] = next_value
        return cleared

    def health(self) -> Dict[str, Dict[str, object]]:
        health: Dict[str, Dict[str, object]] = {}
        for key, bucket in self.slice_recent_trades.items():
            stats = self.stats(bucket)
            health[key] = {
                "trades": stats.trades,
                "wins": stats.wins,
                "losses": stats.losses,
                "win_rate": round(stats.win_rate, 4),
                "expectancy_r": round(stats.expectancy_r, 6),
                "cooldown_cycles_left": int(self.slice_cooldowns.get(key, 0)),
            }
        return health
