from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class StrategyParameters:
    ema_fast: int
    ema_slow: int
    rsi_period: int
    atr_period: int
    atr_multiplier: float
    risk_reward: float
    min_atr_pct: float
    max_atr_pct: float
    funding_abs_limit: float
    min_confidence: float
    long_rsi_min: float
    long_rsi_max: float
    short_rsi_min: float
    short_rsi_max: float
    crossover_lookback: int = 5
    crossover_min_trend_strength: float = 0.0
    crossover_long_rsi_min: float = 0.0
    crossover_short_rsi_max: float = 100.0
    crossover_max_drift_atr: float = 0.5
    pullback_min_trend_strength: float = 0.003
    pullback_confirmation_slack_pct: float = 0.0
    pullback_risk_reward: float = 0.0
    pullback_stop_lookback: int = 6
    pullback_stop_buffer_atr: float = 0.8
    pullback_short_rejection_wick_ratio_min: float = 0.25
    breakdown_min_trend_strength: float = 0.0015
    breakdown_max_rsi: float = 45.0
    breakdown_min_body_ratio: float = 0.55
    breakdown_close_position_max: float = 0.35
    breakdown_lookback: int = 6
    breakdown_min_break_atr: float = 0.0
    breakdown_prev_low_break_atr: float = 0.2
    breakdown_risk_reward: float = 2.2
    breakdown_stop_buffer_atr: float = 0.35
    breakdown_volume_ratio_min: float = 0.7
    breakdown_neutral_volume_ratio_min: float = 1.0
    breakdown_neutral_max_rsi: float = 40.0
    continuation_min_trend_strength: float = 0.001
    continuation_max_rsi: float = 48.0
    continuation_min_body_ratio: float = 0.35
    continuation_close_position_max: float = 0.45
    continuation_lookback: int = 6
    continuation_min_break_atr: float = 0.15
    continuation_retest_tolerance_atr: float = 0.4
    continuation_resume_break_atr: float = 0.05
    continuation_risk_reward: float = 1.8
    continuation_stop_buffer_atr: float = 0.3
    structure_min_trend_strength: float = 0.001
    structure_confirmation_slack_pct: float = 0.0
    structure_risk_reward: float = 1.8
    structure_stop_lookback: int = 6
    structure_stop_buffer_atr: float = 0.8
    structure_short_rejection_wick_ratio_min: float = 0.25
    structure_min_body_ratio: float = 0.35
    structure_close_position_max: float = 0.35
    structure_break_lookback: int = 6
    structure_break_min_atr: float = 0.15
    structure_retest_tolerance_atr: float = 0.4
    structure_stop_max_atr: float = 4.0
    rejection_wick_to_body_ratio: float = 1.2
    rejection_close_position_threshold: float = 0.45
    rejection_extreme_tolerance_atr: float = 0.3
    volume_ratio_min: float = 0.5
    ema_trend: int = 0
    adx_period: int = 14
    adx_trending_threshold: float = 25.0
    adx_ranging_threshold: float = 20.0
    bb_period: int = 20
    bb_std: float = 2.0
    bb_width_volatile_threshold: float = 0.06
    vol_ratio_volatile_threshold: float = 1.5
    supertrend_period: int = 10
    supertrend_multiplier: float = 3.0
    bb_reversion_rsi_oversold: float = 30.0
    bb_reversion_rsi_overbought: float = 70.0
    bb_reversion_volume_spike: float = 1.5
    bb_reversion_stop_atr_mult: float = 0.5
    sr_zone_lookback: int = 120
    sr_swing_lookback: int = 4
    sr_merge_pct: float = 0.003
    sr_min_touches: int = 3
    sr_entry_tolerance_atr: float = 0.9
    sr_stop_buffer_atr: float = 0.35
    sr_target_buffer_atr: float = 0.2
    sr_min_room_atr: float = 1.2
    ma_break_lookback: int = 4
    ema_trend_slope_bars: int = 5
    ema_trend_slope_min: float = 0.0005


@dataclass(frozen=True)
class MarketRegime:
    regime: str
    adx: float
    bb_width_val: float
    trend_direction: str
    confidence: float


@dataclass(frozen=True)
class MarketStructure:
    support: Optional[float]
    resistance: Optional[float]
    support_touches: int
    resistance_touches: int
    hvn_support: Optional[float]
    hvn_resistance: Optional[float]
    recent_swing_low: Optional[float] = None
    recent_swing_high: Optional[float] = None


