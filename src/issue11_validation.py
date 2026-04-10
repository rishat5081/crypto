from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True)
class TradeRecord:
    trade_key: str
    symbol: str
    timeframe: str
    side: str
    result: str
    pnl_r: float
    pnl_usd: float
    opened_at_ms: Optional[int]
    closed_at_ms: Optional[int]
    signal_type: str
    exit_type: str
    stop_state: str
    hold_minutes: Optional[float]


def _trade_key(event: Dict[str, Any], trade: Dict[str, Any]) -> str:
    symbol = str(trade.get("symbol") or "").upper()
    timeframe = str(trade.get("timeframe") or "")
    side = str(trade.get("side") or "")
    opened = trade.get("opened_at_ms")
    closed = trade.get("closed_at_ms")
    if opened is not None or closed is not None:
        return f"{symbol}|{timeframe}|{side}|{opened}|{closed}"
    result = str(trade.get("result") or "")
    event_time = str(event.get("time") or "")
    return f"{symbol}|{timeframe}|{side}|{result}|{event_time}"


def _signal_type(reason: str, trade_meta: Dict[str, Any]) -> str:
    explicit = str(trade_meta.get("signal_type") or "").upper()
    if explicit:
        return explicit
    upper = str(reason or "").upper()
    if "PULLBACK" in upper:
        return "PULLBACK"
    if "MOMENTUM" in upper:
        return "MOMENTUM"
    if "CROSSOVER" in upper:
        return "CROSSOVER"
    return "UNKNOWN"


def _exit_type(reason: str, result: str, trade_meta: Dict[str, Any]) -> str:
    explicit = str(trade_meta.get("exit_type") or "").upper()
    if explicit:
        return explicit
    upper = str(reason or "").upper()
    result_upper = str(result or "").upper()
    if "ADVERSE_CUT" in upper:
        return "ADVERSE_CUT"
    if "MOMENTUM_REVERSAL" in upper:
        return "MOMENTUM_REVERSAL"
    if "STAGNATION" in upper:
        return "STAGNATION_EXIT"
    if "TIMEOUT" in upper:
        return "TIMEOUT_EXIT"
    if "NETWORK_ERROR" in upper:
        return "NETWORK_ERROR_EXIT"
    if result_upper == "WIN":
        return "DIRECT_TP"
    if result_upper == "LOSS":
        return "DIRECT_SL"
    return "DIRECT_EXIT"


def _hold_minutes(trade: Dict[str, Any], trade_meta: Dict[str, Any]) -> Optional[float]:
    explicit = trade_meta.get("hold_minutes")
    if explicit is not None:
        try:
            return float(explicit)
        except (TypeError, ValueError):
            return None
    opened = trade.get("opened_at_ms")
    closed = trade.get("closed_at_ms")
    try:
        if opened is None or closed is None:
            return None
        opened_i = int(opened)
        closed_i = int(closed)
    except (TypeError, ValueError):
        return None
    if closed_i <= opened_i:
        return None
    return round((closed_i - opened_i) / 60000.0, 4)


def load_trade_records(history_file: Path) -> list[TradeRecord]:
    deduped: Dict[str, TradeRecord] = {}
    if not history_file.exists():
        return []

    with history_file.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("type") != "TRADE_RESULT":
                continue
            trade = event.get("trade") or {}
            if not isinstance(trade, dict) or not trade:
                continue

            trade_meta = event.get("trade_meta") or {}
            reason = str(trade.get("reason") or "")
            result = str(trade.get("result") or "")
            key = _trade_key(event, trade)
            record = TradeRecord(
                trade_key=key,
                symbol=str(trade.get("symbol") or "").upper(),
                timeframe=str(trade.get("timeframe") or ""),
                side=str(trade.get("side") or "").upper(),
                result=result.upper(),
                pnl_r=float(trade.get("pnl_r") or 0.0),
                pnl_usd=float(trade.get("pnl_usd") or 0.0),
                opened_at_ms=int(trade["opened_at_ms"]) if trade.get("opened_at_ms") is not None else None,
                closed_at_ms=int(trade["closed_at_ms"]) if trade.get("closed_at_ms") is not None else None,
                signal_type=_signal_type(reason, trade_meta),
                exit_type=_exit_type(reason, result, trade_meta),
                stop_state=str(trade_meta.get("stop_state") or "ORIGINAL").upper(),
                hold_minutes=_hold_minutes(trade, trade_meta),
            )
            deduped[key] = record

    return sorted(deduped.values(), key=lambda row: (row.closed_at_ms or 0, row.trade_key))


