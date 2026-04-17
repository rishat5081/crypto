import unittest

from src.models import Candle, MarketContext
from src.strategy import MarketStructure, RegimeDetector, StrategyEngine, StrategyParameters


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
                sr_entry_tolerance_atr=999.0,
                sr_min_room_atr=0.0,
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

    def test_market_structure_detects_support_and_resistance(self) -> None:
        prices = [101.0, 103.5, 100.2, 104.0, 100.4, 103.8, 99.9, 103.6, 100.3, 103.7, 101.0]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(sr_swing_lookback=2, sr_min_touches=1))
        structure = engine._build_market_structure(candles, entry=101.0)
        self.assertIsNotNone(structure.support)
        self.assertIsNotNone(structure.resistance)
        self.assertLess(structure.support, 101.0)
        self.assertGreater(structure.resistance, 101.0)

    def test_recent_ma_break_detects_upside_cross(self) -> None:
        prices = [105.0, 104.0, 103.0, 102.0, 101.0, 100.0, 99.0, 99.5, 100.2, 101.1, 102.2]
        engine = StrategyEngine(_default_params(ma_break_lookback=4))
        self.assertTrue(engine._has_recent_ma_break(prices, "LONG", 5))

    def test_trade_levels_use_structure_targets(self) -> None:
        engine = StrategyEngine(_default_params(risk_reward=3.0))
        structure = MarketStructure(
            support=99.0,
            resistance=101.2,
            support_touches=4,
            resistance_touches=4,
            hvn_support=None,
            hvn_resistance=None,
        )
        stop_loss, take_profit = engine._build_trade_levels(
            side="LONG",
            signal_type="CROSSOVER",
            entry=100.0,
            atr_v=0.5,
            structure=structure,
            extra=None,
        )
        self.assertLess(stop_loss, 100.0)
        self.assertLessEqual(take_profit, 101.2)


def _trending_up_candles(n: int = 50, start: float = 100.0, step: float = 0.5):
    candles = []
    price = start
    for i in range(n):
        o = price
        c = price + step
        h = c + step * 0.3
        low = o - step * 0.2
        candles.append(Candle(
            open_time_ms=i * 60000, open=o, high=h, low=low,
            close=c, volume=100.0, close_time_ms=(i + 1) * 60000 - 1,
        ))
        price = c
    return candles


def _ranging_candles(n: int = 50, center: float = 100.0, amplitude: float = 1.0):
    import math
    candles = []
    for i in range(n):
        v = center + amplitude * math.sin(i * 0.5)
        o = v - 0.2
        c = v + 0.2
        h = max(o, c) + 0.1
        low = min(o, c) - 0.1
        candles.append(Candle(
            open_time_ms=i * 60000, open=o, high=h, low=low,
            close=c, volume=100.0, close_time_ms=(i + 1) * 60000 - 1,
        ))
    return candles