def build_strategy_parameters(payload: Dict) -> StrategyParameters:
    return StrategyParameters(
        ema_fast=int(payload["ema_fast"]),
        ema_slow=int(payload["ema_slow"]),
        rsi_period=int(payload["rsi_period"]),
        atr_period=int(payload["atr_period"]),
        atr_multiplier=float(payload["atr_multiplier"]),
        risk_reward=float(payload["risk_reward"]),
        min_atr_pct=float(payload["min_atr_pct"]),
        max_atr_pct=float(payload["max_atr_pct"]),
        funding_abs_limit=float(payload["funding_abs_limit"]),
        min_confidence=float(payload["min_confidence"]),
        long_rsi_min=float(payload["long_rsi_min"]),
        long_rsi_max=float(payload["long_rsi_max"]),
        short_rsi_min=float(payload["short_rsi_min"]),
        short_rsi_max=float(payload["short_rsi_max"]),
        crossover_lookback=int(payload.get("crossover_lookback", 5)),
        crossover_min_trend_strength=float(payload.get("crossover_min_trend_strength", 0.0)),
        crossover_long_rsi_min=float(payload.get("crossover_long_rsi_min", payload["long_rsi_min"])),
        crossover_short_rsi_max=float(payload.get("crossover_short_rsi_max", payload["short_rsi_max"])),
        crossover_max_drift_atr=float(payload.get("crossover_max_drift_atr", 0.5)),
        pullback_min_trend_strength=float(payload.get("pullback_min_trend_strength", 0.003)),
        pullback_confirmation_slack_pct=float(payload.get("pullback_confirmation_slack_pct", 0.0)),
        pullback_risk_reward=float(payload.get("pullback_risk_reward", payload.get("risk_reward", 1.5))),
        pullback_stop_lookback=int(payload.get("pullback_stop_lookback", 6)),
        pullback_stop_buffer_atr=float(payload.get("pullback_stop_buffer_atr", 0.8)),
        pullback_short_rejection_wick_ratio_min=float(payload.get("pullback_short_rejection_wick_ratio_min", 0.25)),
        breakdown_min_trend_strength=float(payload.get("breakdown_min_trend_strength", 0.0015)),
        breakdown_max_rsi=float(payload.get("breakdown_max_rsi", payload.get("short_rsi_max", 45.0))),
        breakdown_min_body_ratio=float(payload.get("breakdown_min_body_ratio", 0.55)),
        breakdown_close_position_max=float(payload.get("breakdown_close_position_max", 0.35)),
        breakdown_lookback=int(payload.get("breakdown_lookback", 6)),
        breakdown_min_break_atr=float(payload.get("breakdown_min_break_atr", 0.0)),
        breakdown_prev_low_break_atr=float(payload.get("breakdown_prev_low_break_atr", 0.2)),
        breakdown_risk_reward=float(payload.get("breakdown_risk_reward", max(payload.get("risk_reward", 1.5), 2.2))),
        breakdown_stop_buffer_atr=float(payload.get("breakdown_stop_buffer_atr", 0.35)),
        breakdown_volume_ratio_min=float(payload.get("breakdown_volume_ratio_min", 0.7)),
        breakdown_neutral_volume_ratio_min=float(payload.get("breakdown_neutral_volume_ratio_min", 1.0)),
        breakdown_neutral_max_rsi=float(payload.get("breakdown_neutral_max_rsi", 40.0)),
        continuation_min_trend_strength=float(payload.get("continuation_min_trend_strength", 0.001)),
        continuation_max_rsi=float(payload.get("continuation_max_rsi", payload.get("short_rsi_max", 48.0))),
        continuation_min_body_ratio=float(payload.get("continuation_min_body_ratio", 0.35)),
        continuation_close_position_max=float(payload.get("continuation_close_position_max", 0.45)),
        continuation_lookback=int(payload.get("continuation_lookback", 6)),
        continuation_min_break_atr=float(payload.get("continuation_min_break_atr", 0.15)),
        continuation_retest_tolerance_atr=float(payload.get("continuation_retest_tolerance_atr", 0.4)),
        continuation_resume_break_atr=float(payload.get("continuation_resume_break_atr", 0.05)),
        continuation_risk_reward=float(payload.get("continuation_risk_reward", max(payload.get("risk_reward", 1.5), 1.8))),
        continuation_stop_buffer_atr=float(payload.get("continuation_stop_buffer_atr", 0.3)),
        structure_min_trend_strength=float(payload.get("structure_min_trend_strength", payload.get("pullback_min_trend_strength", payload.get("continuation_min_trend_strength", 0.001)))),
        structure_confirmation_slack_pct=float(payload.get("structure_confirmation_slack_pct", payload.get("pullback_confirmation_slack_pct", 0.0))),
        structure_risk_reward=float(payload.get("structure_risk_reward", payload.get("pullback_risk_reward", payload.get("risk_reward", 1.8)))),
        structure_stop_lookback=int(payload.get("structure_stop_lookback", payload.get("pullback_stop_lookback", 6))),
        structure_stop_buffer_atr=float(payload.get("structure_stop_buffer_atr", payload.get("pullback_stop_buffer_atr", 0.8))),
        structure_short_rejection_wick_ratio_min=float(payload.get("structure_short_rejection_wick_ratio_min", payload.get("pullback_short_rejection_wick_ratio_min", 0.25))),
        structure_min_body_ratio=float(payload.get("structure_min_body_ratio", payload.get("continuation_min_body_ratio", payload.get("breakdown_min_body_ratio", 0.35)))),
        structure_close_position_max=float(payload.get("structure_close_position_max", payload.get("breakdown_close_position_max", payload.get("continuation_close_position_max", 0.35)))),
        structure_break_lookback=int(payload.get("structure_break_lookback", max(int(payload.get("breakdown_lookback", 6)), int(payload.get("continuation_lookback", 6))))),
        structure_break_min_atr=float(payload.get("structure_break_min_atr", payload.get("continuation_min_break_atr", payload.get("breakdown_min_break_atr", 0.15)))),
        structure_retest_tolerance_atr=float(payload.get("structure_retest_tolerance_atr", payload.get("continuation_retest_tolerance_atr", 0.4))),
        structure_stop_max_atr=float(payload.get("structure_stop_max_atr", 4.0)),
        rejection_wick_to_body_ratio=float(payload.get("rejection_wick_to_body_ratio", 1.2)),
        rejection_close_position_threshold=float(payload.get("rejection_close_position_threshold", 0.45)),
        rejection_extreme_tolerance_atr=float(payload.get("rejection_extreme_tolerance_atr", 0.3)),
        volume_ratio_min=float(payload.get("volume_ratio_min", 0.5)),
        ema_trend=int(payload.get("ema_trend", 0)),
        adx_period=int(payload.get("adx_period", 14)),
        adx_trending_threshold=float(payload.get("adx_trending_threshold", 25.0)),
        adx_ranging_threshold=float(payload.get("adx_ranging_threshold", 20.0)),
        bb_period=int(payload.get("bb_period", 20)),
        bb_std=float(payload.get("bb_std", 2.0)),
        bb_width_volatile_threshold=float(payload.get("bb_width_volatile_threshold", 0.06)),
        vol_ratio_volatile_threshold=float(payload.get("vol_ratio_volatile_threshold", 1.5)),
        supertrend_period=int(payload.get("supertrend_period", 10)),
        supertrend_multiplier=float(payload.get("supertrend_multiplier", 3.0)),
        bb_reversion_rsi_oversold=float(payload.get("bb_reversion_rsi_oversold", 30.0)),
        bb_reversion_rsi_overbought=float(payload.get("bb_reversion_rsi_overbought", 70.0)),
        bb_reversion_volume_spike=float(payload.get("bb_reversion_volume_spike", 1.5)),
        bb_reversion_stop_atr_mult=float(payload.get("bb_reversion_stop_atr_mult", 0.5)),
        sr_zone_lookback=int(payload.get("sr_zone_lookback", 120)),
        sr_swing_lookback=int(payload.get("sr_swing_lookback", 4)),
        sr_merge_pct=float(payload.get("sr_merge_pct", 0.003)),
        sr_min_touches=int(payload.get("sr_min_touches", 3)),
        sr_entry_tolerance_atr=float(payload.get("sr_entry_tolerance_atr", 0.9)),
        sr_stop_buffer_atr=float(payload.get("sr_stop_buffer_atr", 0.35)),
        sr_target_buffer_atr=float(payload.get("sr_target_buffer_atr", 0.2)),
        sr_min_room_atr=float(payload.get("sr_min_room_atr", 1.2)),
        ma_break_lookback=int(payload.get("ma_break_lookback", 4)),
        ema_trend_slope_bars=int(payload.get("ema_trend_slope_bars", 5)),
        ema_trend_slope_min=float(payload.get("ema_trend_slope_min", 0.0005)),
    )

