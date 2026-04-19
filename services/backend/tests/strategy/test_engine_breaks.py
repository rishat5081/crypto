import unittest
from unittest.mock import patch

from src.models import Candle
from src.strategies import MarketRegime, MarketStructure, StrategyEngine

from .support import _default_params, _make_candles, _neutral_market


class StrategyEngineBreakTests(unittest.TestCase):
    def test_breakdown_short_requires_bear_macro_trend(self) -> None:
        engine = StrategyEngine(_default_params(short_rsi_min=20, short_rsi_max=50, breakdown_max_rsi=45, breakdown_min_body_ratio=0.6, breakdown_close_position_max=0.3))
        candles = _make_candles([89.5 - i * 0.08 for i in range(40)])
        last = candles[-1]
        candles[-1] = Candle(open_time_ms=last.open_time_ms, open=87.56, high=87.60, low=86.82, close=87.08, volume=last.volume * 1.4, close_time_ms=last.close_time_ms)
        prior_structure = MarketStructure(support=87.20, resistance=88.10, support_touches=3, resistance_touches=3, hvn_support=None, hvn_resistance=None, recent_swing_low=87.07, recent_swing_high=87.62)
        notes = []
        with patch.object(engine, "_build_market_structure", return_value=prior_structure):
            result = engine._evaluate_breakdown_short(candles=candles, market=_neutral_market(), regime=MarketRegime(regime="TRENDING", adx=45.0, bb_width_val=0.02, trend_direction="BEAR", confidence=0.9), entry=87.08, ema_fast_v=87.50, ema_slow_v=88.12, rsi_v=29.9, atr_v=0.33, trend_bias="NEUTRAL", st_direction="DOWN", note=notes.append)
        self.assertIsNone(result)
        self.assertIn("breakdown_requires_bear_trend", notes)

    def test_bearish_continuation_allows_break_retest_resume_sequence(self) -> None:
        engine = StrategyEngine(_default_params(short_rsi_min=20, short_rsi_max=50, continuation_max_rsi=48, continuation_min_body_ratio=0.35, continuation_close_position_max=0.45, continuation_min_break_atr=0.15, continuation_retest_tolerance_atr=0.4, continuation_resume_break_atr=0.05))
        candles = _make_candles([101.0 - (i * 0.08) for i in range(40)])
        break_candle = candles[-3]
        bounce_candle = candles[-2]
        last = candles[-1]
        candles[-3] = Candle(open_time_ms=break_candle.open_time_ms, open=99.10, high=99.15, low=97.72, close=97.82, volume=break_candle.volume * 1.2, close_time_ms=break_candle.close_time_ms)
        candles[-2] = Candle(open_time_ms=bounce_candle.open_time_ms, open=97.86, high=98.56, low=97.80, close=98.28, volume=bounce_candle.volume, close_time_ms=bounce_candle.close_time_ms)
        candles[-1] = Candle(open_time_ms=last.open_time_ms, open=98.24, high=98.34, low=97.48, close=97.74, volume=last.volume * 1.1, close_time_ms=last.close_time_ms)
        result = engine._evaluate_bearish_continuation(candles=candles, market=_neutral_market(), regime=MarketRegime(regime="TRENDING", adx=34.0, bb_width_val=0.02, trend_direction="BEAR", confidence=0.9), entry=97.74, ema_fast_v=98.62, ema_slow_v=99.20, rsi_v=39.0, atr_v=0.42, trend_bias="BEAR", st_direction="DOWN", note=lambda _reason: None)
        self.assertEqual(result[0:2], ("SHORT", "CONTINUATION"))
        self.assertGreater(result[2]["continuation_ref_high"], 98.3)

    def test_breakdown_short_blocks_weak_bearish_candle(self) -> None:
        engine = StrategyEngine(_default_params(short_rsi_min=20, short_rsi_max=50, breakdown_max_rsi=45))
        candles = _make_candles([89.5 - i * 0.08 for i in range(40)])
        last = candles[-1]
        candles[-1] = Candle(open_time_ms=last.open_time_ms, open=87.30, high=87.60, low=87.05, close=87.22, volume=last.volume, close_time_ms=last.close_time_ms)
        notes = []
        with patch.object(engine, "_build_market_structure", return_value=MarketStructure(support=87.20, resistance=88.10, support_touches=3, resistance_touches=3, hvn_support=None, hvn_resistance=None, recent_swing_low=87.07, recent_swing_high=87.62)):
            result = engine._evaluate_breakdown_short(candles=candles, market=_neutral_market(), regime=MarketRegime(regime="TRENDING", adx=45.0, bb_width_val=0.02, trend_direction="BEAR", confidence=0.9), entry=87.22, ema_fast_v=87.50, ema_slow_v=88.12, rsi_v=33.0, atr_v=0.33, trend_bias="BEAR", st_direction="DOWN", note=notes.append)
        self.assertIsNone(result)
        self.assertIn("breakdown_candle_not_strong", notes)

    def test_breakdown_short_blocks_low_volume_bear_setup(self) -> None:
        engine = StrategyEngine(_default_params(short_rsi_min=20, short_rsi_max=50, breakdown_max_rsi=45, breakdown_neutral_max_rsi=40, breakdown_volume_ratio_min=0.7, breakdown_neutral_volume_ratio_min=1.1, breakdown_min_break_atr=0.25))
        candles = _make_candles([89.5 - i * 0.08 for i in range(40)])
        last = candles[-1]
        candles[-1] = Candle(open_time_ms=last.open_time_ms, open=9.715, high=9.72, low=9.64, close=9.666, volume=60.0, close_time_ms=last.close_time_ms)
        notes = []
        with patch.object(engine, "_build_market_structure", return_value=MarketStructure(support=9.677, resistance=9.75, support_touches=3, resistance_touches=3, hvn_support=None, hvn_resistance=None, recent_swing_low=9.615, recent_swing_high=9.73)):
            result = engine._evaluate_breakdown_short(candles=candles, market=_neutral_market(), regime=MarketRegime(regime="TRENDING", adx=29.0, bb_width_val=0.02, trend_direction="BEAR", confidence=0.9), entry=9.666, ema_fast_v=9.68, ema_slow_v=9.71, rsi_v=39.5, atr_v=0.043, trend_bias="BEAR", st_direction="DOWN", note=notes.append)
        self.assertIsNone(result)
        self.assertIn("breakdown_volume_too_low", notes)

    def test_breakdown_short_requires_clear_break_below_immediate_prior_low(self) -> None:
        engine = StrategyEngine(_default_params(short_rsi_min=20, short_rsi_max=50, breakdown_max_rsi=45, breakdown_min_body_ratio=0.55, breakdown_close_position_max=0.35, breakdown_min_break_atr=0.1, breakdown_prev_low_break_atr=0.2))
        candles = _make_candles([9.7 - i * 0.01 for i in range(40)])
        prev = candles[-2]
        last = candles[-1]
        candles[-2] = Candle(open_time_ms=prev.open_time_ms, open=9.315, high=9.315, low=9.274, close=9.289, volume=228130.0, close_time_ms=prev.close_time_ms)
        candles[-1] = Candle(open_time_ms=last.open_time_ms, open=9.289, high=9.295, low=9.262, close=9.270, volume=130100.0, close_time_ms=last.close_time_ms)
        notes = []
        with patch.object(engine, "_build_market_structure", return_value=MarketStructure(support=9.26, resistance=9.31, support_touches=3, resistance_touches=3, hvn_support=None, hvn_resistance=None, recent_swing_low=9.262, recent_swing_high=9.315)):
            result = engine._evaluate_breakdown_short(candles=candles, market=_neutral_market(), regime=MarketRegime(regime="TRENDING", adx=32.0, bb_width_val=0.02, trend_direction="BEAR", confidence=0.9), entry=9.270, ema_fast_v=9.318, ema_slow_v=9.366, rsi_v=27.7, atr_v=0.0306, trend_bias="BEAR", st_direction="DOWN", note=notes.append)
        self.assertIsNone(result)
        self.assertIn("breakdown_prior_low_not_cleared", notes)
