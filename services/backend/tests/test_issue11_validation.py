import json
import tempfile
import unittest
from pathlib import Path

from src.issue11_validation import compare_summaries, load_trade_records, summarize_records


class Issue11ValidationTests(unittest.TestCase):
    def test_load_trade_records_deduplicates_by_trade_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history.jsonl"
            trade = {
                "symbol": "BTCUSDT",
                "timeframe": "5m",
                "side": "LONG",
                "entry": 100.0,
                "take_profit": 101.0,
                "stop_loss": 99.0,
                "exit_price": 99.4,
                "result": "LOSS",
                "opened_at_ms": 1000,
                "closed_at_ms": 2000,
                "pnl_r": -0.6,
                "pnl_usd": -0.12,
                "reason": "ADVERSE_CUT | LONG crossover | regime=TRENDING | test",
            }
            events = [
                {"type": "TRADE_RESULT", "time": "2026-04-09T10:00:00+00:00", "trade": trade},
                {"type": "TRADE_RESULT", "time": "2026-04-09T10:00:05+00:00", "trade": dict(trade)},
            ]
            history.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

            rows = load_trade_records(history)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].trade_key, "BTCUSDT|5m|LONG|1000|2000")
            self.assertEqual(rows[0].regime, "TRENDING")

    def test_summarize_records_returns_issue11_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history.jsonl"
            events = [
                {
                    "type": "TRADE_RESULT",
                    "time": "2026-04-09T10:00:00+00:00",
                    "trade": {
                        "symbol": "BTCUSDT",
                        "timeframe": "5m",
                        "side": "LONG",
                        "entry": 100.0,
                        "take_profit": 101.0,
                        "stop_loss": 99.0,
                        "exit_price": 99.4,
                        "result": "LOSS",
                        "opened_at_ms": 1000,
                        "closed_at_ms": 601000,
                        "pnl_r": -0.6,
                        "pnl_usd": -0.12,
                        "reason": "ADVERSE_CUT | LONG crossover | regime=TRENDING | test",
                    },
                    "trade_meta": {"signal_type": "CROSSOVER", "exit_type": "ADVERSE_CUT", "stop_state": "ORIGINAL", "hold_minutes": 10.0},
                },
                {
                    "type": "TRADE_RESULT",
                    "time": "2026-04-09T11:00:00+00:00",
                    "trade": {
                        "symbol": "ETHUSDT",
                        "timeframe": "15m",
                        "side": "LONG",
                        "entry": 200.0,
                        "take_profit": 202.0,
                        "stop_loss": 198.0,
                        "exit_price": 202.0,
                        "result": "WIN",
                        "opened_at_ms": 1000,
                        "closed_at_ms": 3601000,
                        "pnl_r": 1.0,
                        "pnl_usd": 0.2,
                        "reason": "TP_HIT | LONG pullback | regime=RANGING | test",
                    },
                    "trade_meta": {"signal_type": "PULLBACK", "exit_type": "DIRECT_TP", "stop_state": "TRAILING", "hold_minutes": 60.0},
                },
            ]
            history.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

            summary = summarize_records(load_trade_records(history))

            self.assertEqual(summary["worst_symbols"][0]["label"], "BTCUSDT")
            self.assertEqual(summary["worst_regimes"][0]["label"], "TRENDING")
            self.assertEqual(summary["worst_exit_types"][0]["label"], "ADVERSE_CUT")
            self.assertEqual(summary["worst_signal_exit_combos"][0]["label"], "CROSSOVER x ADVERSE_CUT")
            self.assertEqual(summary["adverse_cut_count"], 1)

    def test_signal_type_parser_supports_new_strategy_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history.jsonl"
            events = [
                {
                    "type": "TRADE_RESULT",
                    "time": "2026-04-09T10:00:00+00:00",
                    "trade": {
                        "symbol": "SOLUSDT",
                        "timeframe": "5m",
                        "side": "SHORT",
                        "entry": 100.0,
                        "take_profit": 98.0,
                        "stop_loss": 101.0,
                        "exit_price": 101.0,
                        "result": "LOSS",
                        "opened_at_ms": 1000,
                        "closed_at_ms": 2000,
                        "pnl_r": -1.0,
                        "pnl_usd": -0.2,
                        "reason": "DIRECT_SL | SHORT bb_reversion | regime=RANGING | test",
                    },
                }
            ]
            history.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

            rows = load_trade_records(history)

            self.assertEqual(rows[0].signal_type, "BB_REVERSION")
            self.assertEqual(rows[0].regime, "RANGING")

    def test_compare_summaries_returns_metric_deltas(self) -> None:
        delta = compare_summaries(
            {"win_rate": 0.4, "expectancy_r": -0.1, "adverse_cut_count": 5},
            {"win_rate": 0.6, "expectancy_r": 0.2, "adverse_cut_count": 2},
        )
        self.assertEqual(delta["win_rate"], 0.2)
        self.assertEqual(delta["expectancy_r"], 0.3)
        self.assertEqual(delta["adverse_cut_count"], -3)


if __name__ == "__main__":
    unittest.main()
