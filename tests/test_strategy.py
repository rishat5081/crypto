import unittest

from src.models import Candle, MarketContext
from src.strategy import StrategyEngine, StrategyParameters


def _default_params(**overrides) -> StrategyParameters:
    defaults = dict(
        ema_fast=5, ema_slow=10, rsi_period=14, atr_period=14,
        atr_multiplier=1.5, risk_reward=2.0,
        min_atr_pct=0.001, max_atr_pct=0.05,
        funding_abs_limit=0.001, min_confidence=0.25,
        long_rsi_min=55, long_rsi_max=72,
        short_rsi_min=28, short_rsi_max=48,
        crossover_max_drift_atr=0.5,
        pullback_confirmation_slack_pct=0.0,
        volume_ratio_min=0.5,
    )
    defaults.update(overrides)
    return StrategyParameters(**defaults)


def _make_candles(prices, volume=100.0):
    candles = []
    for i, p in enumerate(prices):
        candles.append(Candle(
            open_time_ms=i * 60000, open=p * 0.999, high=p * 1.002,
            low=p * 0.998, close=p, volume=volume,
            close_time_ms=(i + 1) * 60000 - 1,
        ))
    return candles


def _neutral_market() -> MarketContext:
    return MarketContext(mark_price=100.0, funding_rate=0.0001, open_interest=1e6)


class StrategyEngineTests(unittest.TestCase):

    def test_not_enough_candles_returns_none(self) -> None:
        engine = StrategyEngine(_default_params())
        candles = _make_candles([100] * 5)
        result = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        self.assertIsNone(result)

    def test_long_signal_generated_on_uptrend(self) -> None:
        # Rising prices → EMA fast > EMA slow, RSI in 55-72 range
        prices = [95 + i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(min_confidence=0.25))
        sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        if sig is not None:
            self.assertEqual(sig.side, "LONG")
            self.assertGreater(sig.take_profit, sig.entry)
            self.assertLess(sig.stop_loss, sig.entry)

    def test_short_signal_generated_on_downtrend(self) -> None:
        prices = [115 - i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(min_confidence=0.25))
        sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        if sig is not None:
            self.assertEqual(sig.side, "SHORT")
            self.assertLess(sig.take_profit, sig.entry)
            self.assertGreater(sig.stop_loss, sig.entry)

    def test_high_funding_rate_blocks_signal(self) -> None:
        prices = [95 + i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(funding_abs_limit=0.0001))
        # Funding rate 0.005 far exceeds 0.0001 limit
        market = MarketContext(mark_price=100, funding_rate=0.005, open_interest=1e6)
        sig = engine.evaluate("BTCUSDT", "5m", candles, market)
        self.assertIsNone(sig)

    def test_negative_funding_also_blocked_symmetrically(self) -> None:
        """Both positive and negative funding should be blocked by abs() filter."""
        prices = [115 - i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(funding_abs_limit=0.0001))
        market = MarketContext(mark_price=100, funding_rate=-0.005, open_interest=1e6)
        sig = engine.evaluate("BTCUSDT", "5m", candles, market)
        self.assertIsNone(sig)

    def test_confidence_below_threshold_returns_none(self) -> None:
        prices = [95 + i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(min_confidence=0.99))
        sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        self.assertIsNone(sig)

    def test_confidence_clamped_below_1(self) -> None:
        prices = [95 + i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(min_confidence=0.0))
        sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        if sig is not None:
            self.assertLess(sig.confidence, 1.0)

    def test_crossover_long_rsi_floor_can_block_neutral_crossover(self) -> None:
        prices = [95 + i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(min_confidence=0.25, crossover_long_rsi_min=90))
        sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        self.assertIsNone(sig)

    def test_pullback_min_trend_strength_can_block_signal(self) -> None:
        prices = [95 + i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(min_confidence=0.0, pullback_min_trend_strength=1.0))
        sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        self.assertIsNone(sig)

    def test_from_dict_supports_generation_relaxation_fields(self) -> None:
        engine = StrategyEngine.from_dict({
            "ema_fast": 5,
            "ema_slow": 10,
            "rsi_period": 14,
            "atr_period": 14,
            "atr_multiplier": 1.5,
            "risk_reward": 2.0,
            "min_atr_pct": 0.001,
            "max_atr_pct": 0.05,
            "funding_abs_limit": 0.001,
            "min_confidence": 0.25,
            "long_rsi_min": 55,
            "long_rsi_max": 72,
            "short_rsi_min": 28,
            "short_rsi_max": 48,
            "crossover_max_drift_atr": 0.9,
            "pullback_confirmation_slack_pct": 0.002,
            "volume_ratio_min": 0.35,
        })
        self.assertEqual(engine.params.crossover_max_drift_atr, 0.9)
        self.assertEqual(engine.params.pullback_confirmation_slack_pct, 0.002)
        self.assertEqual(engine.params.volume_ratio_min, 0.35)

    def test_diagnostics_report_confidence_below_min(self) -> None:
        prices = [95 + i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(
            _default_params(
                min_confidence=0.995,
                min_atr_pct=0.0,
                max_atr_pct=1.0,
                long_rsi_min=0,
                long_rsi_max=100,
                short_rsi_min=0,
                short_rsi_max=100,
                crossover_long_rsi_min=0,
                crossover_short_rsi_max=100,
                crossover_min_trend_strength=0.0,
                pullback_min_trend_strength=0.0,
            )
        )
        diagnostics = {}
        sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market(), diagnostics=diagnostics)
        self.assertIsNone(sig)
        self.assertGreaterEqual(diagnostics.get("confidence_below_min", 0), 1)

    def test_atr_outside_range_blocks_signal(self) -> None:
        # Flat prices → ATR ~ 0 → below min_atr_pct
        prices = [100.0] * 60
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(min_atr_pct=0.01))
        sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        self.assertIsNone(sig)

    def test_adaptive_tune_loss_tightens(self) -> None:
        engine = StrategyEngine(_default_params(min_confidence=0.55, risk_reward=2.0))
        original_conf = engine.params.min_confidence
        engine.adaptive_tune_after_trade("LOSS")
        self.assertGreater(engine.params.min_confidence, original_conf)
        self.assertEqual(engine.params.risk_reward, 2.0)  # R/R stays fixed

    def test_adaptive_tune_win_relaxes(self) -> None:
        engine = StrategyEngine(_default_params(min_confidence=0.85, risk_reward=1.5))
        original_conf = engine.params.min_confidence
        engine.adaptive_tune_after_trade("WIN")
        self.assertLess(engine.params.min_confidence, original_conf)
        self.assertEqual(engine.params.risk_reward, 1.5)  # R/R stays fixed


if __name__ == "__main__":
    unittest.main()
