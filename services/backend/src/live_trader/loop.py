from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Dict, List

from src.alerts import play_trade_alert
from src.live_trader.models import CandidateSignal


class TraderLoopMixin:
    def run(self) -> Dict:
        cycles = 0
        while cycles < self.max_cycles:
            self._apply_runtime_control()
            self._decrement_cooldowns()
            cycles += 1
            current_day = self._current_utc_day()
            if self._daily_loss_pause_day is not None and self._daily_loss_pause_day != current_day:
                print(json.dumps({"type": "DAILY_LOSS_LIMIT_CLEARED", "time": self._now_iso(), "cycle": cycles, "previous_day": self._daily_loss_pause_day, "current_day": current_day}))
                self._daily_loss_pause_day = None
            self._refresh_batch_market_data()
            snapshots = []
            for symbol in self.symbols:
                price = self._ticker_cache.get(symbol)
                if price is not None:
                    snapshots.append({"symbol": symbol, "price": price, "time": 0})
            print(json.dumps({"type": "LIVE_MARKET", "time": self._now_iso(), "snapshots": snapshots}))
            self._update_open_trades(cycles)
            daily_realized = self._daily_realized_pnl(current_day)
            if self.daily_loss_limit_r > 0 and self._daily_loss_pause_day is None and float(daily_realized["pnl_r"]) <= (-1.0 * self.daily_loss_limit_r):
                self._daily_loss_pause_day = current_day
                print(json.dumps({"type": "DAILY_LOSS_LIMIT_PAUSE", "time": self._now_iso(), "cycle": cycles, "utc_day": current_day, "daily_loss_limit_r": round(self.daily_loss_limit_r, 6), "daily_realized_pnl_r": daily_realized["pnl_r"], "daily_realized_pnl_usd": daily_realized["pnl_usd"]}))
            if self._daily_loss_pause_day == current_day:
                self.no_trade_filter_block_streak = 0
                print(json.dumps({"type": "NO_SIGNAL", "time": self._now_iso(), "cycle": cycles, "reason": "DAILY_LOSS_LIMIT_PAUSED", "utc_day": current_day, "daily_loss_limit_r": round(self.daily_loss_limit_r, 6), "daily_realized_pnl_r": daily_realized["pnl_r"], "daily_realized_pnl_usd": daily_realized["pnl_usd"]}))
                time.sleep(self.poll_seconds)
                continue
            candidates = self._signal_candidates()
            candidate_win_prob = {id(c): self._estimate_win_probability(c) for c in candidates}
            possible_trades = []
            execution_candidates: List[CandidateSignal] = []
            candidate_rejections: Dict[str, int] = defaultdict(int)
            for candidate in candidates:
                if candidate.signal.confidence < self.min_candidate_confidence:
                    candidate_rejections["candidate_confidence"] += 1
                    continue
                if candidate.expectancy_r < self.min_candidate_expectancy_r:
                    candidate_rejections["candidate_expectancy"] += 1
                    continue
                execution_candidates.append(candidate)
                win_probability = candidate_win_prob.get(id(candidate), self._estimate_win_probability(candidate))
                bucket = self._probability_bucket(win_probability)
                possible_trades.append(
                    {
                        "symbol": candidate.signal.symbol,
                        "timeframe": candidate.signal.timeframe,
                        "side": candidate.signal.side,
                        "entry": candidate.signal.entry,
                        "take_profit": candidate.signal.take_profit,
                        "stop_loss": candidate.signal.stop_loss,
                        "confidence": round(candidate.signal.confidence, 6),
                        "trend_strength": round(candidate.trend_strength, 6),
                        "rr": round(candidate.rr, 6),
                        "expectancy_r": round(candidate.expectancy_r, 6),
                        "score": round(candidate.score, 6),
                        "symbol_quality": round(candidate.symbol_quality, 6),
                        "win_probability": round(win_probability, 6),
                        "probability_bucket": bucket["id"],
                        "probability_bucket_label": bucket["label"],
                        "loss_likely": bool(win_probability < 0.5),
                        "reason": candidate.signal.reason,
                    }
                )
                if len(possible_trades) >= self.possible_trades_limit:
                    break
            probability_categories = self._build_probability_categories(possible_trades)
            print(json.dumps({"type": "POSSIBLE_TRADES", "time": self._now_iso(), "cycle": cycles, "min_candidate_confidence": self.min_candidate_confidence, "min_candidate_expectancy_r": self.min_candidate_expectancy_r, "max_parallel_candidates": self.max_parallel_candidates, "possible_trades_limit": self.possible_trades_limit, "total_candidates_seen": len(candidates), "total_possible_trades": len(possible_trades), "candidate_rejections": dict(candidate_rejections), "probability_categories": probability_categories, "blocked_symbols": [{"symbol": s, "cooldown_cycles_left": int(self.symbol_cooldowns.get(s, 0))} for s in self.symbols if int(self.symbol_cooldowns.get(s, 0)) > 0], "trades": possible_trades}))
            if self.global_pause_cycles_left > 0:
                print(json.dumps({"type": "NO_SIGNAL", "time": self._now_iso(), "cycle": cycles, "reason": "GLOBAL_RISK_OFF", "global_pause_cycles_left": self.global_pause_cycles_left}))
                self.global_pause_cycles_left = max(0, self.global_pause_cycles_left - 1)
                if self.global_pause_cycles_left == 0:
                    print(json.dumps({"type": "GLOBAL_RISK_OFF_CLEARED", "time": self._now_iso(), "cycle": cycles}))
                time.sleep(self.poll_seconds)
                continue
            if not candidates or not execution_candidates:
                self.no_trade_filter_block_streak = 0
                print(json.dumps({"type": "NO_SIGNAL", "time": self._now_iso(), "cycle": cycles, "reason": "NO_CANDIDATES"}))
                time.sleep(self.poll_seconds)
                continue
            confirmations: Dict[tuple[str, str], set[str]] = {}
            for candidate in execution_candidates:
                key = (candidate.signal.symbol, candidate.signal.side)
                confirmations.setdefault(key, set()).add(candidate.signal.timeframe)
            qualified: List[CandidateSignal] = []
            execution_rejections: Dict[str, int] = defaultdict(int)
            open_trade_symbols = self._open_trade_symbols()
            for candidate in execution_candidates:
                signal_type = self._signal_type_from_reason(candidate.signal.reason)
                is_crossover = signal_type == "CROSSOVER"
                min_confidence = self.crossover_execute_min_confidence if is_crossover else self.execute_min_confidence
                min_expectancy_r = self.crossover_execute_min_expectancy_r if is_crossover else self.execute_min_expectancy_r
                min_score = self.crossover_execute_min_score if is_crossover else self.execute_min_score
                if candidate.signal.confidence < min_confidence:
                    execution_rejections["execute_confidence"] += 1
                    if is_crossover:
                        execution_rejections["execute_crossover_confidence"] += 1
                    continue
                if candidate.expectancy_r < min_expectancy_r:
                    execution_rejections["execute_expectancy"] += 1
                    if is_crossover:
                        execution_rejections["execute_crossover_expectancy"] += 1
                    continue
                if candidate.score < min_score:
                    execution_rejections["execute_score"] += 1
                    if is_crossover:
                        execution_rejections["execute_crossover_score"] += 1
                    continue
                win_probability = candidate_win_prob.get(id(candidate), self._estimate_win_probability(candidate))
                min_win_probability = self.crossover_execute_min_win_probability if is_crossover else self.execute_min_win_probability
                if win_probability < min_win_probability:
                    execution_rejections["execute_win_probability"] += 1
                    if is_crossover:
                        execution_rejections["execute_crossover_win_probability"] += 1
                    continue
                if self.require_dual_timeframe_confirm and len(confirmations.get((candidate.signal.symbol, candidate.signal.side), set())) < 2:
                    execution_rejections["execute_dual_timeframe_confirm"] += 1
                    continue
                if candidate.signal.timeframe not in self.execute_timeframes:
                    execution_rejections["execute_timeframe_not_allowed"] += 1
                    continue
                candidate_regime = self._signal_regime_from_reason(candidate.signal.reason)
                if self.allowed_execution_regimes and candidate_regime not in self.allowed_execution_regimes:
                    execution_rejections["execute_regime_not_allowed"] += 1
                    continue
                if candidate.signal.symbol in open_trade_symbols:
                    execution_rejections["execute_symbol_already_open"] += 1
                    continue
                policy_decision = self.policy_engine.evaluate_candidate(signal_type, candidate.signal.side)
                if not policy_decision.allowed:
                    execution_rejections["policy_setup_side_paused"] += 1
                    continue
                qualified.append(candidate)
            for key, count in candidate_rejections.items():
                self.filter_rejections[key] += count
            for key, count in execution_rejections.items():
                self.filter_rejections[key] += count
            if not qualified:
                self.no_trade_filter_block_streak += 1
                print(json.dumps({"type": "NO_SIGNAL", "time": self._now_iso(), "cycle": cycles, "reason": "EXECUTION_FILTER_BLOCK", "candidate_count": len(execution_candidates), "execute_min_confidence": self.execute_min_confidence, "execute_min_expectancy_r": self.execute_min_expectancy_r, "execute_min_score": self.execute_min_score, "execute_min_win_probability": self.execute_min_win_probability, "execution_rejections": dict(execution_rejections), "no_trade_filter_block_streak": self.no_trade_filter_block_streak}))
                self._maybe_relax_execution_filters(cycles, len(execution_candidates))
                time.sleep(self.poll_seconds)
                continue
            available_slots = max(0, self.max_open_trades - len(self.open_trades))
            if available_slots <= 0:
                self.no_trade_filter_block_streak = 0
                print(json.dumps({"type": "NO_SIGNAL", "time": self._now_iso(), "cycle": cycles, "reason": "MAX_OPEN_TRADES_REACHED", "max_open_trades": self.max_open_trades, "open_trades_count": len(self.open_trades)}))
                time.sleep(self.poll_seconds)
                continue
            if len(qualified) > 1 and (qualified[0].score - qualified[1].score) < self.min_score_gap:
                self.no_trade_filter_block_streak = 0
                print(json.dumps({"type": "NO_SIGNAL", "time": self._now_iso(), "cycle": cycles, "reason": "LOW_SCORE_SEPARATION", "top_score": round(qualified[0].score, 6), "second_score": round(qualified[1].score, 6), "min_score_gap": round(self.min_score_gap, 6)}))
                time.sleep(self.poll_seconds)
                continue
            self.no_trade_filter_block_streak = 0
            open_long_count = sum(1 for managed in self.open_trades.values() if managed.signal.side == "LONG")
            open_short_count = sum(1 for managed in self.open_trades.values() if managed.signal.side == "SHORT")
            selected_candidates: List[CandidateSignal] = []
            seen_symbols = set(self._open_trade_symbols())
            directional_limit_hits = {"LONG": 0, "SHORT": 0}
            for candidate in qualified:
                if candidate.signal.symbol in seen_symbols:
                    continue
                if candidate.signal.side == "LONG" and open_long_count >= self.max_same_direction_trades:
                    directional_limit_hits["LONG"] += 1
                    continue
                if candidate.signal.side == "SHORT" and open_short_count >= self.max_same_direction_trades:
                    directional_limit_hits["SHORT"] += 1
                    continue
                selected_candidates.append(candidate)
                seen_symbols.add(candidate.signal.symbol)
                if candidate.signal.side == "LONG":
                    open_long_count += 1
                else:
                    open_short_count += 1
                if len(selected_candidates) >= min(self.top_n, available_slots):
                    break
            if not selected_candidates:
                blocked_by_direction = directional_limit_hits["LONG"] > 0 or directional_limit_hits["SHORT"] > 0
                print(json.dumps({"type": "NO_SIGNAL", "time": self._now_iso(), "cycle": cycles, "reason": "DIRECTIONAL_EXPOSURE_LIMIT" if blocked_by_direction else "ALL_QUALIFIED_SYMBOLS_ALREADY_OPEN", "open_trade_symbols": sorted(self._open_trade_symbols()), "max_same_direction_trades": self.max_same_direction_trades, "directional_limit_hits": directional_limit_hits, "open_long_count": open_long_count, "open_short_count": open_short_count}))
                time.sleep(self.poll_seconds)
                continue
            for selected in selected_candidates:
                selected_win_probability = candidate_win_prob.get(id(selected), self._estimate_win_probability(selected))
                selected_bucket = self._probability_bucket(selected_win_probability)
                play_trade_alert(self.enable_sound)
                print(json.dumps({"type": "OPEN_TRADE", "time": self._now_iso(), "cycle": cycles, "symbol": selected.signal.symbol, "timeframe": selected.signal.timeframe, "side": selected.signal.side, "entry": selected.signal.entry, "take_profit": selected.signal.take_profit, "stop_loss": selected.signal.stop_loss, "confidence": selected.signal.confidence, "trend_strength": round(selected.trend_strength, 6), "cost_r": round(selected.cost_r, 6), "score": round(selected.score, 6), "symbol_quality": round(selected.symbol_quality, 6), "win_probability": round(selected_win_probability, 6), "probability_bucket": selected_bucket["id"], "probability_bucket_label": selected_bucket["label"], "reason": selected.signal.reason}))
                binance_opened = False
                if self.executor.enabled:
                    try:
                        exec_result = self.executor.open_trade(symbol=selected.signal.symbol, side=selected.signal.side, entry_price=selected.signal.entry, stop_loss=selected.signal.stop_loss, take_profit=selected.signal.take_profit)
                        binance_opened = exec_result.get("executed", False)
                        print(json.dumps({"type": "BINANCE_ORDER", "time": self._now_iso(), "action": "OPEN", "symbol": selected.signal.symbol, "side": selected.signal.side, "result": exec_result}))
                        if not binance_opened:
                            continue
                    except Exception as exc:
                        print(json.dumps({"type": "BINANCE_ORDER", "time": self._now_iso(), "action": "OPEN_FAILED", "symbol": selected.signal.symbol, "error": str(exc)}))
                key = f"{selected.signal.symbol}:{selected.signal.timeframe}:{selected.signal.side}"
                self.open_trades[key] = self._make_managed_trade(selected.signal, binance_opened)
            summary = self._summary()
            if summary["trades"] >= self.min_trades_for_success and summary["trades"] >= self.target_trades and summary["win_rate"] >= self.target_win_rate:
                self._close_all_open_trades_on_exit(cycles)
                return {"status": "TARGET_REACHED", "cycles": cycles, "summary": summary}
            if summary["trades"] >= self.target_trades:
                self._close_all_open_trades_on_exit(cycles)
                return {"status": "TARGET_NOT_REACHED", "cycles": cycles, "summary": summary}
        self._close_all_open_trades_on_exit(cycles)
        return {"status": "MAX_CYCLES_REACHED", "cycles": cycles, "summary": self._summary()}
