from __future__ import annotations

import copy
import json
import time
from collections import defaultdict
from typing import Dict, List, Optional

from src.indicators import ema
from src.models import ClosedTrade, MarketContext
from src.live_trader.models import CandidateSignal, ManagedTrade
from src.strategies import StrategyService


class TraderSignalMixin:
    def _signal_candidates(self) -> List[CandidateSignal]:
        candidates: List[CandidateSignal] = []
        klines_window = self._get_klines_window()
        rejection_summary: Dict[str, object] = {
            "strategy_returned_none": 0,
            "strategy_rejections": defaultdict(int),
            "rr_below_floor": 0,
            "trend_strength_below_min": 0,
            "quality_blocked": defaultdict(int),
        }
        for symbol in klines_window:
            if int(self.symbol_cooldowns.get(symbol, 0)) > 0:
                continue
            try:
                market = self._premium_cache.get(symbol)
                if market is None:
                    market = self.client.fetch_market_context(symbol)
                for timeframe in self.timeframes:
                    candles = self._closed_candles(self.client.fetch_klines(symbol=symbol, interval=timeframe, limit=self.lookback))
                    if len(candles) < max(60, int(self.strategy_payload["ema_slow"])):
                        continue
                    strategy_data = copy.deepcopy(self.strategy_payload)
                    strategy_data["min_confidence"] = self.symbol_confidence.get(symbol, strategy_data["min_confidence"])
                    strategy = StrategyService.from_config(strategy_data)
                    strategy_rejections = rejection_summary["strategy_rejections"]
                    signal = strategy.evaluate(symbol, timeframe, candles, market, diagnostics=strategy_rejections)
                    if signal is None:
                        rejection_summary["strategy_returned_none"] = int(rejection_summary["strategy_returned_none"]) + 1
                        continue
                    rr = abs(signal.take_profit - signal.entry) / max(abs(signal.entry - signal.stop_loss), 1e-9)
                    if rr < self.min_rr_floor:
                        rejection_summary["rr_below_floor"] = int(rejection_summary["rr_below_floor"]) + 1
                        continue
                    closes = [c.close for c in candles]
                    ema_fast_v = ema(closes, int(strategy_data["ema_fast"]))
                    ema_slow_v = ema(closes, int(strategy_data["ema_slow"]))
                    trend_strength = abs(ema_fast_v - ema_slow_v) / max(signal.entry, 1e-9)
                    if trend_strength < self.min_trend_strength:
                        rejection_summary["trend_strength_below_min"] = int(rejection_summary["trend_strength_below_min"]) + 1
                        continue
                    cost_r = self.cost_model.trade_cost_r(signal.entry, signal.stop_loss)
                    expectancy_r = (signal.confidence * rr) - ((1.0 - signal.confidence) * 1.0) - cost_r
                    symbol_quality = self._symbol_quality_factor(symbol)
                    signal_type = self._signal_type_from_reason(signal.reason)
                    quality_block = self._candidate_quality_block_reason(
                        symbol=symbol,
                        market=market,
                        signal_type=signal_type,
                        trend_strength=trend_strength,
                        confidence=signal.confidence,
                        symbol_quality=symbol_quality,
                    )
                    if quality_block is not None:
                        quality_counts = rejection_summary["quality_blocked"]
                        if isinstance(quality_counts, defaultdict):
                            quality_counts[quality_block] += 1
                        continue
                    base_score = (signal.confidence * 0.65) + (trend_strength * 100.0 * 0.25) + ((rr - cost_r) * 0.10)
                    score = base_score * symbol_quality * self._signal_score_multiplier(signal_type)
                    candidates.append(
                        CandidateSignal(
                            signal=signal,
                            trend_strength=trend_strength,
                            cost_r=cost_r,
                            rr=rr,
                            expectancy_r=expectancy_r,
                            symbol_quality=symbol_quality,
                            score=score,
                        )
                    )
                    time.sleep(0.05)
            except Exception as exc:
                print(json.dumps({"type": "MARKET_FETCH_ERROR", "time": self._now_iso(), "symbol": symbol, "error": str(exc)}))
        quality_blocked = rejection_summary["quality_blocked"]
        strategy_rejections = rejection_summary["strategy_rejections"]
        print(
            json.dumps(
                {
                    "type": "CANDIDATE_REJECTION_SUMMARY",
                    "time": self._now_iso(),
                    "window_symbols": klines_window,
                    "counts": {
                        "strategy_returned_none": int(rejection_summary["strategy_returned_none"]),
                        "strategy_rejections": dict(strategy_rejections) if isinstance(strategy_rejections, defaultdict) else {},
                        "rr_below_floor": int(rejection_summary["rr_below_floor"]),
                        "trend_strength_below_min": int(rejection_summary["trend_strength_below_min"]),
                        "quality_blocked": dict(quality_blocked) if isinstance(quality_blocked, defaultdict) else {},
                        "candidates_emitted": len(candidates),
                    },
                }
            )
        )
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    @staticmethod
    def _closed_candles(candles: List, now_ms: Optional[int] = None) -> List:
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        return [c for c in candles if int(getattr(c, "close_time_ms", 0) or 0) < now_ms]

    def _symbol_quality_factor(self, symbol: str) -> float:
        recent = self.symbol_recent_trades.get(symbol, [])
        stats = self._stats(recent[-self.guard_symbol_window :])
        if stats["trades"] < 3:
            return 1.0
        win_rate = stats["win_rate"]
        expectancy = max(-0.2, min(0.2, stats["expectancy_r"]))
        expectancy_component = (expectancy + 0.2) / 0.4
        quality = 0.55 + (win_rate * 0.35) + (expectancy_component * 0.10)
        return max(0.45, min(1.05, quality))

    @staticmethod
    def _signal_type_from_reason(reason: str) -> str:
        upper = str(reason or "").upper()
        if "STRUCTURE" in upper:
            return "STRUCTURE"
        if "CONTINUATION" in upper:
            return "CONTINUATION"
        if "BREAKDOWN" in upper:
            return "BREAKDOWN"
        if "BB_REVERSION" in upper:
            return "BB_REVERSION"
        if "SUPERTREND" in upper:
            return "SUPERTREND"
        if "PULLBACK" in upper:
            return "PULLBACK"
        if "MOMENTUM" in upper:
            return "MOMENTUM"
        if "CROSSOVER" in upper:
            return "CROSSOVER"
        return "UNKNOWN"

    @staticmethod
    def _signal_pattern_from_reason(reason: str) -> str:
        upper = str(reason or "").upper()
        marker = "PATTERN="
        if marker not in upper:
            return ""
        tail = upper.split(marker, 1)[1]
        token = tail.split("|", 1)[0].split(",", 1)[0].strip()
        return token.lower()

    @staticmethod
    def _signal_regime_from_reason(reason: str) -> str:
        upper = str(reason or "").upper()
        marker = "REGIME="
        if marker not in upper:
            return "UNKNOWN"
        tail = upper.split(marker, 1)[1]
        token = tail.split("|", 1)[0].split(",", 1)[0].strip()
        return token or "UNKNOWN"

    def _signal_score_multiplier(self, signal_type: str) -> float:
        normalized = str(signal_type or "").upper()
        if normalized == "STRUCTURE":
            return self.structure_score_multiplier
        if normalized == "PULLBACK":
            return self.pullback_score_multiplier
        if normalized == "CONTINUATION":
            return self.continuation_score_multiplier
        if normalized == "BREAKDOWN":
            return self.breakdown_score_multiplier
        if normalized == "CROSSOVER":
            return self.crossover_score_multiplier
        if normalized == "BB_REVERSION":
            return self.bb_reversion_score_multiplier
        if normalized == "SUPERTREND":
            return self.supertrend_score_multiplier
        return 1.0

    def _candidate_quality_block_reason(
        self,
        symbol: str,
        market: MarketContext,
        signal_type: str,
        trend_strength: float,
        confidence: float,
        symbol_quality: float,
    ) -> Optional[str]:
        normalized_signal = str(signal_type or "").upper()
        if normalized_signal in self.disabled_signal_types:
            return f"signal_type_disabled:{normalized_signal.lower()}"
        if normalized_signal == "CROSSOVER":
            if trend_strength < self.crossover_min_trend_strength:
                return "weak_crossover_trend"
            if confidence < self.crossover_min_confidence:
                return "weak_crossover_confidence"
        if symbol_quality < self.min_symbol_quality_for_entry:
            return "low_symbol_quality"
        symbol_trades = self.symbol_recent_trades.get(symbol, [])
        if len(symbol_trades) >= self.min_symbol_history_for_entry:
            stats = self._stats(symbol_trades[-self.guard_symbol_window :])
            if stats["win_rate"] < self.min_symbol_win_rate_for_entry:
                return "low_symbol_win_rate"
            if stats["expectancy_r"] < self.min_symbol_expectancy_r_for_entry:
                return "low_symbol_expectancy"
        oi_notional = float(market.open_interest or 0.0) * float(market.mark_price or 0.0)
        if oi_notional < self.min_open_interest_notional_usd:
            return "low_open_interest"
        return None

    @staticmethod
    def _break_even_stop_price(side: str, entry: float, risk: float, offset_r: float) -> float:
        if str(side or "").upper() == "SHORT":
            return entry - (offset_r * risk)
        return entry + (offset_r * risk)

    @staticmethod
    def _stop_state(managed: ManagedTrade) -> str:
        if managed.trailing_stop_active:
            return "TRAILING"
        if managed.moved_to_break_even:
            return "BREAKEVEN"
        return "ORIGINAL"

    @staticmethod
    def _exit_type_from_reason(reason: str, result: str) -> str:
        upper = str(reason or "").upper()
        if "ADVERSE_CUT" in upper:
            return "ADVERSE_CUT"
        if "MOMENTUM_REVERSAL" in upper:
            return "MOMENTUM_REVERSAL"
        if "STAGNATION" in upper:
            return "STAGNATION_EXIT"
        if "TIMEOUT" in upper:
            return "TIMEOUT_EXIT"
        if "NETWORK_ERROR" in upper:
            return "NETWORK_ERROR_EXIT"
        result_upper = str(result or "").upper()
        if result_upper == "WIN":
            return "DIRECT_TP"
        if result_upper == "LOSS":
            return "DIRECT_SL"
        return "DIRECT_EXIT"

    @staticmethod
    def _hold_minutes(closed: ClosedTrade) -> Optional[float]:
        try:
            opened = int(closed.opened_at_ms)
            closed_at = int(closed.closed_at_ms)
        except (TypeError, ValueError):
            return None
        if closed_at <= opened:
            return None
        return round((closed_at - opened) / 60000.0, 4)

    def _build_trade_meta(self, managed: ManagedTrade, closed: ClosedTrade) -> Dict[str, object]:
        return {
            "signal_type": self._signal_type_from_reason(closed.reason),
            "regime": self._signal_regime_from_reason(closed.reason),
            "exit_type": self._exit_type_from_reason(closed.reason, closed.result),
            "stop_state": self._stop_state(managed),
            "hold_minutes": self._hold_minutes(closed),
        }

    @staticmethod
    def _trade_result_key(closed: ClosedTrade) -> str:
        return f"{closed.symbol}|{closed.timeframe}|{closed.side}|{closed.opened_at_ms}|{closed.closed_at_ms}|{round(float(closed.exit_price), 8)}"

    def _post_close_cooldown_cycles(self, closed: ClosedTrade, trade_meta: Dict[str, object]) -> int:
        cooldown = max(0, self.reentry_cooldown_cycles)
        hold_minutes = trade_meta.get("hold_minutes")
        exit_type = str(trade_meta.get("exit_type") or "").upper()
        if isinstance(hold_minutes, (int, float)) and float(hold_minutes) <= self.fast_exit_minutes_threshold:
            cooldown = max(cooldown, self.fast_exit_reentry_cooldown_cycles)
        if exit_type in {"ADVERSE_CUT", "STAGNATION_EXIT", "MOMENTUM_REVERSAL", "TIMEOUT_EXIT"}:
            cooldown = max(cooldown, self.fast_exit_reentry_cooldown_cycles)
        return cooldown

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def _estimate_win_probability(self, candidate: CandidateSignal) -> float:
        conf_component = self._clamp(candidate.signal.confidence - 0.03, 0.0, 1.0)
        rr_component = self._clamp(candidate.rr / 1.8, 0.0, 1.0)
        exp_component = self._clamp((candidate.expectancy_r + 0.25) / 0.85, 0.0, 1.0)
        trend_component = self._clamp(candidate.trend_strength / 0.01, 0.0, 1.0)
        quality_component = self._clamp(candidate.symbol_quality, 0.0, 1.0)
        setup_quality = (
            (conf_component * 0.40)
            + (exp_component * 0.25)
            + (trend_component * 0.15)
            + (quality_component * 0.12)
            + (rr_component * 0.08)
        )
        symbol = candidate.signal.symbol
        symbol_trades = self.symbol_recent_trades.get(symbol, [])
        actual_win_rate = sum(1 for t in symbol_trades if t.result == "WIN") / len(symbol_trades) if len(symbol_trades) >= 3 else 0.5
        blended = (setup_quality * 0.60) + (actual_win_rate * 0.40)
        calibrated = (blended * 0.95) + 0.01
        return self._clamp(calibrated, 0.01, 0.99)

    @staticmethod
    def _probability_bucket(win_probability: float) -> Dict[str, str]:
        if win_probability >= 0.7:
            return {"id": "ge_70", "label": "70%+ Win-Likely"}
        if win_probability >= 0.5:
            return {"id": "between_50_69", "label": "50-69% Mixed"}
        if win_probability >= 0.3:
            return {"id": "between_30_49", "label": "30-49% Risky"}
        if win_probability >= 0.2:
            return {"id": "between_20_29", "label": "20-29% Weak"}
        return {"id": "below_20", "label": "<20% Loss-Likely"}

    def _build_probability_categories(self, trades: List[Dict]) -> Dict[str, Dict]:
        categories: Dict[str, Dict] = {
            "ge_70": {"label": "70%+ Win-Likely", "count": 0},
            "between_50_69": {"label": "50-69% Mixed", "count": 0},
            "between_30_49": {"label": "30-49% Risky", "count": 0},
            "between_20_29": {"label": "20-29% Weak", "count": 0},
            "below_20": {"label": "<20% Loss-Likely", "count": 0},
        }
        for trade in trades:
            bucket_id = str(trade.get("probability_bucket") or "")
            if bucket_id in categories:
                categories[bucket_id]["count"] += 1
        return categories

    @staticmethod
    def _timeframe_minutes(timeframe: str) -> int:
        raw = str(timeframe or "").strip().lower()
        if raw.endswith("m"):
            return max(1, int(raw[:-1] or "1"))
        if raw.endswith("h"):
            return max(1, int(raw[:-1] or "1")) * 60
        if raw.endswith("d"):
            return max(1, int(raw[:-1] or "1")) * 1440
        return 1

    def _effective_wait_minutes(self, timeframe_minutes: int, signal_type: str = "", signal_reason: str = "") -> int:
        wait_candles = self._max_wait_candles_for_signal(signal_type, signal_reason)
        if self._is_break_pattern_signal(signal_type, signal_reason):
            wait_candles += max(0, self.breakdown_timeout_extension_candles)
        candle_based_wait = wait_candles * timeframe_minutes
        return max(self.max_wait_minutes_per_trade, candle_based_wait, timeframe_minutes * 2)

    def _is_break_pattern_signal(self, signal_type: str, signal_reason: str = "") -> bool:
        normalized = str(signal_type or "").upper()
        if normalized == "BREAKDOWN":
            return True
        if normalized != "STRUCTURE":
            return False
        pattern = self._signal_pattern_from_reason(signal_reason)
        return "break" in pattern

    def _max_wait_candles_for_signal(self, signal_type: str, signal_reason: str = "") -> int:
        wait_candles = self.max_wait_candles
        if self._is_break_pattern_signal(signal_type, signal_reason):
            wait_candles *= max(1, self.breakdown_wait_candle_multiplier)
        return wait_candles
