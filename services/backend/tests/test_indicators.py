import unittest

from src.indicators import (
    adx,
    adx_components,
    bb_width,
    bollinger_bands,
    ema,
    rsi,
    supertrend,
    supertrend_series,
)
from src.models import Candle


def _candle(open_: float, high: float, low: float, close: float, volume: float = 100.0, ts: int = 0) -> Candle:
    return Candle(open_time_ms=ts, open=open_, high=high, low=low, close=close, volume=volume, close_time_ms=ts + 60000)


def _trending_up_candles(n: int = 50, start: float = 100.0, step: float = 0.5) -> list:
    """Generate candles that trend steadily upward."""
    candles = []
    price = start
    for i in range(n):
        o = price
        c = price + step
        h = c + step * 0.3
        low = o - step * 0.2
        candles.append(_candle(o, h, low, c, ts=i * 60000))
        price = c
    return candles


def _ranging_candles(n: int = 50, center: float = 100.0, amplitude: float = 1.0) -> list:
    """Generate candles that oscillate around a center."""
    import math

    candles = []
    for i in range(n):
        v = center + amplitude * math.sin(i * 0.5)
        o = v - 0.2
        c = v + 0.2
        h = max(o, c) + 0.1
        low = min(o, c) - 0.1
        candles.append(_candle(o, h, low, c, ts=i * 60000))
    return candles


class IndicatorTests(unittest.TestCase):
    def test_ema_output_is_float(self) -> None:
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        out = ema(values, 5)
        self.assertIsInstance(out, float)

    def test_rsi_bounds(self) -> None:
        values = [100, 101, 99, 102, 100, 104, 102, 105, 104, 107, 105, 108, 109, 110, 108]
        out = rsi(values, 14)
        self.assertGreaterEqual(out, 0)
        self.assertLessEqual(out, 100)


class ADXTests(unittest.TestCase):
    def test_adx_trending_market_high(self) -> None:
        candles = _trending_up_candles(50)
        val = adx(candles, 14)
        self.assertGreater(val, 20, "ADX should be high in a strong trend")

    def test_adx_ranging_market_low(self) -> None:
        candles = _ranging_candles(50)
        val = adx(candles, 14)
        self.assertLess(val, 30, "ADX should be low in a ranging market")

    def test_adx_components_returns_three(self) -> None:
        candles = _trending_up_candles(50)
        result = adx_components(candles, 14)
        self.assertEqual(len(result), 3)
        adx_val, plus_di, minus_di = result
        self.assertGreaterEqual(adx_val, 0)
        self.assertGreaterEqual(plus_di, 0)
        self.assertGreaterEqual(minus_di, 0)

    def test_adx_components_uptrend_plus_di_higher(self) -> None:
        candles = _trending_up_candles(50)
        _, plus_di, minus_di = adx_components(candles, 14)
        self.assertGreater(plus_di, minus_di, "+DI should exceed -DI in uptrend")

    def test_adx_insufficient_candles_raises(self) -> None:
        candles = _trending_up_candles(10)
        with self.assertRaises(ValueError):
            adx(candles, 14)


class BollingerBandsTests(unittest.TestCase):
    def test_bands_shape(self) -> None:
        values = [float(i) for i in range(1, 30)]
        upper, middle, lower = bollinger_bands(values, 20, 2.0)
        self.assertGreater(upper, middle)
        self.assertGreater(middle, lower)

    def test_flat_prices_bands_collapse(self) -> None:
        values = [50.0] * 25
        upper, middle, lower = bollinger_bands(values, 20, 2.0)
        self.assertAlmostEqual(upper, middle, places=5)
        self.assertAlmostEqual(lower, middle, places=5)

    def test_bb_width_positive(self) -> None:
        values = [100.0 + i * 0.5 for i in range(25)]
        w = bb_width(values, 20, 2.0)
        self.assertGreater(w, 0)

    def test_bb_width_zero_on_flat(self) -> None:
        values = [50.0] * 25
        w = bb_width(values, 20, 2.0)
        self.assertAlmostEqual(w, 0.0, places=5)

    def test_insufficient_values_raises(self) -> None:
        with self.assertRaises(ValueError):
            bollinger_bands([1.0, 2.0], 20)


class SuperTrendTests(unittest.TestCase):
    def test_uptrend_direction(self) -> None:
        candles = _trending_up_candles(40)
        val, direction = supertrend(candles, 10, 3.0)
        self.assertEqual(direction, "UP")

    def test_downtrend_direction(self) -> None:
        # Reverse the trending candles to get a downtrend
        up = _trending_up_candles(40)
        down = []
        for i, c in enumerate(up):
            down.append(_candle(c.close, c.high, c.low, c.open, ts=i * 60000))
        down.reverse()
        # Re-assign timestamps
        candles = []
        for i, c in enumerate(down):
            candles.append(_candle(c.open, c.high, c.low, c.close, ts=i * 60000))
        _, direction = supertrend(candles, 10, 3.0)
        self.assertEqual(direction, "DOWN")

    def test_supertrend_value_below_price_in_uptrend(self) -> None:
        candles = _trending_up_candles(40)
        val, direction = supertrend(candles, 10, 3.0)
        if direction == "UP":
            self.assertLess(val, candles[-1].close, "SuperTrend should be below price in uptrend")

    def test_supertrend_series_length(self) -> None:
        candles = _trending_up_candles(40)
        series = supertrend_series(candles, 10, 3.0)
        self.assertEqual(len(series), len(candles) - 10)

    def test_supertrend_insufficient_candles_raises(self) -> None:
        candles = _trending_up_candles(5)
        with self.assertRaises(ValueError):
            supertrend(candles, 10, 3.0)


if __name__ == "__main__":
    unittest.main()
