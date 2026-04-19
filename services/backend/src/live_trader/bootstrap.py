from __future__ import annotations

import copy
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional

from src.binance import BinanceExecutor, BinanceFuturesRestClient
from src.ml import MLWalkForwardOptimizer
from src.models import ClosedTrade
from src.policy_engine import SmartPolicyEngine
from src.strategies import StrategyService


class TraderBootstrapMixin:
    def __init__(self, config: Dict):
        self.config = config
        ds = config.get("data_source", {})
        self.client = BinanceFuturesRestClient(
            allow_mock_fallback=bool(ds.get("allow_mock_fallback", False)),
            force_mock=bool(ds.get("force_mock", False)),
            mock_seed=int(ds.get("mock_seed", 42)),
        )

        self.strategy_payload = copy.deepcopy(config["strategy"])
        self.strategy_service = StrategyService.from_config(copy.deepcopy(config["strategy"]))
        self.base_strategy = self.strategy_service.engine

        acct = config["account"]
        self.starting_balance_usd = float(acct["starting_balance_usd"])
        self.risk_per_trade_pct = float(acct["risk_per_trade_pct"])
        self.paper_risk_usd = acct.get("paper_risk_usd")
        self.risk_usd = (
            float(self.paper_risk_usd)
            if self.paper_risk_usd is not None
            else self.starting_balance_usd * self.risk_per_trade_pct
        )
        self.risk_sizing_mode = "paper_risk_usd" if self.paper_risk_usd is not None else "balance_pct"

        execution_cfg = config.get("execution", {})
        self.cost_model = MLWalkForwardOptimizer(
            risk_usd=self.risk_usd,
            fee_bps_per_side=float(execution_cfg.get("fee_bps_per_side", 0.0)),
            slippage_bps_per_side=float(execution_cfg.get("slippage_bps_per_side", 0.0)),
        )

        live_cfg = config.get("live_loop", {})
        self.symbols = self._normalize_symbols(live_cfg.get("symbols", []))
        self.timeframes = live_cfg.get("timeframes", ["1m", "5m", "15m"])
        self.execute_timeframes = {
            str(v).strip()
            for v in live_cfg.get("execute_timeframes", self.timeframes)
            if str(v).strip()
        }
        if not self.execute_timeframes:
            self.execute_timeframes = {str(v).strip() for v in self.timeframes if str(v).strip()}
        self.lookback = int(live_cfg.get("lookback_candles", 260))
        self.poll_seconds = int(live_cfg.get("poll_seconds", 12))
        self.max_wait_minutes_per_trade = int(live_cfg.get("max_wait_minutes_per_trade", 120))
        self.min_rr_floor = float(live_cfg.get("min_rr_floor", 0.4))
        self.min_trend_strength = float(live_cfg.get("min_trend_strength", 0.0007))
        self.top_n = int(live_cfg.get("top_n", 3))
        self.max_parallel_candidates = int(live_cfg.get("max_parallel_candidates", 10))
        self.possible_trades_limit = int(live_cfg.get("possible_trades_limit", max(100, self.max_parallel_candidates)))
        self.possible_trades_limit = max(10, min(self.possible_trades_limit, 5000))
        self.min_candidate_confidence = float(live_cfg.get("min_candidate_confidence", 0.7))
        self.min_candidate_expectancy_r = float(live_cfg.get("min_candidate_expectancy_r", 0.0))
        self.execute_min_confidence = float(
            live_cfg.get(
                "execute_min_confidence",
                max(self.min_candidate_confidence, float(self.strategy_payload.get("min_confidence", 0.6))),
            )
        )
        self.execute_min_expectancy_r = float(live_cfg.get("execute_min_expectancy_r", max(0.08, self.min_candidate_expectancy_r)))
        self.execute_min_score = float(live_cfg.get("execute_min_score", 0.72))
        self.execute_min_win_probability = float(live_cfg.get("execute_min_win_probability", 0.72))
        self.require_dual_timeframe_confirm = bool(live_cfg.get("require_dual_timeframe_confirm", True))
        self.min_score_gap = float(live_cfg.get("min_score_gap", 0.02))
        self.relax_after_filter_blocks = int(live_cfg.get("relax_after_filter_blocks", 8))
        self.relax_conf_step = float(live_cfg.get("relax_conf_step", 0.005))
        self.relax_expectancy_step = float(live_cfg.get("relax_expectancy_step", 0.01))
        self.relax_score_step = float(live_cfg.get("relax_score_step", 0.005))
        self.relax_min_execute_confidence = float(live_cfg.get("relax_min_execute_confidence", 0.82))
        self.relax_min_execute_expectancy_r = float(live_cfg.get("relax_min_execute_expectancy_r", 0.1))
        self.relax_min_execute_score = float(live_cfg.get("relax_min_execute_score", 0.65))
        self.target_trades = int(live_cfg.get("target_trades", 30))
        self.target_win_rate = float(live_cfg.get("target_win_rate", 0.75))
        self.min_trades_for_success = int(live_cfg.get("min_trades_for_success", 20))
        self.max_cycles = int(live_cfg.get("max_cycles", 1200))
        self.max_open_trades = int(live_cfg.get("max_open_trades", 1))
        self.enable_sound = bool(config.get("scanner", {}).get("enable_sound", True))
        self.enable_break_even = bool(live_cfg.get("enable_break_even", True))
        self.break_even_trigger_r = float(live_cfg.get("break_even_trigger_r", 0.5))
        self.break_even_offset_r = float(live_cfg.get("break_even_offset_r", 0.02))
        self.structure_score_multiplier = float(
            live_cfg.get(
                "structure_score_multiplier",
                max(
                    float(live_cfg.get("pullback_score_multiplier", 1.03)),
                    float(live_cfg.get("breakdown_score_multiplier", 1.05)),
                    float(live_cfg.get("continuation_score_multiplier", 1.04)),
                ),
            )
        )
        self.crossover_score_multiplier = float(live_cfg.get("crossover_score_multiplier", 0.88))
        self.pullback_score_multiplier = float(live_cfg.get("pullback_score_multiplier", 1.03))
        self.breakdown_score_multiplier = float(live_cfg.get("breakdown_score_multiplier", 1.05))
        self.continuation_score_multiplier = float(live_cfg.get("continuation_score_multiplier", 1.04))
        self.bb_reversion_score_multiplier = float(live_cfg.get("bb_reversion_score_multiplier", 1.0))
        self.supertrend_score_multiplier = float(live_cfg.get("supertrend_score_multiplier", 1.08))
        self.max_same_direction_trades = int(live_cfg.get("max_same_direction_trades", 3))
        self.disabled_signal_types = {str(v).strip().upper() for v in live_cfg.get("disabled_signal_types", []) if str(v).strip()}
        self.allowed_execution_regimes = {
            str(v).strip().upper()
            for v in live_cfg.get("allowed_execution_regimes", [])
            if str(v).strip()
        }
        self.crossover_min_trend_strength = float(live_cfg.get("crossover_min_trend_strength", self.min_trend_strength))
        self.crossover_min_confidence = float(live_cfg.get("crossover_min_confidence", self.min_candidate_confidence))
        self.crossover_execute_min_confidence = float(
            live_cfg.get("crossover_execute_min_confidence", max(self.execute_min_confidence, self.crossover_min_confidence))
        )
        self.crossover_execute_min_expectancy_r = float(
            live_cfg.get("crossover_execute_min_expectancy_r", max(self.execute_min_expectancy_r, self.min_candidate_expectancy_r))
        )
        self.crossover_execute_min_score = float(
            live_cfg.get("crossover_execute_min_score", max(self.execute_min_score, self.crossover_score_multiplier))
        )
        self.crossover_execute_min_win_probability = float(
            live_cfg.get("crossover_execute_min_win_probability", self.execute_min_win_probability)
        )
        self.min_symbol_quality_for_entry = float(live_cfg.get("min_symbol_quality_for_entry", 0.55))
        self.min_symbol_history_for_entry = int(live_cfg.get("min_symbol_history_for_entry", 3))
        self.min_symbol_win_rate_for_entry = float(live_cfg.get("min_symbol_win_rate_for_entry", 0.40))
        self.min_symbol_expectancy_r_for_entry = float(live_cfg.get("min_symbol_expectancy_r_for_entry", -0.02))
        self.min_open_interest_notional_usd = float(live_cfg.get("min_open_interest_notional_usd", 0.0))
        self.enable_trailing_stop = bool(live_cfg.get("enable_trailing_stop", True))
        self.trail_trigger_r = float(live_cfg.get("trail_trigger_r", 0.2))
        self.trail_keep_pct = float(live_cfg.get("trail_keep_pct", 0.7))
        self.max_adverse_r_cut = float(live_cfg.get("max_adverse_r_cut", 0.9))
        self.max_wait_candles = int(live_cfg.get("max_wait_candles", 12))
        self.breakdown_wait_candle_multiplier = int(live_cfg.get("breakdown_wait_candle_multiplier", 2))
        self.breakdown_timeout_extension_candles = int(live_cfg.get("breakdown_timeout_extension_candles", 2))
        self.breakdown_timeout_min_best_r = float(live_cfg.get("breakdown_timeout_min_best_r", 0.5))
        self.breakdown_timeout_min_current_r = float(live_cfg.get("breakdown_timeout_min_current_r", 0.0))
        self.max_stagnation_bars = int(live_cfg.get("max_stagnation_bars", 6))
        self.min_progress_r_for_stagnation = float(live_cfg.get("min_progress_r_for_stagnation", 0.10))
        self.momentum_reversal_bars = int(live_cfg.get("momentum_reversal_bars", 3))
        self.momentum_reversal_r = float(live_cfg.get("momentum_reversal_r", -0.4))
        self.close_orphaned_positions_on_startup = bool(live_cfg.get("close_orphaned_positions_on_startup", False))
        self.reentry_cooldown_cycles = int(live_cfg.get("reentry_cooldown_cycles", 4))
        self.fast_exit_reentry_cooldown_cycles = int(
            live_cfg.get("fast_exit_reentry_cooldown_cycles", max(self.reentry_cooldown_cycles + 2, 6))
        )
        self.fast_exit_minutes_threshold = float(live_cfg.get("fast_exit_minutes_threshold", 8.0))
        guard_cfg = live_cfg.get("performance_guard", {})
        self.guard_enabled = bool(guard_cfg.get("enabled", True))
        self.guard_symbol_window = int(guard_cfg.get("rolling_window_trades", 12))
        self.guard_min_symbol_trades = int(guard_cfg.get("min_symbol_trades", 4))
        self.guard_min_symbol_win_rate = float(guard_cfg.get("min_symbol_win_rate", 0.45))
        self.guard_min_symbol_expectancy_r = float(guard_cfg.get("min_symbol_expectancy_r", -0.05))
        self.guard_cooldown_cycles = int(guard_cfg.get("cooldown_cycles", 6))
        self.guard_min_active_symbols = int(guard_cfg.get("min_active_symbols", 3))
        self.guard_global_window = int(guard_cfg.get("global_window_trades", 10))
        self.guard_global_min_win_rate = float(guard_cfg.get("global_min_win_rate", 0.5))
        self.guard_global_min_expectancy_r = float(guard_cfg.get("global_min_expectancy_r", 0.0))
        loss_guard_cfg = live_cfg.get("loss_guard", {})
        self.loss_guard_enabled = bool(loss_guard_cfg.get("enabled", True))
        self.max_global_consecutive_losses = int(loss_guard_cfg.get("max_global_consecutive_losses", 2))
        self.global_pause_cycles = int(loss_guard_cfg.get("global_pause_cycles", 4))
        self.max_symbol_consecutive_losses = int(loss_guard_cfg.get("max_symbol_consecutive_losses", 2))
        self.symbol_pause_cycles = int(loss_guard_cfg.get("symbol_pause_cycles", max(4, self.guard_cooldown_cycles)))
        self.daily_loss_limit_r = float(live_cfg.get("daily_loss_limit_r", 0.0))
        self.klines_window_size = int(live_cfg.get("klines_window_size", 20))
        self._klines_window_offset = 0
        self._premium_cache: Dict[str, "MarketContext"] = {}
        self._ticker_cache: Dict[str, float] = {}
        self.invalid_symbol_failures: Dict[str, int] = defaultdict(int)
        self.invalid_symbol_failure_threshold = int(live_cfg.get("invalid_symbol_failure_threshold", 2))

        cfg_path = config.get("_config_path")
        root_dir = Path(cfg_path).resolve().parent if cfg_path else Path.cwd()
        runtime_control_path = live_cfg.get("runtime_control_file", "/tmp/crypto-runtime/runtime_control.json")
        runtime_path = Path(runtime_control_path)
        if not runtime_path.is_absolute():
            runtime_path = (root_dir / runtime_path).resolve()
        self.runtime_control_file = runtime_path
        events_path = live_cfg.get("events_file", "")
        if events_path:
            candidate_events_path = Path(events_path)
            if not candidate_events_path.is_absolute():
                candidate_events_path = (root_dir / candidate_events_path).resolve()
        else:
            candidate_events_path = self.runtime_control_file.parent / "live_events.jsonl"
        self.events_file = candidate_events_path
        self._runtime_control_mtime_ns: Optional[int] = None

        base_conf = float(self.strategy_payload.get("min_confidence", 0.6))
        self.symbol_confidence: Dict[str, float] = {s: base_conf for s in self.symbols}
        self.recent_trades: list[ClosedTrade] = []
        self.symbol_recent_trades: Dict[str, list[ClosedTrade]] = defaultdict(list)
        policy_cfg = config.get("policy", {})
        self.policy_engine = SmartPolicyEngine(
            enabled=bool(policy_cfg.get("enable_policy_engine", True)),
            min_trades_for_setup_eval=int(policy_cfg.get("min_trades_for_setup_eval", 3)),
            setup_pause_cycles=int(policy_cfg.get("setup_pause_cycles", 20)),
            negative_expectancy_pause=bool(policy_cfg.get("negative_expectancy_pause", True)),
            min_setup_win_rate=float(policy_cfg.get("min_setup_win_rate", 0.0)),
        )
        self.symbol_cooldowns: Dict[str, int] = {}
        self.symbol_consecutive_losses: Dict[str, int] = defaultdict(int)
        self.global_consecutive_losses = 0
        self.global_pause_cycles_left = 0
        self.no_trade_filter_block_streak = 0
        self.filter_rejections: Dict[str, int] = defaultdict(int)
        self.open_trades = {}
        self._emitted_trade_result_keys: set[str] = set()
        self._daily_loss_pause_day: Optional[str] = None
        self.executor = BinanceExecutor.from_env(config)
        self._close_orphaned_positions()