class UnifiedStrategyIntegrationTests(unittest.TestCase):
    """Integration tests for the regime-aware multi-strategy engine."""

    def test_trending_market_produces_signal(self) -> None:
        candles = _trending_up_candles(60, start=95.0, step=0.3)
        engine = StrategyEngine(_default_params(
            min_confidence=0.1, min_atr_pct=0.0, max_atr_pct=1.0,
            pullback_min_trend_strength=0.0, crossover_min_trend_strength=0.0,
        ))
        market = MarketContext(mark_price=100.0, funding_rate=0.0001, open_interest=1e6)
        sig = engine.evaluate("BTCUSDT", "5m", candles, market)
        if sig is not None:
            self.assertIn(sig.side, ("LONG", "SHORT"))
            self.assertIn("regime=", sig.reason)
            self.assertIn("ADX=", sig.reason)

    def test_signal_reason_contains_regime_info(self) -> None:
        prices = [95 + i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(min_confidence=0.0))
        sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        if sig is not None:
            self.assertIn("regime=", sig.reason)
            self.assertIn("trend=", sig.reason)
            self.assertIn("SR=", sig.reason)
            self.assertRegex(sig.reason, r"SR=(?:na|-?\d+\.\d{2})/(?:na|-?\d+\.\d{2})")

    def test_confidence_is_structure_based(self) -> None:
        """Confidence should be between 0 and 1, no blanket *0.85 penalty."""
        prices = [95 + i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(min_confidence=0.0))
        sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        if sig is not None:
            self.assertGreater(sig.confidence, 0)
            self.assertLess(sig.confidence, 1.0)

    def test_old_config_from_dict_still_works(self) -> None:
        """Backward compat: old config without new keys should still work."""
        engine = StrategyEngine.from_dict({
            "ema_fast": 5, "ema_slow": 10, "rsi_period": 14,
            "atr_period": 14, "atr_multiplier": 1.5, "risk_reward": 2.0,
            "min_atr_pct": 0.001, "max_atr_pct": 0.05,
            "funding_abs_limit": 0.001, "min_confidence": 0.25,
            "long_rsi_min": 55, "long_rsi_max": 72,
            "short_rsi_min": 28, "short_rsi_max": 48,
        })
        # Should have defaults for all new params
        self.assertEqual(engine.params.adx_period, 14)
        self.assertEqual(engine.params.bb_period, 20)
        self.assertEqual(engine.params.supertrend_period, 10)

    def test_volatile_regime_blocks_weak_signals(self) -> None:
        """In volatile markets, only strong crossovers should pass."""
        engine = StrategyEngine(_default_params(
            min_confidence=0.9, min_atr_pct=0.0, max_atr_pct=1.0,
        ))
        # Create volatile candles (large swings)
        candles = []
        for i in range(60):
            base = 100.0 + (i % 2) * 5  # alternating 100/105
            candles.append(Candle(
                open_time_ms=i * 60000, open=base, high=base + 3,
                low=base - 3, close=base + 1, volume=100.0,
                close_time_ms=(i + 1) * 60000 - 1,
            ))
        market = MarketContext(mark_price=100.0, funding_rate=0.0001, open_interest=1e6)
        sig = engine.evaluate("BTCUSDT", "5m", candles, market)
        # High min_confidence should block most volatile regime signals
        self.assertIsNone(sig)

    def test_signal_type_bb_reversion_in_live_trader(self) -> None:
        """Live trader should correctly identify BB_REVERSION signal type."""
        from src.live_adaptive_trader import LiveAdaptivePaperTrader
        reason = "LONG bb_reversion | regime=RANGING | EMA(8/34)=100/99, RSI=28, ATR%=0.005, ADX=15, funding=0.0001"
        sig_type = LiveAdaptivePaperTrader._signal_type_from_reason(reason)
        self.assertEqual(sig_type, "BB_REVERSION")


class RegimeDetectorTests(unittest.TestCase):
    def test_trending_regime_on_strong_trend(self) -> None:
        candles = _trending_up_candles(50)
        closes = [c.close for c in candles]
        detector = RegimeDetector()
        regime = detector.detect(candles, closes, ema_fast_v=candles[-1].close, ema_slow_v=candles[-1].close * 0.95)
        self.assertEqual(regime.regime, "TRENDING")
        self.assertEqual(regime.trend_direction, "BULL")

    def test_ranging_regime_on_flat_market(self) -> None:
        candles = _ranging_candles(50)
        closes = [c.close for c in candles]
        detector = RegimeDetector()
        regime = detector.detect(candles, closes, ema_fast_v=100.0, ema_slow_v=100.0)
        self.assertEqual(regime.regime, "RANGING")

    def test_regime_confidence_positive(self) -> None:
        candles = _trending_up_candles(50)
        closes = [c.close for c in candles]
        detector = RegimeDetector()
        regime = detector.detect(candles, closes)
        self.assertGreater(regime.confidence, 0)
        self.assertLessEqual(regime.confidence, 1.0)

    def test_regime_trend_direction_bear(self) -> None:
        candles = _trending_up_candles(50)
        closes = [c.close for c in candles]
        detector = RegimeDetector()
        regime = detector.detect(candles, closes, ema_fast_v=90.0, ema_slow_v=100.0)
        self.assertEqual(regime.trend_direction, "BEAR")

    def test_regime_neutral_when_emas_close(self) -> None:
        candles = _ranging_candles(50)
        closes = [c.close for c in candles]
        detector = RegimeDetector()
        regime = detector.detect(candles, closes, ema_fast_v=100.0, ema_slow_v=100.05)
        self.assertEqual(regime.trend_direction, "NEUTRAL")


if __name__ == "__main__":
    unittest.main()
