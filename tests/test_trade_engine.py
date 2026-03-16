import unittest

from src.models import Candle, Signal
from src.trade_engine import TradeEngine


def _signal(side: str, entry: float, tp: float, sl: float) -> Signal:
    return Signal(
        symbol="BTCUSDT",
        timeframe="5m",
        side=side,
        entry=entry,
        take_profit=tp,
        stop_loss=sl,
        confidence=0.7,
        reason="test",
        signal_time_ms=1,
    )


def _candle(high: float, low: float, close: float) -> Candle:
    return Candle(
        open_time_ms=2, open=close, high=high, low=low,
        close=close, volume=1.0, close_time_ms=3,
    )


class TradeEngineTests(unittest.TestCase):

    # ── LONG trades ──────────────────────────────────────────

    def test_long_trade_hits_tp(self) -> None:
        engine = TradeEngine(risk_usd=1.0)
        engine.maybe_open_trade(_signal("LONG", 100.0, 102.0, 99.0))
        closed = engine.on_candle(_candle(high=102.5, low=99.8, close=101.8))
        self.assertIsNotNone(closed)
        self.assertEqual(closed.result, "WIN")
        self.assertAlmostEqual(closed.pnl_r, 2.0)

    def test_long_trade_hits_sl(self) -> None:
        engine = TradeEngine(risk_usd=1.0)
        engine.maybe_open_trade(_signal("LONG", 100.0, 102.0, 99.0))
        closed = engine.on_candle(_candle(high=100.5, low=98.5, close=99.2))
        self.assertIsNotNone(closed)
        self.assertEqual(closed.result, "LOSS")
        self.assertAlmostEqual(closed.pnl_r, -1.0)

    def test_long_both_hit_same_candle_favors_sl(self) -> None:
        """Conservative assumption: when both TP and SL hit in same candle, SL wins."""
        engine = TradeEngine(risk_usd=1.0)
        engine.maybe_open_trade(_signal("LONG", 100.0, 102.0, 99.0))
        closed = engine.on_candle(_candle(high=103.0, low=98.0, close=100.0))
        self.assertIsNotNone(closed)
        self.assertEqual(closed.result, "LOSS")

    def test_long_no_hit_returns_none(self) -> None:
        engine = TradeEngine(risk_usd=1.0)
        engine.maybe_open_trade(_signal("LONG", 100.0, 102.0, 99.0))
        closed = engine.on_candle(_candle(high=101.0, low=99.5, close=100.5))
        self.assertIsNone(closed)
        self.assertIsNotNone(engine.active_trade)

    # ── SHORT trades ─────────────────────────────────────────

    def test_short_trade_hits_tp(self) -> None:
        engine = TradeEngine(risk_usd=1.0)
        engine.maybe_open_trade(_signal("SHORT", 100.0, 98.0, 101.0))
        closed = engine.on_candle(_candle(high=100.5, low=97.5, close=98.2))
        self.assertIsNotNone(closed)
        self.assertEqual(closed.result, "WIN")
        self.assertAlmostEqual(closed.pnl_r, 2.0)

    def test_short_trade_hits_sl(self) -> None:
        engine = TradeEngine(risk_usd=1.0)
        engine.maybe_open_trade(_signal("SHORT", 100.0, 98.0, 101.0))
        closed = engine.on_candle(_candle(high=101.5, low=99.5, close=100.8))
        self.assertIsNotNone(closed)
        self.assertEqual(closed.result, "LOSS")
        self.assertAlmostEqual(closed.pnl_r, -1.0)

    def test_short_both_hit_same_candle_favors_sl(self) -> None:
        """Conservative assumption: when both TP and SL hit in same candle, SL wins."""
        engine = TradeEngine(risk_usd=1.0)
        engine.maybe_open_trade(_signal("SHORT", 100.0, 98.0, 101.0))
        closed = engine.on_candle(_candle(high=102.0, low=97.0, close=100.0))
        self.assertIsNotNone(closed)
        self.assertEqual(closed.result, "LOSS")

    def test_short_no_hit_returns_none(self) -> None:
        engine = TradeEngine(risk_usd=1.0)
        engine.maybe_open_trade(_signal("SHORT", 100.0, 98.0, 101.0))
        closed = engine.on_candle(_candle(high=100.8, low=98.5, close=99.5))
        self.assertIsNone(closed)

    # ── PnL R-multiple calculations ──────────────────────────

    def test_long_tp_pnl_r_equals_risk_reward(self) -> None:
        engine = TradeEngine(risk_usd=10.0)
        engine.maybe_open_trade(_signal("LONG", 100.0, 103.0, 99.0))
        closed = engine.on_candle(_candle(high=103.5, low=100.0, close=103.0))
        self.assertAlmostEqual(closed.pnl_r, 3.0)
        self.assertAlmostEqual(closed.pnl_usd, 30.0)

    def test_short_tp_pnl_r_equals_risk_reward(self) -> None:
        engine = TradeEngine(risk_usd=10.0)
        engine.maybe_open_trade(_signal("SHORT", 100.0, 97.0, 101.0))
        closed = engine.on_candle(_candle(high=100.5, low=96.5, close=97.5))
        self.assertAlmostEqual(closed.pnl_r, 3.0)
        self.assertAlmostEqual(closed.pnl_usd, 30.0)

    # ── Engine state ─────────────────────────────────────────

    def test_cannot_open_two_trades(self) -> None:
        engine = TradeEngine(risk_usd=1.0)
        self.assertTrue(engine.maybe_open_trade(_signal("LONG", 100, 102, 99)))
        self.assertFalse(engine.maybe_open_trade(_signal("SHORT", 100, 98, 101)))

    def test_on_candle_with_no_trade_returns_none(self) -> None:
        engine = TradeEngine(risk_usd=1.0)
        self.assertIsNone(engine.on_candle(_candle(100, 99, 100)))

    def test_closed_trades_accumulate(self) -> None:
        engine = TradeEngine(risk_usd=1.0)
        engine.maybe_open_trade(_signal("LONG", 100, 102, 99))
        engine.on_candle(_candle(high=103, low=100, close=102))
        engine.maybe_open_trade(_signal("SHORT", 100, 98, 101))
        engine.on_candle(_candle(high=102, low=100, close=101))
        self.assertEqual(len(engine.closed_trades), 2)


if __name__ == "__main__":
    unittest.main()
