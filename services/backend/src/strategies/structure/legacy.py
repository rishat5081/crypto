from __future__ import annotations

from typing import List, Optional

from ...indicators import bollinger_bands, ema_series, macd_histogram_series, supertrend_series
from ...models import Candle, MarketContext
from .types import MarketRegime


class StrategyLegacySetupMixin:
    def _evaluate_crossover(
        self,
        candles: List[Candle],
        close_prices: List[float],
        market: MarketContext,
        regime: MarketRegime,
        entry: float,
        ema_fast_v: float,
        ema_slow_v: float,
        rsi_v: float,
        atr_v: float,
        allow_long: bool,
        allow_short: bool,
        note,
    ) -> Optional[tuple]:
        crossover_lookback = self.params.crossover_lookback
        fast_series_vals = ema_series(close_prices, self.params.ema_fast)
        slow_series_vals = ema_series(close_prices, self.params.ema_slow)
        look = min(crossover_lookback + 1, len(fast_series_vals), len(slow_series_vals))
        recent_diffs = []
        for k in range(look):
            fi = len(fast_series_vals) - look + k
            si = len(slow_series_vals) - look + k
            recent_diffs.append(fast_series_vals[fi] - slow_series_vals[si])
        bullish_cross = any(recent_diffs[j] <= 0 and recent_diffs[j + 1] > 0 for j in range(len(recent_diffs) - 1))
        bearish_cross = any(recent_diffs[j] >= 0 and recent_diffs[j + 1] < 0 for j in range(len(recent_diffs) - 1))
        trend_strength = abs(ema_fast_v - ema_slow_v) / entry if entry else 0.0
        if trend_strength < self.params.crossover_min_trend_strength:
            if bullish_cross or bearish_cross:
                note("crossover_trend_too_weak")
            return None
        if not bullish_cross and not bearish_cross:
            note("no_recent_crossover")
            return None

        def _crossover_age_and_drift(diffs, bullish: bool) -> tuple:
            for j in range(len(diffs) - 1, 0, -1):
                if bullish and diffs[j - 1] <= 0 and diffs[j] > 0:
                    return (len(diffs) - 1 - j, abs(entry - close_prices[-(len(diffs) - j)]) / atr_v if atr_v else 0.0)
                if not bullish and diffs[j - 1] >= 0 and diffs[j] < 0:
                    return (len(diffs) - 1 - j, abs(entry - close_prices[-(len(diffs) - j)]) / atr_v if atr_v else 0.0)
            return (len(diffs), 0.0)

        if bullish_cross:
            age, drift = _crossover_age_and_drift(recent_diffs, True)
            if age >= 3 and drift > self.params.crossover_max_drift_atr:
                note("crossover_drift_too_large")
                bullish_cross = False
        if bearish_cross:
            age, drift = _crossover_age_and_drift(recent_diffs, False)
            if age >= 3 and drift > self.params.crossover_max_drift_atr:
                note("crossover_drift_too_large")
                bearish_cross = False

        if allow_long and ema_fast_v > ema_slow_v and bullish_cross and self.params.long_rsi_min <= rsi_v <= self.params.long_rsi_max and rsi_v >= self.params.crossover_long_rsi_min and entry >= ema_fast_v and abs(market.funding_rate) <= self.params.funding_abs_limit:
            return ("LONG", "CROSSOVER", None)
        if allow_short and ema_fast_v < ema_slow_v and bearish_cross and self.params.short_rsi_min <= rsi_v <= self.params.short_rsi_max and rsi_v <= self.params.crossover_short_rsi_max and entry <= ema_fast_v and abs(market.funding_rate) <= self.params.funding_abs_limit:
            return ("SHORT", "CROSSOVER", None)
        if bullish_cross or bearish_cross:
            if abs(market.funding_rate) > self.params.funding_abs_limit:
                note("crossover_funding_blocked")
            elif (bullish_cross and not allow_long) or (bearish_cross and not allow_short):
                note("crossover_macro_trend_blocked")
            else:
                note("crossover_rsi_out_of_range")
        return None

    def _evaluate_trend_pullback(
        self,
        candles: List[Candle],
        close_prices: List[float],
        market: MarketContext,
        regime: MarketRegime,
        entry: float,
        ema_fast_v: float,
        ema_slow_v: float,
        rsi_v: float,
        atr_v: float,
        allow_long: bool,
        allow_short: bool,
        st_direction: str,
        note,
    ) -> Optional[tuple]:
        if abs(market.funding_rate) > self.params.funding_abs_limit:
            note("pullback_funding_blocked")
            return None
        trend_strength = abs(ema_fast_v - ema_slow_v) / entry if entry else 0.0
        if trend_strength <= self.params.pullback_min_trend_strength or len(candles) < 3:
            note("pullback_trend_too_weak")
            return None
        prev_close = candles[-2].close
        prev2_close = candles[-3].close
        if allow_long and ema_fast_v > ema_slow_v:
            touch_dist = abs(candles[-1].low - ema_fast_v) / atr_v if atr_v else 999
            bounced = entry > ema_fast_v and prev_close <= ema_fast_v * 1.002
            confirmed = prev_close >= prev2_close * (1 - self.params.pullback_confirmation_slack_pct) and entry >= prev_close * (1 - self.params.pullback_confirmation_slack_pct)
            if (touch_dist < 1.0 or bounced) and confirmed and self.params.long_rsi_min <= rsi_v <= self.params.long_rsi_max:
                return ("LONG", "PULLBACK", {"st_aligned": st_direction == "UP"})
            note("pullback_confirmation_failed" if self.params.long_rsi_min <= rsi_v <= self.params.long_rsi_max else "pullback_rsi_out_of_range")
            return None
        if allow_short and ema_fast_v < ema_slow_v:
            last = candles[-1]
            touch_dist = abs(candles[-1].high - ema_fast_v) / atr_v if atr_v else 999
            rejected = entry < ema_fast_v and prev_close >= ema_fast_v * 0.998
            prev_was_pullback = prev_close >= prev2_close * (1 - self.params.pullback_confirmation_slack_pct)
            candle_range = last.high - last.low
            body = abs(last.close - last.open)
            upper_wick = last.high - max(last.open, last.close)
            wick_threshold = max(body * self.params.pullback_short_rejection_wick_ratio_min, candle_range * 0.08)
            confirmed = prev_was_pullback and entry < prev_close and entry < candles[-1].open and candle_range > 0 and upper_wick >= wick_threshold
            if (touch_dist < 1.0 or rejected) and confirmed and self.params.short_rsi_min <= rsi_v <= self.params.short_rsi_max:
                return ("SHORT", "PULLBACK", {"st_aligned": st_direction == "DOWN"})
            note("pullback_confirmation_failed" if self.params.short_rsi_min <= rsi_v <= self.params.short_rsi_max else "pullback_rsi_out_of_range")
            return None
        note("pullback_macro_trend_blocked")
        return None

    def _evaluate_breakdown_short(self, candles: List[Candle], market: MarketContext, regime: MarketRegime, entry: float, ema_fast_v: float, ema_slow_v: float, rsi_v: float, atr_v: float, trend_bias: str, st_direction: str, note) -> Optional[tuple]:
        if abs(market.funding_rate) > self.params.funding_abs_limit:
            note("breakdown_funding_blocked")
            return None
        if len(candles) < max(4, self.params.breakdown_lookback + 1):
            note("breakdown_not_enough_candles")
            return None
        if trend_bias != "BEAR":
            note("breakdown_requires_bear_trend")
            return None
        if ema_fast_v >= ema_slow_v:
            note("breakdown_not_bearish_trend")
            return None
        trend_strength = abs(ema_fast_v - ema_slow_v) / entry if entry else 0.0
        if trend_strength < self.params.breakdown_min_trend_strength:
            note("breakdown_trend_too_weak")
            return None
        last = candles[-1]
        candle_range = last.high - last.low
        if candle_range <= 0:
            note("breakdown_invalid_candle")
            return None
        body = abs(last.close - last.open)
        body_ratio = body / candle_range
        close_position = (last.close - last.low) / candle_range
        if last.close >= last.open or body_ratio < self.params.breakdown_min_body_ratio or close_position > self.params.breakdown_close_position_max:
            note("breakdown_candle_not_strong")
            return None
        if not (self.params.short_rsi_min <= rsi_v <= self.params.breakdown_max_rsi):
            note("breakdown_rsi_out_of_range")
            return None
        if st_direction != "DOWN":
            note("breakdown_supertrend_not_down")
            return None
        if len(candles) >= 20:
            avg_volume = sum(c.volume for c in candles[-20:]) / 20
            relative_volume = (last.volume / avg_volume) if avg_volume > 0 else 1.0
            if relative_volume < self.params.breakdown_volume_ratio_min:
                note("breakdown_volume_too_low")
                return None
        prev_low = candles[-2].low if len(candles) >= 2 else None
        if prev_low is not None and entry > (prev_low - (atr_v * self.params.breakdown_prev_low_break_atr)):
            note("breakdown_prior_low_not_cleared")
            return None
        prior_support = self._support_reference(self._build_market_structure(candles[:-1], candles[-2].close)) if len(candles) >= 3 else None
        recent_low = self._recent_breakdown_low(candles)
        broke_support = prior_support is not None and entry <= (prior_support - (atr_v * self.params.breakdown_min_break_atr))
        broke_recent_low = recent_low is not None and last.low < recent_low and entry <= (recent_low - (atr_v * self.params.breakdown_min_break_atr))
        if not (broke_support or broke_recent_low):
            note("breakdown_support_not_broken")
            return None
        return ("SHORT", "BREAKDOWN", {"st_aligned": True, "prior_support": prior_support, "prior_low": recent_low, "breakdown_candle_high": last.high})

    def _evaluate_bearish_continuation(self, candles: List[Candle], market: MarketContext, regime: MarketRegime, entry: float, ema_fast_v: float, ema_slow_v: float, rsi_v: float, atr_v: float, trend_bias: str, st_direction: str, note) -> Optional[tuple]:
        if abs(market.funding_rate) > self.params.funding_abs_limit:
            note("continuation_funding_blocked")
            return None
        if len(candles) < max(5, self.params.continuation_lookback + 3):
            note("continuation_not_enough_candles")
            return None
        if trend_bias != "BEAR":
            note("continuation_requires_bear_trend")
            return None
        if ema_fast_v >= ema_slow_v:
            note("continuation_not_bearish_trend")
            return None
        trend_strength = abs(ema_fast_v - ema_slow_v) / entry if entry else 0.0
        if trend_strength < self.params.continuation_min_trend_strength:
            note("continuation_trend_too_weak")
            return None
        if not (self.params.short_rsi_min <= rsi_v <= self.params.continuation_max_rsi):
            note("continuation_rsi_out_of_range")
            return None
        if st_direction != "DOWN":
            note("continuation_supertrend_not_down")
            return None
        break_candle = candles[-3]
        bounce_candle = candles[-2]
        last = candles[-1]
        candle_range = last.high - last.low
        if candle_range <= 0:
            note("continuation_invalid_candle")
            return None
        body_ratio = abs(last.close - last.open) / candle_range
        close_position = (last.close - last.low) / candle_range
        if last.close >= last.open or body_ratio < self.params.continuation_min_body_ratio or close_position > self.params.continuation_close_position_max:
            note("continuation_candle_not_strong")
            return None
        prior_window = candles[-(self.params.continuation_lookback + 3) : -3]
        if not prior_window:
            note("continuation_not_enough_history")
            return None
        prior_low = min(c.low for c in prior_window)
        prior_support = self._support_reference(self._build_market_structure(candles[:-3], break_candle.close))
        break_reference = prior_support if prior_support is not None else prior_low
        if break_candle.close > (break_reference - (atr_v * self.params.continuation_min_break_atr)):
            note("continuation_support_not_broken")
            return None
        retest_level = prior_support if prior_support is not None else ema_fast_v
        retest_threshold = atr_v * self.params.continuation_retest_tolerance_atr
        if bounce_candle.high < (retest_level - retest_threshold):
            note("continuation_retest_missing")
            return None
        resume_threshold = atr_v * self.params.continuation_resume_break_atr
        resumed_down = last.close <= (bounce_candle.low - resume_threshold) and last.close < bounce_candle.close and last.high <= (bounce_candle.high + retest_threshold) and last.close <= ema_fast_v
        if not resumed_down:
            note("continuation_resume_not_confirmed")
            return None
        return ("SHORT", "CONTINUATION", {"st_aligned": True, "prior_support": prior_support, "continuation_ref_high": max(bounce_candle.high, last.high)})

    def _evaluate_supertrend_trend(self, candles: List[Candle], close_prices: List[float], market: MarketContext, regime: MarketRegime, entry: float, rsi_v: float, atr_v: float, st_direction: str, note) -> Optional[tuple]:
        if abs(market.funding_rate) > self.params.funding_abs_limit:
            note("st_trend_funding_blocked")
            return None
        if len(candles) <= self.params.supertrend_period + 2:
            return None
        try:
            st_series = supertrend_series(candles, self.params.supertrend_period, self.params.supertrend_multiplier)
        except (ValueError, IndexError):
            return None
        if len(st_series) < 3:
            return None
        curr_dir = st_series[-1][1]
        flipped = any(st_series[i][1] != st_series[i + 1][1] for i in range(max(0, len(st_series) - 4), len(st_series) - 1))
        if not flipped:
            note("st_trend_no_flip")
            return None
        try:
            hist = macd_histogram_series(close_prices)
            if len(hist) >= 2 and ((curr_dir == "UP" and hist[-1] < 0) or (curr_dir == "DOWN" and hist[-1] > 0)):
                note("st_trend_macd_divergent")
                return None
        except (ValueError, IndexError):
            pass
        if len(candles) >= 20:
            avg_vol = sum(c.volume for c in candles[-20:]) / 20
            if avg_vol > 0 and candles[-1].volume < avg_vol * 0.8:
                note("st_trend_low_volume")
                return None
        st_val = st_series[-1][0]
        if curr_dir == "UP":
            if entry <= st_val or rsi_v > 75:
                note("st_trend_price_below_st" if entry <= st_val else "st_trend_rsi_exhausted")
                return None
            return ("LONG", "SUPERTREND", {"st_value": st_val})
        if entry >= st_val or rsi_v < 25:
            note("st_trend_price_above_st" if entry >= st_val else "st_trend_rsi_exhausted")
            return None
        return ("SHORT", "SUPERTREND", {"st_value": st_val})

    def _evaluate_bb_mean_reversion(self, candles: List[Candle], close_prices: List[float], market: MarketContext, regime: MarketRegime, entry: float, rsi_v: float, atr_v: float, note) -> Optional[tuple]:
        if abs(market.funding_rate) > self.params.funding_abs_limit:
            note("bb_reversion_funding_blocked")
            return None
        if len(close_prices) < self.params.bb_period:
            note("bb_reversion_insufficient_data")
            return None
        bb_upper, bb_mid, bb_lower = bollinger_bands(close_prices, self.params.bb_period, self.params.bb_std)
        has_volume_spike = False
        if len(candles) >= 20:
            avg_vol = sum(c.volume for c in candles[-20:]) / 20
            if avg_vol > 0:
                has_volume_spike = candles[-1].volume >= avg_vol * self.params.bb_reversion_volume_spike
        bb_vals = (bb_upper, bb_mid, bb_lower)
        if entry <= bb_lower and rsi_v <= self.params.bb_reversion_rsi_oversold:
            return ("LONG", "BB_REVERSION", {"bb": bb_vals, "volume_spike": has_volume_spike})
        if entry >= bb_upper and rsi_v >= self.params.bb_reversion_rsi_overbought:
            return ("SHORT", "BB_REVERSION", {"bb": bb_vals, "volume_spike": has_volume_spike})
        note("bb_reversion_no_volume_spike" if (entry <= bb_lower or entry >= bb_upper) and not has_volume_spike else ("bb_reversion_rsi_not_extreme" if (entry <= bb_lower or entry >= bb_upper) else "bb_reversion_price_not_at_band"))
        return None
