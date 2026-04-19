import unittest
from unittest.mock import patch

from src.models import Candle, Signal

from .support import _candidate, _json_lines, _trader


class LiveAdaptivePaperTraderFlowTests(unittest.TestCase):
    def test_run_can_open_new_trade_while_previous_trade_remains_open(self) -> None:
        cfg = _trader().config
        cfg["live_loop"]["max_cycles"] = 2
        cfg["live_loop"]["max_open_trades"] = 2
        trader = _trader(cfg)
        cycle_candidates = [[_candidate("BTCUSDT", 0.80, 0.30, 0.90)], [_candidate("ETHUSDT", 0.82, 0.32, 0.91)]]
        with patch("src.live_trader.loop.time.sleep", lambda *_: None), patch("builtins.print") as fake_print:
            trader._refresh_batch_market_data = lambda: None
            trader._signal_candidates = lambda: cycle_candidates.pop(0) if cycle_candidates else []
            trader._update_open_trades = lambda cycle: None
            trader._estimate_win_probability = lambda candidate: 0.80
            result = trader.run()
        printed = _json_lines(fake_print.mock_calls)
        self.assertEqual(result["summary"]["open_trades_count"], 0)
        self.assertEqual(len([event for event in printed if event["type"] == "OPEN_TRADE"]), 2)

    def test_short_break_even_price_moves_below_entry(self) -> None:
        trader = _trader()
        self.assertEqual(trader._break_even_stop_price("SHORT", 100.0, 2.0, 0.05), 99.9)

    def test_effective_wait_minutes_preserves_candle_budget(self) -> None:
        cfg = _trader().config
        cfg["live_loop"]["max_wait_candles"] = 6
        cfg["live_loop"]["max_wait_minutes_per_trade"] = 45
        cfg["live_loop"]["breakdown_wait_candle_multiplier"] = 2
        cfg["live_loop"]["breakdown_timeout_extension_candles"] = 2
        trader = _trader(cfg)
        self.assertEqual(trader._effective_wait_minutes(15), 90)
        self.assertEqual(trader._effective_wait_minutes(15, "BREAKDOWN"), 210)

    def test_breakdown_timeout_extension_keeps_trade_open_when_continuation_is_intact(self) -> None:
        cfg = _trader().config
        cfg["live_loop"]["max_wait_candles"] = 6
        cfg["live_loop"]["breakdown_wait_candle_multiplier"] = 2
        cfg["live_loop"]["breakdown_timeout_extension_candles"] = 2
        trader = _trader(cfg)
        signal = Signal(symbol="BNBUSDT", timeframe="15m", side="SHORT", entry=100.0, take_profit=98.0, stop_loss=101.0, confidence=0.8, reason="SHORT breakdown | regime=TRENDING | trend=BEAR | test", signal_time_ms=1)
        managed = trader._make_managed_trade(signal, binance_opened=False)
        managed.bars_seen = trader._max_wait_candles_for_signal("BREAKDOWN")
        managed.best_r = 0.6
        managed.last_known_candles = [Candle(open_time_ms=idx * 60000, open=102.0 - (idx * 0.2), high=102.1 - (idx * 0.2), low=101.7 - (idx * 0.2), close=101.9 - (idx * 0.2), volume=10.0, close_time_ms=((idx + 1) * 60000) - 1) for idx in range(12)]
        self.assertTrue(trader._should_extend_breakdown_timeout(managed, managed.last_known_candles[-1], now_r=0.2))

    def test_signal_score_multiplier_penalizes_crossover_and_boosts_pullback(self) -> None:
        trader = _trader()
        self.assertLess(trader._signal_score_multiplier("CROSSOVER"), 1.0)
        self.assertGreater(trader._signal_score_multiplier("BREAKDOWN"), 1.0)

    def test_finalize_closed_trade_emits_trade_meta(self) -> None:
        trader = _trader()
        signal = Signal(symbol="BTCUSDT", timeframe="5m", side="LONG", entry=100.0, take_profit=101.0, stop_loss=99.0, confidence=0.8, reason="LONG pullback | regime=TRENDING | test", signal_time_ms=1)
        managed = trader._make_managed_trade(signal, binance_opened=False)
        managed.moved_to_break_even = True
        managed.last_known_candles = [Candle(open_time_ms=1, open=100.0, high=100.8, low=99.9, close=100.6, volume=10.0, close_time_ms=300001)]
        managed.engine.active_trade.stop_loss = 100.05
        closed = trader._make_exit(managed, managed.last_known_candles[-1], "ADVERSE_CUT")
        with patch("builtins.print") as fake_print:
            trader._finalize_closed_trade(managed, closed, 1, False, False)
        printed = _json_lines(fake_print.mock_calls)
        event = next(item for item in printed if item["type"] == "TRADE_RESULT")
        self.assertEqual(event["trade_meta"]["stop_state"], "BREAKEVEN")

    def test_signal_regime_from_reason_parses_regime(self) -> None:
        from src.live_trader import LiveAdaptivePaperTrader

        self.assertEqual(LiveAdaptivePaperTrader._signal_regime_from_reason("LONG pullback | regime=TRENDING | EMA(8/34)=1/2"), "TRENDING")

    def test_candidate_quality_block_reason_rejects_weak_crossover(self) -> None:
        trader = _trader()
        reason = trader._candidate_quality_block_reason(symbol="BTCUSDT", market=trader._premium_cache.get("BTCUSDT", None) or type("M", (), {"mark_price": 100.0, "funding_rate": 0.0, "open_interest": 100000.0})(), signal_type="CROSSOVER", trend_strength=trader.crossover_min_trend_strength / 2.0, confidence=0.9, symbol_quality=1.0)
        self.assertEqual(reason, "weak_crossover_trend")

    def test_finalize_closed_trade_skips_duplicate_result_emission(self) -> None:
        trader = _trader()
        signal = Signal(symbol="BTCUSDT", timeframe="5m", side="LONG", entry=100.0, take_profit=101.0, stop_loss=99.0, confidence=0.8, reason="LONG pullback | test", signal_time_ms=1)
        managed = trader._make_managed_trade(signal, binance_opened=False)
        closed = trader._make_exit(managed, Candle(open_time_ms=1, open=100.0, high=100.8, low=99.9, close=100.6, volume=10.0, close_time_ms=300001), "ADVERSE_CUT")
        with patch("builtins.print") as fake_print:
            trader._finalize_closed_trade(managed, closed, 1, False, False)
            trader._finalize_closed_trade(managed, closed, 1, False, False)
        printed = _json_lines(fake_print.mock_calls)
        self.assertEqual(sum(1 for event in printed if event["type"] == "TRADE_RESULT"), 1)

    def test_finalize_closed_trade_applies_reentry_cooldown(self) -> None:
        trader = _trader()
        signal = Signal(symbol="BTCUSDT", timeframe="5m", side="LONG", entry=100.0, take_profit=101.0, stop_loss=99.0, confidence=0.8, reason="LONG pullback | test", signal_time_ms=1)
        managed = trader._make_managed_trade(signal, binance_opened=False)
        closed = trader._make_exit(managed, Candle(open_time_ms=1, open=100.0, high=100.8, low=99.9, close=100.6, volume=10.0, close_time_ms=300001), "STAGNATION_EXIT")
        with patch("builtins.print", lambda *_: None):
            trader._finalize_closed_trade(managed, closed, 1, False, False)
        self.assertEqual(trader.symbol_cooldowns["BTCUSDT"], trader.fast_exit_reentry_cooldown_cycles)
