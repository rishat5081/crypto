from __future__ import annotations

import json
import time
from typing import Dict, Optional

from src.indicators import ema
from src.models import ClosedTrade, Signal
from src.trade_engine import TradeEngine


class TraderManagementMixin:
    def _should_extend_breakdown_timeout(self, managed, latest, now_r: float) -> bool:
        signal_type = self._signal_type_from_reason(managed.signal.reason)
        if not self._is_break_pattern_signal(signal_type, managed.signal.reason):
            return False
        extension_limit = self._max_wait_candles_for_signal(signal_type, managed.signal.reason) + max(0, self.breakdown_timeout_extension_candles)
        if managed.bars_seen >= extension_limit:
            return False
        if managed.best_r < self.breakdown_timeout_min_best_r or now_r < self.breakdown_timeout_min_current_r:
            return False
        active = managed.engine.active_trade
        if active is None:
            return False
        closed_candles = [candle for candle in (managed.last_known_candles or []) if getattr(candle, "close_time_ms", 0) <= getattr(latest, "close_time_ms", 0)]
        if len(closed_candles) < max(2, self.base_strategy.params.ema_fast):
            return False
        ema_fast_v = ema([candle.close for candle in closed_candles], self.base_strategy.params.ema_fast)
        return latest.close <= ema_fast_v if active.side == "SHORT" else latest.close >= ema_fast_v

    def _wait_for_close(self, signal: Signal) -> ClosedTrade:
        engine = TradeEngine(risk_usd=self.risk_usd)
        opened = engine.maybe_open_trade(signal)
        if not opened:
            raise RuntimeError("Failed to open paper trade")
        start = time.time()
        timeframe_minutes = self._timeframe_minutes(signal.timeframe)
        signal_type = self._signal_type_from_reason(signal.reason)
        effective_wait_minutes = self._effective_wait_minutes(timeframe_minutes, signal_type, signal.reason)
        max_wait_seconds = effective_wait_minutes * 60
        last_seen_close_ms = signal.signal_time_ms
        best_r = 0.0
        original_risk = max(abs(signal.entry - signal.stop_loss), 1e-9)
        bars_seen = 0
        consecutive_adverse_bars = 0
        moved_to_break_even = False
        trailing_stop_active = False
        consecutive_fetch_errors = 0
        last_known_candles = None

        def current_r_multiple(side: str, entry: float, stop_loss: float, price: float) -> float:
            risk = max(abs(entry - stop_loss), 1e-9)
            pnl_per_unit = price - entry if side == "LONG" else entry - price
            return pnl_per_unit / risk

        def make_exit(active, latest, reason_prefix):
            pnl_per_unit = latest.close - active.entry if active.side == "LONG" else active.entry - latest.close
            gross_r = pnl_per_unit / original_risk
            cost_r = self.cost_model.trade_cost_r(active.entry, signal.stop_loss)
            net_r = gross_r - cost_r
            return ClosedTrade(
                symbol=active.symbol,
                timeframe=active.timeframe,
                side=active.side,
                entry=active.entry,
                take_profit=active.take_profit,
                stop_loss=active.stop_loss,
                exit_price=latest.close,
                result="WIN" if net_r > 0 else "LOSS",
                opened_at_ms=active.opened_at_ms,
                closed_at_ms=latest.close_time_ms,
                pnl_r=net_r,
                pnl_usd=net_r * self.risk_usd,
                reason=f"{reason_prefix} | {active.reason}",
            )

        while True:
            if time.time() - start >= max_wait_seconds:
                active = engine.active_trade
                latest = last_known_candles[-1] if active and last_known_candles else None
                if latest:
                    return make_exit(active, latest, "TIMEOUT_EXIT")
            try:
                candles = self.client.fetch_klines(symbol=signal.symbol, interval=signal.timeframe, limit=10)
                last_known_candles = candles
                consecutive_fetch_errors = 0
            except Exception as exc:
                consecutive_fetch_errors += 1
                print(json.dumps({"type": "TRADE_MONITOR_FETCH_ERROR", "time": self._now_iso(), "symbol": signal.symbol, "error": str(exc), "consecutive_errors": consecutive_fetch_errors}))
                if consecutive_fetch_errors >= 5 and last_known_candles:
                    active = engine.active_trade
                    if active:
                        return make_exit(active, last_known_candles[-1], "NETWORK_ERROR_EXIT")
                time.sleep(self.poll_seconds)
                continue
            closed_candles = [c for c in candles if c.close_time_ms < int(time.time() * 1000)]
            if closed_candles:
                latest = closed_candles[-1]
                if latest.close_time_ms > last_seen_close_ms:
                    last_seen_close_ms = latest.close_time_ms
                    active = engine.active_trade
                    if active is None:
                        raise RuntimeError("Active trade missing while waiting for close")
                    bars_seen += 1
                    now_r = current_r_multiple(active.side, active.entry, signal.stop_loss, latest.close)
                    favorable_price = latest.high if active.side == "LONG" else latest.low
                    peak_r = current_r_multiple(active.side, active.entry, signal.stop_loss, favorable_price)
                    best_r = max(best_r, peak_r)
                    consecutive_adverse_bars = consecutive_adverse_bars + 1 if now_r < 0 else 0
                    closed = engine.on_candle(latest)
                    if closed:
                        return closed
                    active = engine.active_trade
                    if active is None:
                        raise RuntimeError("Active trade missing after candle update")
                    if self.enable_trailing_stop and best_r >= self.trail_trigger_r:
                        trail_sl_r = best_r * self.trail_keep_pct
                        new_sl = active.entry + (trail_sl_r * original_risk) if active.side == "LONG" else active.entry - (trail_sl_r * original_risk)
                        if (active.side == "LONG" and new_sl > active.stop_loss) or (active.side == "SHORT" and new_sl < active.stop_loss):
                            active.stop_loss = new_sl
                        action = "TRAILING_STOP_UPDATED" if trailing_stop_active else "TRAILING_STOP_ACTIVATED"
                        trailing_stop_active = True
                        payload = {"type": "RISK_MANAGER_UPDATE", "time": self._now_iso(), "symbol": active.symbol, "timeframe": active.timeframe, "action": action, "updated_stop_loss": round(active.stop_loss, 6), "best_r": round(best_r, 4)}
                        if action == "TRAILING_STOP_ACTIVATED":
                            payload["trail_keep_pct"] = self.trail_keep_pct
                        print(json.dumps(payload))
                    elif self.enable_break_even and (not moved_to_break_even) and best_r >= self.break_even_trigger_r:
                        risk = max(abs(active.entry - active.stop_loss), 1e-9)
                        be_stop = self._break_even_stop_price(active.side, active.entry, risk, self.break_even_offset_r)
                        if (active.side == "LONG" and be_stop > active.stop_loss) or (active.side == "SHORT" and be_stop < active.stop_loss):
                            active.stop_loss = be_stop
                            moved_to_break_even = True
                        if moved_to_break_even:
                            print(json.dumps({"type": "RISK_MANAGER_UPDATE", "time": self._now_iso(), "symbol": active.symbol, "timeframe": active.timeframe, "action": "STOP_TO_BREAKEVEN", "updated_stop_loss": round(active.stop_loss, 6), "best_r": round(best_r, 6)}))
                    worst_price = latest.low if active.side == "LONG" else latest.high
                    adverse_r = current_r_multiple(active.side, active.entry, signal.stop_loss, worst_price)
                    if adverse_r <= (-1.0 * self.max_adverse_r_cut):
                        return make_exit(active, latest, "ADVERSE_CUT")
                    if consecutive_adverse_bars >= self.momentum_reversal_bars and now_r <= self.momentum_reversal_r:
                        print(json.dumps({"type": "RISK_MANAGER_UPDATE", "time": self._now_iso(), "symbol": active.symbol, "timeframe": active.timeframe, "action": "MOMENTUM_REVERSAL_EXIT", "now_r": round(now_r, 4), "consecutive_adverse_bars": consecutive_adverse_bars}))
                        return make_exit(active, latest, "MOMENTUM_REVERSAL")
                    if bars_seen >= self.max_stagnation_bars and best_r < self.min_progress_r_for_stagnation:
                        return make_exit(active, latest, "STAGNATION_EXIT")
                    if bars_seen >= self.max_wait_candles:
                        return make_exit(active, latest, "CANDLE_TIMEOUT")
            time.sleep(self.poll_seconds)

    def _apply_feedback(self, trade: ClosedTrade) -> None:
        symbol = trade.symbol
        current = self.symbol_confidence.get(symbol, float(self.strategy_payload["min_confidence"]))
        if trade.result == "LOSS":
            self.symbol_confidence[symbol] = min(0.93, current + 0.015)
            self.min_trend_strength = min(0.003, self.min_trend_strength + 0.000015)
            self.min_rr_floor = min(0.75, self.min_rr_floor + 0.0025)
            self.execute_min_confidence = min(0.92, self.execute_min_confidence + 0.0015)
            self.execute_min_expectancy_r = min(0.5, self.execute_min_expectancy_r + 0.003)
            self.execute_min_score = min(0.85, self.execute_min_score + 0.0015)
        else:
            self.symbol_confidence[symbol] = max(0.50, current - 0.015)
            self.min_trend_strength = max(0.0004, self.min_trend_strength - 0.00003)
            self.execute_min_confidence = max(0.58, self.execute_min_confidence - 0.004)
            self.execute_min_expectancy_r = max(0.03, self.execute_min_expectancy_r - 0.01)
            self.execute_min_score = max(0.50, self.execute_min_score - 0.004)

    def _apply_loss_guard(self, trade: ClosedTrade, cycle: int) -> None:
        if not self.loss_guard_enabled:
            return
        symbol = trade.symbol
        if trade.result == "LOSS":
            self.global_consecutive_losses += 1
            self.symbol_consecutive_losses[symbol] = int(self.symbol_consecutive_losses.get(symbol, 0)) + 1
        else:
            self.global_consecutive_losses = 0
            self.symbol_consecutive_losses[symbol] = 0
        if trade.result != "LOSS":
            return
        symbol_streak = int(self.symbol_consecutive_losses.get(symbol, 0))
        if symbol_streak >= self.max_symbol_consecutive_losses:
            self.symbol_cooldowns[symbol] = max(self.symbol_pause_cycles, int(self.symbol_cooldowns.get(symbol, 0)))
            print(json.dumps({"type": "LOSS_GUARD_SYMBOL_PAUSE", "time": self._now_iso(), "cycle": cycle, "symbol": symbol, "symbol_consecutive_losses": symbol_streak, "cooldown_cycles": self.symbol_cooldowns[symbol], "max_symbol_consecutive_losses": self.max_symbol_consecutive_losses}))
            self.symbol_consecutive_losses[symbol] = 0
        if self.global_consecutive_losses >= self.max_global_consecutive_losses:
            before = {
                "min_candidate_confidence": self.min_candidate_confidence,
                "min_rr_floor": self.min_rr_floor,
                "min_trend_strength": self.min_trend_strength,
                "execute_min_confidence": self.execute_min_confidence,
                "execute_min_expectancy_r": self.execute_min_expectancy_r,
                "execute_min_score": self.execute_min_score,
            }
            self.global_pause_cycles_left = max(self.global_pause_cycles_left, self.global_pause_cycles)
            self.min_candidate_confidence = min(0.90, self.min_candidate_confidence + 0.005)
            self.min_rr_floor = min(0.8, self.min_rr_floor + 0.01)
            self.min_trend_strength = min(0.004, self.min_trend_strength + 0.000025)
            self.execute_min_confidence = min(0.92, self.execute_min_confidence + 0.005)
            self.execute_min_expectancy_r = min(0.5, self.execute_min_expectancy_r + 0.025)
            self.execute_min_score = min(0.88, self.execute_min_score + 0.01)
            print(json.dumps({"type": "LOSS_GUARD_GLOBAL_PAUSE", "time": self._now_iso(), "cycle": cycle, "global_consecutive_losses": self.global_consecutive_losses, "global_pause_cycles_left": self.global_pause_cycles_left, "max_global_consecutive_losses": self.max_global_consecutive_losses, "before": before, "after": {"min_candidate_confidence": round(self.min_candidate_confidence, 6), "min_rr_floor": round(self.min_rr_floor, 6), "min_trend_strength": round(self.min_trend_strength, 6), "execute_min_confidence": round(self.execute_min_confidence, 6), "execute_min_expectancy_r": round(self.execute_min_expectancy_r, 6), "execute_min_score": round(self.execute_min_score, 6), "execute_min_win_probability": round(self.execute_min_win_probability, 6)}}))
            self.global_consecutive_losses = 0

    def _maybe_relax_execution_filters(self, cycle: int, candidate_count: int) -> None:
        if self.relax_after_filter_blocks <= 0 or self.no_trade_filter_block_streak < self.relax_after_filter_blocks:
            return
        before = {
            "execute_min_confidence": self.execute_min_confidence,
            "execute_min_expectancy_r": self.execute_min_expectancy_r,
            "execute_min_score": self.execute_min_score,
            "execute_min_win_probability": self.execute_min_win_probability,
        }
        self.execute_min_confidence = max(self.relax_min_execute_confidence, self.execute_min_confidence - self.relax_conf_step)
        self.execute_min_expectancy_r = max(self.relax_min_execute_expectancy_r, self.execute_min_expectancy_r - self.relax_expectancy_step)
        self.execute_min_score = max(self.relax_min_execute_score, self.execute_min_score - self.relax_score_step)
        self.execute_min_win_probability = max(0.48, self.execute_min_win_probability - 0.01)
        self.no_trade_filter_block_streak = 0
        print(json.dumps({"type": "EXECUTION_FILTER_RELAX", "time": self._now_iso(), "cycle": cycle, "candidate_count": candidate_count, "relax_after_filter_blocks": self.relax_after_filter_blocks, "before": before, "after": {"execute_min_confidence": round(self.execute_min_confidence, 6), "execute_min_expectancy_r": round(self.execute_min_expectancy_r, 6), "execute_min_score": round(self.execute_min_score, 6), "execute_min_win_probability": round(self.execute_min_win_probability, 6)}}))

    def _summary(self) -> Dict:
        trades = len(self.recent_trades)
        wins = sum(1 for t in self.recent_trades if t.result == "WIN")
        losses = trades - wins
        win_rate = (wins / trades) if trades else 0.0
        expectancy_r = (sum(t.pnl_r for t in self.recent_trades) / trades) if trades else 0.0
        symbol_health: Dict[str, Dict] = {}
        for symbol in self.symbols:
            stats = self._stats(self.symbol_recent_trades.get(symbol, [])[-self.guard_symbol_window :])
            symbol_health[symbol] = {
                "trades": stats["trades"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "win_rate": round(stats["win_rate"], 4),
                "expectancy_r": round(stats["expectancy_r"], 6),
                "cooldown_cycles_left": int(self.symbol_cooldowns.get(symbol, 0)),
            }
        blocked_symbols = [{"symbol": s, "cooldown_cycles_left": int(self.symbol_cooldowns.get(s, 0))} for s in self.symbols if int(self.symbol_cooldowns.get(s, 0)) > 0]
        daily_realized = self._daily_realized_pnl()
        return {
            "trades": trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 4),
            "expectancy_r": round(expectancy_r, 6),
            "expectancy_usd_per_trade": round(expectancy_r * self.risk_usd, 6),
            "risk_usd": round(self.risk_usd, 6),
            "risk_sizing_mode": self.risk_sizing_mode,
            "starting_balance_usd": round(self.starting_balance_usd, 6),
            "risk_per_trade_pct": round(self.risk_per_trade_pct, 6),
            "paper_risk_usd": None if self.paper_risk_usd is None else round(float(self.paper_risk_usd), 6),
            "symbol_confidence": self.symbol_confidence,
            "min_rr_floor": round(self.min_rr_floor, 4),
            "min_trend_strength": round(self.min_trend_strength, 6),
            "min_candidate_confidence": round(self.min_candidate_confidence, 6),
            "execute_min_confidence": round(self.execute_min_confidence, 6),
            "execute_min_expectancy_r": round(self.execute_min_expectancy_r, 6),
            "execute_min_score": round(self.execute_min_score, 6),
            "execute_min_win_probability": round(self.execute_min_win_probability, 6),
            "filter_rejections": dict(self.filter_rejections),
            "max_open_trades": int(self.max_open_trades),
            "open_trades_count": len(self.open_trades),
            "open_trades": [{"symbol": managed.signal.symbol, "timeframe": managed.signal.timeframe, "side": managed.signal.side, "entry": managed.signal.entry, "bars_seen": managed.bars_seen, "best_r": round(managed.best_r, 6)} for managed in self.open_trades.values()],
            "possible_trades_limit": int(self.possible_trades_limit),
            "max_parallel_candidates": int(self.max_parallel_candidates),
            "global_pause_cycles_left": int(self.global_pause_cycles_left),
            "global_consecutive_losses": int(self.global_consecutive_losses),
            "daily_loss_limit_r": round(self.daily_loss_limit_r, 6),
            "daily_loss_pause_day": self._daily_loss_pause_day,
            "daily_realized_pnl": daily_realized,
            "no_trade_filter_block_streak": int(self.no_trade_filter_block_streak),
            "active_symbols": self._active_symbols(),
            "blocked_symbols": blocked_symbols,
            "symbol_health": symbol_health,
            "setup_side_health": self.policy_engine.health(),
        }
