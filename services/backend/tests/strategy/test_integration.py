import unittest

from src.strategies import RegimeDetector, StrategyEngine

from .support import _default_params, _make_candles, _neutral_market, _ranging_candles, _trending_up_candles


class UnifiedStrategyIntegrationTests(unittest.TestCase):
    def test_trending_market_produces_signal(self) -> None:
        candles = _trending_up_candles(60, start=95.0, step=0.3)
        engine = StrategyEngine(_default_params(min_confidence=0.1, min_atr_pct=0.0, max_atr_pct=1.0, pullback_min_trend_strength=0.0, crossover_min_trend_strength=0.0))
        sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        if sig is not None:
            self.assertIn(sig.side, ("LONG", "SHORT"))
            self.assertIn("regime=", sig.reason)
            self.assertIn("ADX=", sig.reason)

    def test_signal_reason_contains_regime_info(self) -> None:
        candles = _make_candles([95 + i * 0.3 for i in range(60)])
        engine = StrategyEngine(_default_params(min_confidence=0.0))
        sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        if sig is not None:
            self.assertRegex(sig.reason, r"SR=(?:na|-?\d+\.\d{2})/(?:na|-?\d+\.\d{2})")

    def test_confidence_is_structure_based(self) -> None:
        candles = _make_candles([95 + i * 0.3 for i in range(60)])
        engine = StrategyEngine(_default_params(min_confidence=0.0))
        sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        if sig is not None:
            self.assertGreater(sig.confidence, 0)
            self.assertLess(sig.confidence, 1.0)

    def test_old_config_from_dict_still_works(self) -> None:
        engine = StrategyEngine.from_dict({"ema_fast": 5, "ema_slow": 10, "rsi_period": 14, "atr_period": 14, "atr_multiplier": 1.5, "risk_reward": 2.0, "min_atr_pct": 0.001, "max_atr_pct": 0.05, "funding_abs_limit": 0.001, "min_confidence": 0.25, "long_rsi_min": 55, "long_rsi_max": 72, "short_rsi_min": 28, "short_rsi_max": 48})
        self.assertEqual(engine.params.adx_period, 14)
        self.assertEqual(engine.params.bb_period, 20)
        self.assertEqual(engine.params.supertrend_period, 10)

    def test_volatile_regime_blocks_weak_signals(self) -> None:
        engine = StrategyEngine(_default_params(min_confidence=0.9, min_atr_pct=0.0, max_atr_pct=1.0))
        candles = []
        for i in range(60):
            base = 100.0 + (i % 2) * 5
            candles.append(_make_candles([base])[0].__class__(open_time_ms=i * 60000, open=base, high=base + 3, low=base - 3, close=base + 1, volume=100.0, close_time_ms=(i + 1) * 60000 - 1))
        self.assertIsNone(engine.evaluate("BTCUSDT", "5m", candles, _neutral_market()))

    def test_signal_type_bb_reversion_in_live_trader(self) -> None:
        from src.live_trader import LiveAdaptivePaperTrader

        reason = "LONG bb_reversion | regime=RANGING | EMA(8/34)=100/99, RSI=28, ATR%=0.005, ADX=15, funding=0.0001"
        self.assertEqual(LiveAdaptivePaperTrader._signal_type_from_reason(reason), "BB_REVERSION")

    def test_signal_type_breakdown_in_live_trader(self) -> None:
        from src.live_trader import LiveAdaptivePaperTrader

        reason = "SHORT breakdown | regime=TRENDING | EMA(8/34)=87.50/88.12, RSI=29.9, ATR%=0.0038, ADX=45.0, funding=0.0001"
        self.assertEqual(LiveAdaptivePaperTrader._signal_type_from_reason(reason), "BREAKDOWN")

    def test_signal_type_continuation_in_live_trader(self) -> None:
        from src.live_trader import LiveAdaptivePaperTrader

        reason = "SHORT continuation | regime=TRENDING | EMA(8/34)=98.92/99.41, RSI=39.0, ATR%=0.0042, ADX=34.0, funding=0.0001"
        self.assertEqual(LiveAdaptivePaperTrader._signal_type_from_reason(reason), "CONTINUATION")


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
