from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _parse_trade_results(events_file: Path) -> List[Dict[str, Any]]:
    if not events_file.exists():
        return []

    out: List[Dict[str, Any]] = []
    with events_file.open("r", encoding="utf-8", errors="ignore") as fp:
        for raw in fp:
            line = raw.strip().lstrip("\x07")
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") != "TRADE_RESULT":
                continue
            trade = event.get("trade")
            if isinstance(trade, dict):
                out.append(trade)
    return out


def _stats(trades: List[Dict[str, Any]]) -> Dict[str, float]:
    count = len(trades)
    if count == 0:
        return {"trades": 0.0, "wins": 0.0, "losses": 0.0, "win_rate": 0.0, "expectancy_r": 0.0}

    wins = 0
    pnl_sum = 0.0
    for trade in trades:
        if str(trade.get("result", "")).upper() == "WIN":
            wins += 1
        try:
            pnl_sum += float(trade.get("pnl_r", 0.0))
        except (TypeError, ValueError):
            continue
    losses = count - wins
    return {
        "trades": float(count),
        "wins": float(wins),
        "losses": float(losses),
        "win_rate": float(wins) / float(count),
        "expectancy_r": pnl_sum / float(count),
    }


def _round_live_cfg(live: Dict[str, Any]) -> None:
    for key in (
        "min_candidate_confidence",
        "min_candidate_expectancy_r",
        "execute_min_confidence",
        "execute_min_expectancy_r",
        "execute_min_score",
        "min_rr_floor",
        "min_trend_strength",
        "min_score_gap",
        "relax_conf_step",
        "relax_expectancy_step",
        "relax_score_step",
        "relax_min_execute_confidence",
        "relax_min_execute_expectancy_r",
        "relax_min_execute_score",
    ):
        if key in live:
            try:
                live[key] = round(float(live[key]), 6)
            except (TypeError, ValueError):
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Retune live_loop thresholds using longer multi-coin trade history")
    parser.add_argument("--config", default="config.json", help="Path to config file")
    parser.add_argument("--events-file", default="/tmp/crypto-runtime/live_events.jsonl", help="Path to live events JSONL file")
    parser.add_argument("--lookback-trades", type=int, default=300, help="Use most recent N closed trades")
    parser.add_argument("--min-trades", type=int, default=20, help="Minimum trade count required to retune")
    parser.add_argument("--apply", action="store_true", help="Write tuned values back to config")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    events_path = Path(args.events_file).resolve()

    config = _load_json(config_path)
    live = config.setdefault("live_loop", {})
    live.setdefault("symbols", config.get("pairs", []))
    live.setdefault("timeframes", config.get("timeframes", ["5m", "15m"]))
    live.setdefault("target_win_rate", 0.75)
    live.setdefault("min_candidate_confidence", 0.7)
    live.setdefault("min_candidate_expectancy_r", 0.0)
    live.setdefault("execute_min_confidence", 0.86)
    live.setdefault("execute_min_expectancy_r", 0.22)
    live.setdefault("execute_min_score", 0.68)
    live.setdefault("min_rr_floor", 0.35)
    live.setdefault("min_trend_strength", 0.0012)
    live.setdefault("min_score_gap", 0.02)
    live.setdefault("max_parallel_candidates", 500)
    live.setdefault("possible_trades_limit", 500)

    trades = _parse_trade_results(events_path)
    if args.lookback_trades > 0:
        trades = trades[-int(args.lookback_trades) :]
    global_stats = _stats(trades)
    enough_data = int(global_stats["trades"]) >= int(args.min_trades)

    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for trade in trades:
        symbol = str(trade.get("symbol") or "").upper()
        if not symbol:
            continue
        by_symbol.setdefault(symbol, []).append(trade)

    symbol_stats: Dict[str, Dict[str, float]] = {}
    for symbol, bucket in by_symbol.items():
        symbol_stats[symbol] = _stats(bucket)

    current = {
        "min_candidate_confidence": float(live.get("min_candidate_confidence", 0.7)),
        "min_candidate_expectancy_r": float(live.get("min_candidate_expectancy_r", 0.0)),
        "execute_min_confidence": float(live.get("execute_min_confidence", 0.86)),
        "execute_min_expectancy_r": float(live.get("execute_min_expectancy_r", 0.22)),
        "execute_min_score": float(live.get("execute_min_score", 0.68)),
        "min_rr_floor": float(live.get("min_rr_floor", 0.35)),
        "min_trend_strength": float(live.get("min_trend_strength", 0.0012)),
        "min_score_gap": float(live.get("min_score_gap", 0.02)),
    }
    tuned = dict(current)
    direction = "UNCHANGED"

    target_win_rate = float(live.get("target_win_rate", 0.75))
    if enough_data:
        win_rate = float(global_stats["win_rate"])
        expectancy_r = float(global_stats["expectancy_r"])

        if win_rate < (target_win_rate - 0.08) or expectancy_r < 0.0:
            direction = "TIGHTEN"
            tuned["min_candidate_confidence"] = _clamp(tuned["min_candidate_confidence"] + 0.01, 0.65, 0.96)
            tuned["min_candidate_expectancy_r"] = _clamp(tuned["min_candidate_expectancy_r"] + 0.02, -0.05, 0.5)
            tuned["execute_min_confidence"] = _clamp(tuned["execute_min_confidence"] + 0.01, 0.78, 0.98)
            tuned["execute_min_expectancy_r"] = _clamp(tuned["execute_min_expectancy_r"] + 0.03, 0.0, 1.2)
            tuned["execute_min_score"] = _clamp(tuned["execute_min_score"] + 0.01, 0.6, 0.98)
            tuned["min_rr_floor"] = _clamp(tuned["min_rr_floor"] + 0.01, 0.2, 1.2)
            tuned["min_trend_strength"] = _clamp(tuned["min_trend_strength"] + 0.00005, 0.0003, 0.01)
            tuned["min_score_gap"] = _clamp(tuned["min_score_gap"] + 0.002, 0.0, 0.08)
        elif win_rate > (target_win_rate + 0.05) and expectancy_r > 0.06:
            direction = "RELAX"
            tuned["min_candidate_confidence"] = _clamp(tuned["min_candidate_confidence"] - 0.005, 0.6, 0.96)
            tuned["min_candidate_expectancy_r"] = _clamp(tuned["min_candidate_expectancy_r"] - 0.01, -0.1, 0.5)
            tuned["execute_min_confidence"] = _clamp(tuned["execute_min_confidence"] - 0.005, 0.75, 0.98)
            tuned["execute_min_expectancy_r"] = _clamp(tuned["execute_min_expectancy_r"] - 0.01, -0.05, 1.2)
            tuned["execute_min_score"] = _clamp(tuned["execute_min_score"] - 0.005, 0.55, 0.98)
            tuned["min_rr_floor"] = _clamp(tuned["min_rr_floor"] - 0.005, 0.2, 1.2)
            tuned["min_trend_strength"] = _clamp(tuned["min_trend_strength"] - 0.00002, 0.00025, 0.01)
            tuned["min_score_gap"] = _clamp(tuned["min_score_gap"] - 0.001, 0.0, 0.08)

    symbols_count = max(1, len(live.get("symbols") or []))
    live["possible_trades_limit"] = int(_clamp(float(live.get("possible_trades_limit", 500)), 50.0, 5000.0))
    live["max_parallel_candidates"] = max(int(live["possible_trades_limit"]), symbols_count * 10)

    for key, value in tuned.items():
        live[key] = value

    _round_live_cfg(live)

    report = {
        "type": "RETUNE_THRESHOLDS",
        "config": str(config_path),
        "events_file": str(events_path),
        "lookback_trades": int(args.lookback_trades),
        "min_trades_required": int(args.min_trades),
        "enough_data": enough_data,
        "global_stats": {
            "trades": int(global_stats["trades"]),
            "wins": int(global_stats["wins"]),
            "losses": int(global_stats["losses"]),
            "win_rate": round(float(global_stats["win_rate"]), 6),
            "expectancy_r": round(float(global_stats["expectancy_r"]), 6),
        },
        "direction": direction,
        "before": {k: round(v, 6) for k, v in current.items()},
        "after": {k: round(float(live.get(k, 0.0)), 6) for k in current.keys()},
        "possible_trades_limit": int(live["possible_trades_limit"]),
        "max_parallel_candidates": int(live["max_parallel_candidates"]),
        "top_symbols": sorted(
            (
                {
                    "symbol": sym,
                    "trades": int(st["trades"]),
                    "win_rate": round(float(st["win_rate"]), 4),
                    "expectancy_r": round(float(st["expectancy_r"]), 4),
                }
                for sym, st in symbol_stats.items()
            ),
            key=lambda row: (row["expectancy_r"], row["win_rate"], row["trades"]),
            reverse=True,
        )[:20],
    }

    if args.apply:
        _save_json(config_path, config)
        report["applied"] = True
    else:
        report["applied"] = False

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