def _bucket_rows(rows: Iterable[TradeRecord], label_getter) -> list[Dict[str, Any]]:
    stats: Dict[str, Dict[str, float]] = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "pnl_r": 0.0, "pnl_usd": 0.0})
    for row in rows:
        label = str(label_getter(row) or "UNKNOWN")
        bucket = stats[label]
        bucket["trades"] += 1
        if row.result == "WIN":
            bucket["wins"] += 1
        elif row.result == "LOSS":
            bucket["losses"] += 1
        bucket["pnl_r"] += row.pnl_r
        bucket["pnl_usd"] += row.pnl_usd

    output = []
    for label, bucket in sorted(stats.items(), key=lambda item: (item[1]["pnl_usd"], item[0])):
        trades = int(bucket["trades"])
        output.append(
            {
                "label": label,
                "trades": trades,
                "wins": int(bucket["wins"]),
                "losses": int(bucket["losses"]),
                "win_rate": round(bucket["wins"] / trades, 4) if trades else 0.0,
                "pnl_r": round(bucket["pnl_r"], 4),
                "pnl_usd": round(bucket["pnl_usd"], 4),
            }
        )
    return output


def summarize_records(rows: list[TradeRecord]) -> Dict[str, Any]:
    wins = sum(1 for row in rows if row.result == "WIN")
    losses = sum(1 for row in rows if row.result == "LOSS")
    total = len(rows)
    total_pnl_r = sum(row.pnl_r for row in rows)
    total_pnl_usd = sum(row.pnl_usd for row in rows)
    adverse_cut_count = sum(1 for row in rows if row.exit_type == "ADVERSE_CUT")
    holds = [row.hold_minutes for row in rows if row.hold_minutes is not None]

    summary = {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total, 4) if total else 0.0,
        "expectancy_r": round(total_pnl_r / total, 4) if total else 0.0,
        "net_pnl_usd": round(total_pnl_usd, 4),
        "adverse_cut_count": adverse_cut_count,
        "adverse_cut_frequency": round(adverse_cut_count / total, 4) if total else 0.0,
        "avg_hold_minutes": round(sum(holds) / len(holds), 4) if holds else 0.0,
        "per_signal_type": _bucket_rows(rows, lambda row: row.signal_type),
        "per_exit_type": _bucket_rows(rows, lambda row: row.exit_type),
        "per_signal_exit_combo": _bucket_rows(rows, lambda row: f"{row.signal_type} x {row.exit_type}"),
        "per_symbol": _bucket_rows(rows, lambda row: row.symbol),
    }
    summary["worst_symbols"] = summary["per_symbol"][:5]
    summary["worst_exit_types"] = summary["per_exit_type"][:5]
    summary["worst_signal_exit_combos"] = summary["per_signal_exit_combo"][:5]
    return summary


def compare_summaries(baseline: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "total_trades",
        "wins",
        "losses",
        "win_rate",
        "expectancy_r",
        "net_pnl_usd",
        "adverse_cut_count",
        "adverse_cut_frequency",
        "avg_hold_minutes",
    ]
    delta: Dict[str, Any] = {}
    for key in keys:
        before = baseline.get(key, 0)
        after = current.get(key, 0)
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            delta[key] = round(after - before, 4)
    return delta
