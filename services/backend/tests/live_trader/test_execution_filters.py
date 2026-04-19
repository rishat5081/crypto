import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from src.models import ClosedTrade, MarketContext

from .support import _candidate, _json_lines, _trader


class LiveAdaptivePaperTraderExecutionFilterTests(unittest.TestCase):
    def test_execution_filter_blocks_non_execution_timeframe(self) -> None:
        cfg = _trader().config
        cfg["live_loop"]["timeframes"] = ["5m", "15m"]
        cfg["live_loop"]["execute_timeframes"] = ["15m"]
        trader = _trader(cfg)
        with patch("src.live_trader.loop.time.sleep", lambda *_: None), patch("builtins.print") as fake_print:
            trader._refresh_batch_market_data = lambda: None
            trader._signal_candidates = lambda: [_candidate("BTCUSDT", 0.9, 0.5, 0.9, reason="LONG pullback | regime=TRENDING | test", timeframe="5m")]
            trader._estimate_win_probability = lambda candidate: 0.9
            trader.run()
        printed = _json_lines(fake_print.mock_calls)
        self.assertEqual(next(event for event in printed if event["type"] == "NO_SIGNAL")["execution_rejections"]["execute_timeframe_not_allowed"], 1)

    def test_execution_filter_blocks_disallowed_regime(self) -> None:
        cfg = _trader().config
        cfg["live_loop"]["allowed_execution_regimes"] = ["TRENDING"]
        trader = _trader(cfg)
        with patch("src.live_trader.loop.time.sleep", lambda *_: None), patch("builtins.print") as fake_print:
            trader._refresh_batch_market_data = lambda: None
            trader._signal_candidates = lambda: [_candidate("BTCUSDT", 0.9, 0.5, 0.9, reason="LONG pullback | regime=RANGING | test")]
            trader._estimate_win_probability = lambda candidate: 0.9
            trader.run()
        printed = _json_lines(fake_print.mock_calls)
        self.assertEqual(next(event for event in printed if event["type"] == "NO_SIGNAL")["execution_rejections"]["execute_regime_not_allowed"], 1)

    def test_5m_can_confirm_but_only_15m_executes(self) -> None:
        cfg = _trader().config
        cfg["live_loop"]["timeframes"] = ["5m", "15m"]
        cfg["live_loop"]["execute_timeframes"] = ["15m"]
        cfg["live_loop"]["require_dual_timeframe_confirm"] = True
        trader = _trader(cfg)
        with patch("src.live_trader.loop.time.sleep", lambda *_: None), patch("builtins.print") as fake_print:
            trader._refresh_batch_market_data = lambda: None
            trader._signal_candidates = lambda: [_candidate("BTCUSDT", 0.9, 0.5, 0.85, reason="LONG pullback | regime=TRENDING | test", timeframe="5m"), _candidate("BTCUSDT", 0.92, 0.6, 0.9, reason="LONG pullback | regime=TRENDING | test", timeframe="15m")]
            trader._estimate_win_probability = lambda candidate: 0.9
            trader.run()
        printed = _json_lines(fake_print.mock_calls)
        self.assertEqual(next(event for event in printed if event["type"] == "OPEN_TRADE")["timeframe"], "15m")

    def test_1h_short_can_execute_when_enabled(self) -> None:
        cfg = _trader().config
        cfg["live_loop"]["timeframes"] = ["15m", "1h"]
        cfg["live_loop"]["execute_timeframes"] = ["15m", "1h"]
        trader = _trader(cfg)
        with patch("src.live_trader.loop.time.sleep", lambda *_: None), patch("builtins.print") as fake_print:
            trader._refresh_batch_market_data = lambda: None
            trader._signal_candidates = lambda: [_candidate("ETHUSDT", 0.9, 0.6, 0.92, reason="SHORT pullback | regime=TRENDING | test", side="SHORT", timeframe="1h")]
            trader._estimate_win_probability = lambda candidate: 0.9
            trader.run()
        printed = _json_lines(fake_print.mock_calls)
        open_event = next(event for event in printed if event["type"] == "OPEN_TRADE")
        self.assertEqual(open_event["timeframe"], "1h")
        self.assertEqual(open_event["side"], "SHORT")

    def test_crossover_execution_gate_blocks_marginal_setup(self) -> None:
        cfg = _trader().config
        cfg["live_loop"]["crossover_min_confidence"] = 0.84
        cfg["live_loop"]["crossover_execute_min_confidence"] = 0.84
        cfg["live_loop"]["crossover_execute_min_expectancy_r"] = 0.32
        cfg["live_loop"]["crossover_execute_min_score"] = 0.86
        cfg["live_loop"]["crossover_execute_min_win_probability"] = 0.72
        trader = _trader(cfg)
        with patch("src.live_trader.loop.time.sleep", lambda *_: None), patch("builtins.print") as fake_print:
            trader._refresh_batch_market_data = lambda: None
            trader._signal_candidates = lambda: [_candidate("BTCUSDT", 0.84, 0.24, 0.84, reason="LONG crossover | test")]
            trader._estimate_win_probability = lambda candidate: 0.70
            trader.run()
        printed = _json_lines(fake_print.mock_calls)
        no_signal = next(event for event in printed if event["type"] == "NO_SIGNAL")
        self.assertEqual(no_signal["execution_rejections"]["execute_crossover_expectancy"], 1)

    def test_daily_loss_limit_pauses_new_entries_for_the_day(self) -> None:
        cfg = _trader().config
        cfg["live_loop"]["daily_loss_limit_r"] = 1.5
        trader = _trader(cfg)
        loss_day = "2026-04-10"
        closed_at_ms = int(datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
        trader._record_trade(ClosedTrade(symbol="BTCUSDT", timeframe="5m", side="LONG", entry=100.0, take_profit=101.0, stop_loss=99.0, exit_price=98.4, result="LOSS", opened_at_ms=closed_at_ms - 300000, closed_at_ms=closed_at_ms, pnl_r=-1.6, pnl_usd=-0.32, reason="DIRECT_SL"))
        with patch("src.live_trader.loop.time.sleep", lambda *_: None), patch("builtins.print") as fake_print:
            trader._current_utc_day = lambda: loss_day
            trader._refresh_batch_market_data = lambda: None
            trader._signal_candidates = lambda: [_candidate("BTCUSDT", 0.95, 0.5, 0.95)]
            trader.run()
        printed = _json_lines(fake_print.mock_calls)
        self.assertTrue(any(event["type"] == "DAILY_LOSS_LIMIT_PAUSE" for event in printed))

    def test_daily_loss_limit_clears_on_new_utc_day(self) -> None:
        cfg = _trader().config
        cfg["live_loop"]["daily_loss_limit_r"] = 1.5
        trader = _trader(cfg)
        trader._daily_loss_pause_day = "2026-04-10"
        with patch("src.live_trader.loop.time.sleep", lambda *_: None), patch("builtins.print") as fake_print:
            trader._current_utc_day = lambda: "2026-04-11"
            trader._refresh_batch_market_data = lambda: None
            trader._signal_candidates = lambda: []
            trader.run()
        printed = _json_lines(fake_print.mock_calls)
        self.assertTrue(any(event["type"] == "DAILY_LOSS_LIMIT_CLEARED" for event in printed))
