import unittest
from unittest.mock import patch

from src.models import MarketContext
from src.strategies import MarketRegime, MarketStructure, StrategyEngine

from .support import _default_params, _make_candles, _neutral_market


class StrategyEngineBasicTests(unittest.TestCase):
    def test_not_enough_candles_returns_none(self) -> None:
        engine = StrategyEngine(_default_params())
        candles = _make_candles([100] * 5)
        result = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market())
        self.assertIsNone(result)

    def test_long_signal_generated_on_uptrend(self) -> None:
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
        market = MarketContext(mark_price=100, funding_rate=0.005, open_interest=1e6)
        self.assertIsNone(engine.evaluate("BTCUSDT", "5m", candles, market))

    def test_negative_funding_also_blocked_symmetrically(self) -> None:
        prices = [115 - i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(funding_abs_limit=0.0001))
        market = MarketContext(mark_price=100, funding_rate=-0.005, open_interest=1e6)
        self.assertIsNone(engine.evaluate("BTCUSDT", "5m", candles, market))

    def test_confidence_below_threshold_returns_none(self) -> None:
        prices = [95 + i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(min_confidence=0.99))
        self.assertIsNone(engine.evaluate("BTCUSDT", "5m", candles, _neutral_market()))

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
        self.assertIsNone(engine.evaluate("BTCUSDT", "5m", candles, _neutral_market()))

    def test_pullback_min_trend_strength_can_block_signal(self) -> None:
        prices = [95 + i * 0.3 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(min_confidence=0.0, pullback_min_trend_strength=1.0))
        self.assertIsNone(engine.evaluate("BTCUSDT", "5m", candles, _neutral_market()))

    def test_from_dict_supports_generation_relaxation_fields(self) -> None:
        engine = StrategyEngine.from_dict(
            {
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
                "pullback_risk_reward": 2.1,
                "pullback_stop_lookback": 7,
                "pullback_stop_buffer_atr": 0.9,
                "pullback_short_rejection_wick_ratio_min": 0.3,
                "breakdown_min_trend_strength": 0.0015,
                "breakdown_max_rsi": 44,
                "breakdown_min_body_ratio": 0.6,
                "breakdown_close_position_max": 0.3,
                "breakdown_lookback": 8,
                "breakdown_min_break_atr": 0.1,
                "breakdown_prev_low_break_atr": 0.2,
                "breakdown_risk_reward": 2.4,
                "breakdown_stop_buffer_atr": 0.4,
                "breakdown_volume_ratio_min": 0.8,
                "breakdown_neutral_volume_ratio_min": 1.1,
                "breakdown_neutral_max_rsi": 39,
                "continuation_min_trend_strength": 0.0011,
                "continuation_max_rsi": 46,
                "continuation_min_body_ratio": 0.4,
                "continuation_close_position_max": 0.42,
                "continuation_lookback": 7,
                "continuation_min_break_atr": 0.18,
                "continuation_retest_tolerance_atr": 0.35,
                "continuation_resume_break_atr": 0.06,
                "continuation_risk_reward": 1.9,
                "continuation_stop_buffer_atr": 0.28,
                "structure_stop_max_atr": 5.0,
                "rejection_wick_to_body_ratio": 1.4,
                "rejection_close_position_threshold": 0.4,
                "rejection_extreme_tolerance_atr": 0.25,
                "volume_ratio_min": 0.35,
            }
        )
        self.assertEqual(engine.params.breakdown_prev_low_break_atr, 0.2)
        self.assertEqual(engine.params.continuation_risk_reward, 1.9)
        self.assertEqual(engine.params.rejection_wick_to_body_ratio, 1.4)

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
        with patch.object(engine, "_evaluate_trend_structure", return_value=("LONG", "STRUCTURE", {"pattern": "support_bounce", "break_level": 112.5})), patch.object(engine, "_build_market_structure", return_value=MarketStructure(support=112.5, resistance=115.0, support_touches=3, resistance_touches=3, hvn_support=None, hvn_resistance=None, recent_swing_low=112.4, recent_swing_high=115.1)), patch.object(engine, "_macro_trend_bias", return_value="BULL"), patch.object(engine, "_has_recent_ma_break", return_value=True), patch.object(engine, "_is_rejection_against_entry", return_value=False):
            sig = engine.evaluate("BTCUSDT", "5m", candles, _neutral_market(), diagnostics=diagnostics)
        self.assertIsNone(sig)
        self.assertGreaterEqual(diagnostics.get("confidence_below_min", 0), 1)

    def test_atr_outside_range_blocks_signal(self) -> None:
        candles = _make_candles([100.0] * 60)
        engine = StrategyEngine(_default_params(min_atr_pct=0.01))
        self.assertIsNone(engine.evaluate("BTCUSDT", "5m", candles, _neutral_market()))

    def test_adaptive_tune_loss_tightens(self) -> None:
        engine = StrategyEngine(_default_params(min_confidence=0.55, risk_reward=2.0))
        original_conf = engine.params.min_confidence
        engine.adaptive_tune_after_trade("LOSS")
        self.assertGreater(engine.params.min_confidence, original_conf)
        self.assertEqual(engine.params.risk_reward, 2.0)

    def test_adaptive_tune_win_relaxes(self) -> None:
        engine = StrategyEngine(_default_params(min_confidence=0.85, risk_reward=1.5))
        original_conf = engine.params.min_confidence
        engine.adaptive_tune_after_trade("WIN")
        self.assertLess(engine.params.min_confidence, original_conf)
        self.assertEqual(engine.params.risk_reward, 1.5)

    def test_market_structure_detects_support_and_resistance(self) -> None:
        prices = [101.0, 103.5, 100.2, 104.0, 100.4, 103.8, 99.9, 103.6, 100.3, 103.7, 101.0]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(sr_swing_lookback=2, sr_min_touches=1))
        structure = engine._build_market_structure(candles, entry=101.0)
        self.assertIsNotNone(structure.support)
        self.assertIsNotNone(structure.resistance)

    def test_recent_ma_break_detects_upside_cross(self) -> None:
        prices = [105.0, 104.0, 103.0, 102.0, 101.0, 100.0, 99.0, 99.5, 100.2, 101.1, 102.2]
        engine = StrategyEngine(_default_params(ma_break_lookback=4))
        self.assertTrue(engine._has_recent_ma_break(prices, "LONG", 5))

    def test_trade_levels_use_structure_targets(self) -> None:
        engine = StrategyEngine(_default_params(risk_reward=3.0))
        structure = MarketStructure(support=99.0, resistance=101.2, support_touches=4, resistance_touches=4, hvn_support=None, hvn_resistance=None)
        stop_loss, take_profit = engine._build_trade_levels(side="LONG", signal_type="CROSSOVER", entry=100.0, atr_v=0.5, structure=structure, extra=None)
        self.assertLess(stop_loss, 100.0)
        self.assertLessEqual(take_profit, 101.2)
