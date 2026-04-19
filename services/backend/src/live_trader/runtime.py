from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from src.models import ClosedTrade


class TraderRuntimeMixin:
    @staticmethod
    def _normalize_symbols(symbols: List[str]) -> List[str]:
        out: List[str] = []
        for symbol in symbols or []:
            clean = str(symbol).strip().upper()
            if not clean or clean in out:
                continue
            out.append(clean)
        return out

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _stdout_targets_events_file(self) -> bool:
        try:
            stdout_target = Path(os.readlink("/proc/self/fd/1")).resolve()
            return stdout_target == self.events_file.resolve()
        except Exception:
            return False

    def _emit_event(self, payload: Dict, persist: bool = False) -> None:
        line = json.dumps(payload)
        print(line)
        if not persist or self._stdout_targets_events_file():
            return
        try:
            self.events_file.parent.mkdir(parents=True, exist_ok=True)
            with self.events_file.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")
        except Exception:
            pass

    def _apply_runtime_control(self) -> None:
        try:
            if not self.runtime_control_file.exists():
                return
            stats = self.runtime_control_file.stat()
            mtime_ns = int(stats.st_mtime_ns)
            if self._runtime_control_mtime_ns is not None and mtime_ns <= self._runtime_control_mtime_ns:
                return
            payload = json.loads(self.runtime_control_file.read_text(encoding="utf-8"))
            symbols = payload.get("symbols")
            if not isinstance(symbols, list):
                self._runtime_control_mtime_ns = mtime_ns
                return
            normalized = self._normalize_symbols(symbols)
            if not normalized:
                self._runtime_control_mtime_ns = mtime_ns
                return
            if normalized != self.symbols:
                old_symbols = self.symbols[:]
                self.symbols = normalized
                base_conf = float(self.strategy_payload.get("min_confidence", 0.6))
                new_conf: Dict[str, float] = {}
                for symbol in self.symbols:
                    new_conf[symbol] = self.symbol_confidence.get(symbol, base_conf)
                self.symbol_confidence = new_conf
                for symbol in self.symbols:
                    self.symbol_recent_trades.setdefault(symbol, [])
                    self.symbol_cooldowns.setdefault(symbol, 0)
                print(
                    json.dumps(
                        {
                            "type": "RUNTIME_SYMBOLS_UPDATED",
                            "time": self._now_iso(),
                            "old_symbols": old_symbols,
                            "new_symbols": self.symbols,
                        }
                    )
                )
            self._runtime_control_mtime_ns = mtime_ns
        except Exception as exc:
            print(json.dumps({"type": "RUNTIME_UPDATE_ERROR", "time": self._now_iso(), "error": str(exc)}))

    def _active_symbols(self) -> List[str]:
        return [s for s in self.symbols if int(self.symbol_cooldowns.get(s, 0)) <= 0]

    def _open_trade_symbols(self) -> set[str]:
        return {managed.signal.symbol for managed in self.open_trades.values()}

    def _decrement_cooldowns(self) -> None:
        changed: List[Dict[str, int]] = []
        for symbol in list(self.symbols):
            remaining = int(self.symbol_cooldowns.get(symbol, 0))
            if remaining <= 0:
                self.symbol_cooldowns[symbol] = 0
                continue
            updated = max(0, remaining - 1)
            self.symbol_cooldowns[symbol] = updated
            if updated == 0:
                changed.append({"symbol": symbol, "cooldown_cycles_left": 0})
        if changed:
            print(json.dumps({"type": "SYMBOL_COOLDOWN_CLEARED", "time": self._now_iso(), "symbols": changed}))
        for item in self.policy_engine.tick():
            print(json.dumps({"type": "SETUP_SIDE_COOLDOWN_CLEARED", "time": self._now_iso(), "slice_key": item["slice_key"]}))

    @staticmethod
    def _stats(trades: List[ClosedTrade]) -> Dict:
        count = len(trades)
        wins = sum(1 for t in trades if t.result == "WIN")
        losses = count - wins
        win_rate = (wins / count) if count else 0.0
        expectancy_r = (sum(t.pnl_r for t in trades) / count) if count else 0.0
        return {"trades": count, "wins": wins, "losses": losses, "win_rate": win_rate, "expectancy_r": expectancy_r}

    def _record_trade(self, trade: ClosedTrade) -> None:
        self.recent_trades.append(trade)
        max_global = max(self.target_trades * 2, self.guard_global_window * 4, 40)
        if len(self.recent_trades) > max_global:
            del self.recent_trades[:-max_global]
        bucket = self.symbol_recent_trades[trade.symbol]
        bucket.append(trade)
        max_symbol = max(self.guard_symbol_window * 3, 20)
        if len(bucket) > max_symbol:
            del bucket[:-max_symbol]

    @staticmethod
    def _utc_day_from_ms(timestamp_ms: int) -> str:
        return datetime.fromtimestamp(int(timestamp_ms) / 1000.0, tz=timezone.utc).date().isoformat()

    def _current_utc_day(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _daily_realized_pnl(self, utc_day: Optional[str] = None) -> Dict[str, float | int | str]:
        day = utc_day or self._current_utc_day()
        realized = [trade for trade in self.recent_trades if self._utc_day_from_ms(trade.closed_at_ms) == day]
        pnl_r = sum(float(trade.pnl_r) for trade in realized)
        pnl_usd = sum(float(trade.pnl_usd) for trade in realized)
        return {"utc_day": day, "trades": len(realized), "pnl_r": round(pnl_r, 6), "pnl_usd": round(pnl_usd, 6)}

    def _apply_performance_guard(self, cycle: int) -> None:
        if not self.guard_enabled:
            return
        active_symbols = self._active_symbols()
        for symbol in list(self.symbols):
            if int(self.symbol_cooldowns.get(symbol, 0)) > 0:
                continue
            if len(active_symbols) <= self.guard_min_active_symbols:
                break
            bucket = self.symbol_recent_trades.get(symbol, [])
            stats = self._stats(bucket[-self.guard_symbol_window :])
            if stats["trades"] < self.guard_min_symbol_trades:
                continue
            bad_symbol = stats["win_rate"] < self.guard_min_symbol_win_rate or stats["expectancy_r"] < self.guard_min_symbol_expectancy_r
            if not bad_symbol:
                continue
            self.symbol_cooldowns[symbol] = max(self.guard_cooldown_cycles, int(self.symbol_cooldowns.get(symbol, 0)))
            active_symbols = self._active_symbols()
            print(
                json.dumps(
                    {
                        "type": "SYMBOL_COOLDOWN_APPLIED",
                        "time": self._now_iso(),
                        "cycle": cycle,
                        "symbol": symbol,
                        "cooldown_cycles": self.symbol_cooldowns[symbol],
                        "stats": {
                            "trades": stats["trades"],
                            "wins": stats["wins"],
                            "losses": stats["losses"],
                            "win_rate": round(stats["win_rate"], 4),
                            "expectancy_r": round(stats["expectancy_r"], 6),
                        },
                        "thresholds": {
                            "min_symbol_win_rate": self.guard_min_symbol_win_rate,
                            "min_symbol_expectancy_r": self.guard_min_symbol_expectancy_r,
                        },
                    }
                )
            )
        recent = self.recent_trades[-self.guard_global_window :]
        global_stats = self._stats(recent)
        if global_stats["trades"] < max(4, self.guard_global_window // 2):
            return
        changed = False
        if global_stats["win_rate"] < self.guard_global_min_win_rate or global_stats["expectancy_r"] < self.guard_global_min_expectancy_r:
            prev = {
                "min_candidate_confidence": self.min_candidate_confidence,
                "min_rr_floor": self.min_rr_floor,
                "min_trend_strength": self.min_trend_strength,
            }
            self.min_candidate_confidence = min(0.95, self.min_candidate_confidence + 0.01)
            self.min_rr_floor = min(0.85, self.min_rr_floor + 0.01)
            self.min_trend_strength = min(0.0045, self.min_trend_strength + 0.00003)
            changed = True
            direction = "TIGHTEN"
        elif global_stats["win_rate"] >= (self.guard_global_min_win_rate + 0.12) and global_stats["expectancy_r"] >= (self.guard_global_min_expectancy_r + 0.05):
            prev = {
                "min_candidate_confidence": self.min_candidate_confidence,
                "min_rr_floor": self.min_rr_floor,
                "min_trend_strength": self.min_trend_strength,
            }
            self.min_candidate_confidence = max(0.65, self.min_candidate_confidence - 0.005)
            self.min_rr_floor = max(0.25, self.min_rr_floor - 0.005)
            self.min_trend_strength = max(0.0007, self.min_trend_strength - 0.00001)
            changed = True
            direction = "RELAX"
        if changed:
            print(
                json.dumps(
                    {
                        "type": "GUARD_RETUNE",
                        "time": self._now_iso(),
                        "cycle": cycle,
                        "direction": direction,
                        "recent_global_stats": {
                            "trades": global_stats["trades"],
                            "wins": global_stats["wins"],
                            "losses": global_stats["losses"],
                            "win_rate": round(global_stats["win_rate"], 4),
                            "expectancy_r": round(global_stats["expectancy_r"], 6),
                        },
                        "previous": prev,
                        "updated": {
                            "min_candidate_confidence": round(self.min_candidate_confidence, 6),
                            "min_rr_floor": round(self.min_rr_floor, 6),
                            "min_trend_strength": round(self.min_trend_strength, 6),
                        },
                    }
                )
            )
