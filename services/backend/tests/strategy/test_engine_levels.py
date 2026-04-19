import unittest
from unittest.mock import patch

from src.models import Candle
from src.strategies import MarketRegime, MarketStructure, StrategyEngine

from .support import _default_params, _make_candles, _neutral_market


class StrategyEngineLevelsTests(unittest.TestCase):
    def test_pullback_trade_levels_use_recent_swing_stop_and_extended_rr(self) -> None:
        engine = StrategyEngine(_default_params(risk_reward=1.5, pullback_risk_reward=2.1, pullback_stop_buffer_atr=0.8, structure_stop_max_atr=4.0))
        structure = MarketStructure(support=99.2, resistance=110.0, support_touches=4, resistance_touches=4, hvn_support=None, hvn_resistance=None, recent_swing_low=97.5, recent_swing_high=102.0)
        stop_loss, take_profit = engine._build_trade_levels(side="LONG", signal_type="PULLBACK", entry=100.0, atr_v=2.0, structure=structure, extra=None)
        self.assertLess(stop_loss, structure.recent_swing_low)
        self.assertGreater(take_profit, 105.0)

    def test_breakdown_trade_levels_use_breakdown_high_and_do_not_cap_to_old_support(self) -> None:
        engine = StrategyEngine(_default_params(atr_multiplier=1.2, risk_reward=1.5, breakdown_risk_reward=2.2, breakdown_stop_buffer_atr=0.35))
        structure = MarketStructure(support=87.2, resistance=None, support_touches=4, resistance_touches=0, hvn_support=None, hvn_resistance=None, recent_swing_low=86.8, recent_swing_high=87.45)
        stop_loss, take_profit = engine._build_trade_levels(side="SHORT", signal_type="BREAKDOWN", entry=87.08, atr_v=0.3, structure=structure, extra={"breakdown_candle_high": 87.6})
        self.assertGreater(stop_loss, 87.3)
        self.assertLess(take_profit, structure.support)

    def test_structure_long_blocked_on_resistance_rejection(self) -> None:
        prices = [100 + i * 0.25 for i in range(60)]
        candles = _make_candles(prices)
        last = candles[-1]
        candles[-1] = Candle(open_time_ms=last.open_time_ms, open=114.0, high=116.6, low=113.8, close=114.2, volume=last.volume, close_time_ms=last.close_time_ms)
        engine = StrategyEngine(_default_params(min_confidence=0.0, min_atr_pct=0.0, max_atr_pct=1.0, sr_entry_tolerance_atr=999.0, sr_min_room_atr=0.0))
        structure = MarketStructure(support=112.5, resistance=116.5, support_touches=3, resistance_touches=3, hvn_support=None, hvn_resistance=None, recent_swing_low=112.4, recent_swing_high=116.6)
        regime = MarketRegime(regime="TRENDING", adx=30.0, bb_width_val=0.01, trend_direction="BULL", confidence=0.8)
        diagnostics = {}
        with patch.object(engine.regime_detector, "detect", return_value=regime), patch.object(engine, "_macro_trend_bias", return_value="BULL"), patch.object(engine, "_evaluate_trend_structure", return_value=("LONG", "STRUCTURE", {"pattern": "support_bounce", "break_level": 112.5})), patch.object(engine, "_build_market_structure", return_value=structure):
            sig = engine.evaluate("AAVEUSDT", "15m", candles, _neutral_market(), diagnostics=diagnostics)
        self.assertIsNone(sig)
        self.assertGreaterEqual(diagnostics.get("structure_rejection_against_entry", 0), 1)

    def test_structure_short_requires_bear_trend(self) -> None:
        prices = [120 - i * 0.2 for i in range(60)]
        candles = _make_candles(prices)
        engine = StrategyEngine(_default_params(min_confidence=0.0, min_atr_pct=0.0, max_atr_pct=1.0, sr_entry_tolerance_atr=999.0, sr_min_room_atr=0.0))
        structure = MarketStructure(support=107.8, resistance=109.5, support_touches=3, resistance_touches=3, hvn_support=None, hvn_resistance=None, recent_swing_low=107.7, recent_swing_high=109.6)
        regime = MarketRegime(regime="TRENDING", adx=28.0, bb_width_val=0.01, trend_direction="NEUTRAL", confidence=0.7)
        diagnostics = {}
        with patch.object(engine.regime_detector, "detect", return_value=regime), patch.object(engine, "_macro_trend_bias", return_value="NEUTRAL"), patch.object(engine, "_evaluate_trend_structure", return_value=("SHORT", "STRUCTURE", {"pattern": "resistance_reject", "break_level": 109.5})), patch.object(engine, "_build_market_structure", return_value=structure):
            sig = engine.evaluate("LTCUSDT", "15m", candles, _neutral_market(), diagnostics=diagnostics)
        self.assertIsNone(sig)
        self.assertGreaterEqual(diagnostics.get("structure_trend_alignment_failed", 0), 1)

    def test_pullback_short_allows_bounce_then_bearish_reclaim(self) -> None:
        engine = StrategyEngine(_default_params(pullback_confirmation_slack_pct=0.003))
        candles = _make_candles([100 - i * 0.1 for i in range(30)])
        prev2 = candles[-3]
        prev = candles[-2]
        last = candles[-1]
        candles[-3] = Candle(open_time_ms=prev2.open_time_ms, open=1.4320, high=1.4330, low=1.4298, close=1.4308, volume=prev2.volume, close_time_ms=prev2.close_time_ms)
        candles[-2] = Candle(open_time_ms=prev.open_time_ms, open=1.4308, high=1.4366, low=1.4300, close=1.4360, volume=prev.volume, close_time_ms=prev.close_time_ms)
        candles[-1] = Candle(open_time_ms=last.open_time_ms, open=1.4360, high=1.4370, low=1.4324, close=1.4325, volume=last.volume, close_time_ms=last.close_time_ms)
        result = engine._evaluate_trend_pullback(candles=candles, close_prices=[c.close for c in candles], market=_neutral_market(), regime=MarketRegime(regime="TRENDING", adx=28.0, bb_width_val=0.01, trend_direction="BEAR", confidence=0.8), entry=1.4325, ema_fast_v=1.4347, ema_slow_v=1.4510, rsi_v=34.6, atr_v=0.0067, allow_long=False, allow_short=True, st_direction="DOWN", note=lambda _reason: None)
        self.assertEqual(result, ("SHORT", "PULLBACK", {"st_aligned": True}))

    def test_pullback_short_blocks_flat_bearish_candle_without_rejection_wick(self) -> None:
        engine = StrategyEngine(_default_params(pullback_confirmation_slack_pct=0.003))
        candles = _make_candles([100 - i * 0.1 for i in range(30)])
        prev2 = candles[-3]
        prev = candles[-2]
        last = candles[-1]
        candles[-3] = Candle(open_time_ms=prev2.open_time_ms, open=0.2500, high=0.2502, low=0.2498, close=0.2499, volume=prev2.volume, close_time_ms=prev2.close_time_ms)
        candles[-2] = Candle(open_time_ms=prev.open_time_ms, open=0.2500, high=0.2501, low=0.2496, close=0.2500, volume=prev.volume, close_time_ms=prev.close_time_ms)
        candles[-1] = Candle(open_time_ms=last.open_time_ms, open=0.2499, high=0.2499, low=0.2487, close=0.2489, volume=last.volume, close_time_ms=last.close_time_ms)
        notes = []
        result = engine._evaluate_trend_pullback(candles=candles, close_prices=[c.close for c in candles], market=_neutral_market(), regime=MarketRegime(regime="TRENDING", adx=38.0, bb_width_val=0.01, trend_direction="BEAR", confidence=0.8), entry=0.2489, ema_fast_v=0.2492, ema_slow_v=0.2505, rsi_v=45.4, atr_v=0.00095, allow_long=False, allow_short=True, st_direction="DOWN", note=notes.append)
        self.assertIsNone(result)
        self.assertIn("pullback_confirmation_failed", notes)
