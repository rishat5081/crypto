import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.live_trader import LiveAdaptivePaperTrader
from src.models import Candle, ClosedTrade, MarketContext, Signal

from .support import _EnabledExecutor, _candidate, _config, _json_lines, _trader


class LiveAdaptivePaperTraderRuntimeTests(unittest.TestCase):
    def test_orphan_close_events_are_persisted_to_runtime_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.json"
            runtime_dir = root / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            cfg = _config()
            cfg["live_loop"]["close_orphaned_positions_on_startup"] = True
            cfg["live_loop"]["runtime_control_file"] = str(runtime_dir / "runtime_control.json")
            cfg["_config_path"] = str(config_path)
            config_path.write_text(json.dumps(cfg), encoding="utf-8")
            executor = _EnabledExecutor(account={"positions": [{"symbol": "DOTUSDT", "positionAmt": "190.5", "entryPrice": "1.31", "unrealizedProfit": "-4.85748901"}]}, close_result={"status": "closed", "executed": True, "entry_price": 1.31, "quantity": 190.5, "unrealized_pnl": -4.85748901})
            with patch("src.live_trader.bootstrap.BinanceExecutor.from_env", return_value=executor):
                LiveAdaptivePaperTrader(cfg)
            rows = [json.loads(line) for line in (runtime_dir / "live_events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(rows[0]["action"], "ORPHAN_DETECTED")
            self.assertEqual(rows[1]["action"], "ORPHAN_CLOSE")

    def test_paper_risk_override_is_used(self) -> None:
        cfg = _config()
        cfg["account"]["paper_risk_usd"] = 5.0
        trader = _trader(cfg)
        self.assertEqual(trader.risk_usd, 5.0)
        self.assertEqual(trader.risk_sizing_mode, "paper_risk_usd")

    def test_filter_rejection_telemetry_is_reported(self) -> None:
        cfg = _config()
        cfg["live_loop"]["require_dual_timeframe_confirm"] = True
        trader = _trader(cfg)
        candidates = [_candidate("CONFUSDT", 0.60, 0.30, 0.90), _candidate("EXPUSDT", 0.80, 0.05, 0.90), _candidate("SCOREUSDT", 0.80, 0.30, 0.60), _candidate("WINUSDT", 0.80, 0.30, 0.90), _candidate("DUALUSDT", 0.80, 0.30, 0.90)]

        def fake_win_probability(candidate):
            return 0.40 if candidate.signal.symbol == "WINUSDT" else 0.80

        with patch("src.live_trader.loop.time.sleep", lambda *_: None), patch("builtins.print") as fake_print:
            trader._refresh_batch_market_data = lambda: None
            trader._signal_candidates = lambda: candidates
            trader._estimate_win_probability = fake_win_probability
            result = trader.run()
        printed = _json_lines(fake_print.mock_calls)
        summary = result["summary"]
        self.assertEqual(summary["filter_rejections"]["candidate_confidence"], 1)
        self.assertEqual(summary["filter_rejections"]["execute_dual_timeframe_confirm"], 1)
        possible_trades = next(event for event in printed if event["type"] == "POSSIBLE_TRADES")
        self.assertEqual(possible_trades["candidate_rejections"]["candidate_expectancy"], 1)

    def test_underperforming_setup_side_is_paused_by_policy(self) -> None:
        trader = _trader(_config())
        for idx in range(3):
            trader.policy_engine.record_trade(signal_type="PULLBACK", side="SHORT", trade=ClosedTrade(symbol=f"LOSS{idx}USDT", timeframe="5m", side="SHORT", entry=100.0, take_profit=99.0, stop_loss=101.0, exit_price=101.0, result="LOSS", opened_at_ms=1, closed_at_ms=2 + idx, pnl_r=-1.0, pnl_usd=-0.2, reason="SHORT pullback | test"))
        with patch("src.live_trader.loop.time.sleep", lambda *_: None), patch("builtins.print") as fake_print:
            trader._refresh_batch_market_data = lambda: None
            trader._signal_candidates = lambda: [_candidate("BTCUSDT", 0.9, 0.5, 0.9, reason="SHORT pullback | test", side="SHORT")]
            trader._estimate_win_probability = lambda candidate: 0.9
            result = trader.run()
        printed = _json_lines(fake_print.mock_calls)
        self.assertEqual(next(event for event in printed if event["type"] == "NO_SIGNAL")["execution_rejections"]["policy_setup_side_paused"], 1)
        self.assertGreater(result["summary"]["setup_side_health"]["PULLBACK|SHORT"]["cooldown_cycles_left"], 0)

    def test_invalid_symbols_are_filtered_from_watchlist(self) -> None:
        cfg = _config()
        cfg["live_loop"]["invalid_symbol_failure_threshold"] = 1
        cfg["live_loop"]["symbols"] = ["BTCUSDT", "BADUSDT"]
        trader = _trader(cfg)
        with patch("builtins.print") as fake_print:
            trader.client.fetch_all_premium_index = lambda: {"BTCUSDT": object()}
            trader.client.fetch_all_ticker_prices = lambda: {"BTCUSDT": 100.0}
            trader._refresh_batch_market_data()
        printed = _json_lines(fake_print.mock_calls)
        self.assertEqual(trader.symbols, ["BTCUSDT"])
        self.assertEqual(next(event for event in printed if event["type"] == "SYMBOLS_FILTERED")["removed"][0]["symbol"], "BADUSDT")

    def test_signal_candidates_emit_rejection_summary(self) -> None:
        cfg = _config()
        cfg["live_loop"]["symbols"] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        trader = _trader(cfg)
        trader._get_klines_window = lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        trader._premium_cache = {symbol: MarketContext(mark_price=100.0, funding_rate=0.0, open_interest=100000.0) for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]}
        candles = [Candle(open_time_ms=(idx + 1) * 60000, open=100.0 + (idx * 0.1), high=100.5 + (idx * 0.1), low=99.5 + (idx * 0.1), close=100.0 + (idx * 0.1), volume=10.0, close_time_ms=((idx + 1) * 60000) + 1) for idx in range(80)]
        trader.client.fetch_klines = lambda symbol, interval, limit: candles
        signals = {"BTCUSDT": None, "ETHUSDT": Signal(symbol="ETHUSDT", timeframe="5m", side="LONG", entry=100.0, take_profit=100.2, stop_loss=99.0, confidence=0.9, reason="LONG crossover | test", signal_time_ms=1), "SOLUSDT": Signal(symbol="SOLUSDT", timeframe="5m", side="LONG", entry=100.0, take_profit=101.0, stop_loss=99.0, confidence=0.9, reason="LONG crossover | test", signal_time_ms=1)}
        def fake_strategy_from_config(_payload):
            return SimpleNamespace(evaluate=lambda symbol, timeframe, passed_candles, market, diagnostics=None: signals[symbol])
        with patch("src.live_trader.signals.StrategyService.from_config", side_effect=fake_strategy_from_config), patch("builtins.print") as fake_print, patch.object(trader, "_candidate_quality_block_reason", return_value="weak_crossover_confidence"):
            candidates = trader._signal_candidates()
        printed = _json_lines(fake_print.mock_calls)
        self.assertEqual(candidates, [])
        summary = next(event for event in printed if event["type"] == "CANDIDATE_REJECTION_SUMMARY")
        self.assertEqual(summary["counts"]["strategy_returned_none"], 1)

    def test_signal_candidates_drop_unfinished_last_candle(self) -> None:
        cfg = _config()
        cfg["live_loop"]["symbols"] = ["BTCUSDT"]
        trader = _trader(cfg)
        trader._get_klines_window = lambda: ["BTCUSDT"]
        trader._premium_cache = {"BTCUSDT": MarketContext(mark_price=100.0, funding_rate=0.0, open_interest=100000.0)}
        now_ms = 1_000_000
        candles = [Candle(open_time_ms=idx * 60000, open=100.0, high=101.0, low=99.0, close=100.0 + (idx * 0.01), volume=10.0, close_time_ms=(idx + 1) * 1000) for idx in range(79)]
        candles.append(Candle(open_time_ms=79 * 60000, open=100.0, high=101.0, low=99.0, close=100.79, volume=10.0, close_time_ms=now_ms + 60000))
        trader.client.fetch_klines = lambda symbol, interval, limit: candles
        seen = {}
        def fake_strategy_from_config(_payload):
            def evaluate(symbol, timeframe, passed_candles, market, diagnostics=None):
                seen["count"] = len(passed_candles)
                seen["last_close_time_ms"] = passed_candles[-1].close_time_ms
                return None
            return SimpleNamespace(evaluate=evaluate)
        with patch("src.live_trader.signals.StrategyService.from_config", side_effect=fake_strategy_from_config), patch("src.live_trader.signals.time.time", return_value=now_ms / 1000.0), patch("builtins.print", lambda *_: None):
            trader._signal_candidates()
        self.assertEqual(seen["count"], 79)
        self.assertLess(seen["last_close_time_ms"], now_ms)
