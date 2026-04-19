from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Optional

from src.models import ClosedTrade, Signal
from src.trade_engine import TradeEngine
from src.live_trader.models import ManagedTrade


class TraderExecutionMixin:
    @staticmethod
    def _current_r_multiple(side: str, entry: float, stop_loss: float, price: float) -> float:
        risk = max(abs(entry - stop_loss), 1e-9)
        pnl_per_unit = price - entry if side == "LONG" else entry - price
        return pnl_per_unit / risk

    def _make_managed_trade(self, signal: Signal, binance_opened: bool) -> ManagedTrade:
        engine = TradeEngine(risk_usd=self.risk_usd)
        opened = engine.maybe_open_trade(signal)
        if not opened:
            raise RuntimeError("Failed to open paper trade")
        timeframe_minutes = self._timeframe_minutes(signal.timeframe)
        signal_type = self._signal_type_from_reason(signal.reason)
        effective_wait_minutes = self._effective_wait_minutes(timeframe_minutes, signal_type, signal.reason)
        return ManagedTrade(
            signal=signal,
            engine=engine,
            start_time=time.time(),
            timeframe_minutes=timeframe_minutes,
            max_wait_seconds=effective_wait_minutes * 60,
            last_seen_close_ms=signal.signal_time_ms,
            best_r=0.0,
            original_risk=max(abs(signal.entry - signal.stop_loss), 1e-9),
            bars_seen=0,
            consecutive_adverse_bars=0,
            moved_to_break_even=False,
            trailing_stop_active=False,
            consecutive_fetch_errors=0,
            last_known_candles=None,
            binance_opened=binance_opened,
        )

    def _make_exit(self, managed: ManagedTrade, latest, reason_prefix: str) -> ClosedTrade:
        active = managed.engine.active_trade
        if active is None:
            raise RuntimeError("Active trade missing while building exit")
        pnl_per_unit = latest.close - active.entry if active.side == "LONG" else active.entry - latest.close
        gross_r = pnl_per_unit / managed.original_risk
        cost_r = self.cost_model.trade_cost_r(active.entry, managed.signal.stop_loss)
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

    def _close_binance_trade(self, closed: ClosedTrade) -> bool:
        if not self.executor.enabled:
            return False
        binance_closed = False
        try:
            has_position = self.executor.has_open_position(closed.symbol)
            if has_position:
                close_result = self.executor.close_trade(symbol=closed.symbol, side=closed.side, reason=closed.reason)
                binance_closed = close_result.get("executed", False)
                print(json.dumps({"type": "BINANCE_ORDER", "time": self._now_iso(), "action": "CLOSE", "symbol": closed.symbol, "side": closed.side, "result": close_result}))
                if not binance_closed or self.executor.has_open_position(closed.symbol):
                    time.sleep(1)
                    retry = self.executor.close_trade(closed.symbol, closed.side, "RETRY_CLOSE")
                    binance_closed = retry.get("executed", False)
                    print(json.dumps({"type": "BINANCE_ORDER", "time": self._now_iso(), "action": "RETRY_CLOSE", "symbol": closed.symbol, "result": retry}))
        except Exception as exc:
            print(json.dumps({"type": "BINANCE_ORDER", "time": self._now_iso(), "action": "CLOSE_FAILED", "symbol": closed.symbol, "error": str(exc)}))
        return binance_closed

    def _finalize_closed_trade(self, managed: ManagedTrade, closed: ClosedTrade, cycle: int, binance_opened: bool, binance_closed: bool) -> None:
        trade_key = self._trade_result_key(closed)
        if trade_key in self._emitted_trade_result_keys:
            print(json.dumps({"type": "TRADE_RESULT_DUPLICATE_SKIPPED", "time": self._now_iso(), "cycle": cycle, "symbol": closed.symbol, "trade_key": trade_key}))
            return
        self._emitted_trade_result_keys.add(trade_key)
        trade_meta = self._build_trade_meta(managed, closed)
        self._record_trade(closed)
        policy_result = self.policy_engine.record_trade(signal_type=str(trade_meta.get("signal_type") or ""), side=closed.side, trade=closed)
        self._apply_feedback(closed)
        self._apply_loss_guard(closed, cycle)
        self._apply_performance_guard(cycle)
        if policy_result.get("paused"):
            stats = policy_result["stats"]
            print(json.dumps({"type": "SETUP_SIDE_COOLDOWN_APPLIED", "time": self._now_iso(), "cycle": cycle, "slice_key": policy_result["slice_key"], "cooldown_cycles": self.policy_engine.slice_cooldowns.get(policy_result["slice_key"], 0), "stats": {"trades": stats.trades, "wins": stats.wins, "losses": stats.losses, "win_rate": round(stats.win_rate, 4), "expectancy_r": round(stats.expectancy_r, 6)}}))
        cooldown_cycles = self._post_close_cooldown_cycles(closed, trade_meta)
        if cooldown_cycles > 0:
            self.symbol_cooldowns[closed.symbol] = max(int(self.symbol_cooldowns.get(closed.symbol, 0)), cooldown_cycles)
            print(json.dumps({"type": "SYMBOL_REENTRY_COOLDOWN_APPLIED", "time": self._now_iso(), "cycle": cycle, "symbol": closed.symbol, "cooldown_cycles": self.symbol_cooldowns[closed.symbol], "trade_key": trade_key, "exit_type": trade_meta.get("exit_type"), "hold_minutes": trade_meta.get("hold_minutes")}))
        print(json.dumps({"type": "TRADE_RESULT", "time": self._now_iso(), "cycle": cycle, "trade": asdict(closed), "trade_key": trade_key, "trade_meta": trade_meta, "summary": self._summary(), "binance_executed": binance_opened, "binance_closed": binance_closed}))

    def _update_managed_trade(self, managed: ManagedTrade) -> Optional[ClosedTrade]:
        if time.time() - managed.start_time >= managed.max_wait_seconds and managed.last_known_candles:
            return self._make_exit(managed, managed.last_known_candles[-1], "TIMEOUT_EXIT")
        try:
            candles = self.client.fetch_klines(symbol=managed.signal.symbol, interval=managed.signal.timeframe, limit=10)
            managed.last_known_candles = candles
            managed.consecutive_fetch_errors = 0
        except Exception as exc:
            managed.consecutive_fetch_errors += 1
            print(json.dumps({"type": "TRADE_MONITOR_FETCH_ERROR", "time": self._now_iso(), "symbol": managed.signal.symbol, "error": str(exc), "consecutive_errors": managed.consecutive_fetch_errors}))
            if managed.consecutive_fetch_errors >= 5 and managed.last_known_candles:
                return self._make_exit(managed, managed.last_known_candles[-1], "NETWORK_ERROR_EXIT")
            return None
        closed_candles = [c for c in candles if c.close_time_ms < int(time.time() * 1000)]
        if not closed_candles:
            return None
        latest = closed_candles[-1]
        if latest.close_time_ms <= managed.last_seen_close_ms:
            return None
        managed.last_seen_close_ms = latest.close_time_ms
        active = managed.engine.active_trade
        if active is None:
            raise RuntimeError("Active trade missing while updating managed trade")
        managed.bars_seen += 1
        now_r = self._current_r_multiple(active.side, active.entry, managed.signal.stop_loss, latest.close)
        favorable_price = latest.high if active.side == "LONG" else latest.low
        peak_r = self._current_r_multiple(active.side, active.entry, managed.signal.stop_loss, favorable_price)
        managed.best_r = max(managed.best_r, peak_r)
        managed.consecutive_adverse_bars = managed.consecutive_adverse_bars + 1 if now_r < 0 else 0
        closed = managed.engine.on_candle(latest)
        if closed:
            return closed
        active = managed.engine.active_trade
        if active is None:
            raise RuntimeError("Active trade missing after candle update")
        if self.enable_trailing_stop and managed.best_r >= self.trail_trigger_r:
            trail_sl_r = managed.best_r * self.trail_keep_pct
            new_sl = active.entry + (trail_sl_r * managed.original_risk) if active.side == "LONG" else active.entry - (trail_sl_r * managed.original_risk)
            if (active.side == "LONG" and new_sl > active.stop_loss) or (active.side == "SHORT" and new_sl < active.stop_loss):
                active.stop_loss = new_sl
            action = "TRAILING_STOP_UPDATED" if managed.trailing_stop_active else "TRAILING_STOP_ACTIVATED"
            managed.trailing_stop_active = True
            payload = {"type": "RISK_MANAGER_UPDATE", "time": self._now_iso(), "symbol": active.symbol, "timeframe": active.timeframe, "action": action, "updated_stop_loss": round(active.stop_loss, 6), "best_r": round(managed.best_r, 4)}
            if action == "TRAILING_STOP_ACTIVATED":
                payload["trail_keep_pct"] = self.trail_keep_pct
            print(json.dumps(payload))
        elif self.enable_break_even and (not managed.moved_to_break_even) and managed.best_r >= self.break_even_trigger_r:
            risk = max(abs(active.entry - active.stop_loss), 1e-9)
            be_stop = self._break_even_stop_price(active.side, active.entry, risk, self.break_even_offset_r)
            if (active.side == "LONG" and be_stop > active.stop_loss) or (active.side == "SHORT" and be_stop < active.stop_loss):
                active.stop_loss = be_stop
                managed.moved_to_break_even = True
            if managed.moved_to_break_even:
                print(json.dumps({"type": "RISK_MANAGER_UPDATE", "time": self._now_iso(), "symbol": active.symbol, "timeframe": active.timeframe, "action": "STOP_TO_BREAKEVEN", "updated_stop_loss": round(active.stop_loss, 6), "best_r": round(managed.best_r, 6)}))
        worst_price = latest.low if active.side == "LONG" else latest.high
        adverse_r = self._current_r_multiple(active.side, active.entry, managed.signal.stop_loss, worst_price)
        if adverse_r <= (-1.0 * self.max_adverse_r_cut):
            return self._make_exit(managed, latest, "ADVERSE_CUT")
        if managed.consecutive_adverse_bars >= self.momentum_reversal_bars and now_r <= self.momentum_reversal_r:
            print(json.dumps({"type": "RISK_MANAGER_UPDATE", "time": self._now_iso(), "symbol": active.symbol, "timeframe": active.timeframe, "action": "MOMENTUM_REVERSAL_EXIT", "now_r": round(now_r, 4), "consecutive_adverse_bars": managed.consecutive_adverse_bars}))
            return self._make_exit(managed, latest, "MOMENTUM_REVERSAL")
        if managed.bars_seen >= self.max_stagnation_bars and managed.best_r < self.min_progress_r_for_stagnation:
            return self._make_exit(managed, latest, "STAGNATION_EXIT")
        signal_type = self._signal_type_from_reason(managed.signal.reason)
        max_wait_candles = self._max_wait_candles_for_signal(signal_type, managed.signal.reason)
        if managed.bars_seen >= max_wait_candles:
            if self._should_extend_breakdown_timeout(managed, latest, now_r):
                return None
            return self._make_exit(managed, latest, "CANDLE_TIMEOUT")
        return None

    def _update_open_trades(self, cycle: int) -> None:
        for key, managed in list(self.open_trades.items()):
            closed = self._update_managed_trade(managed)
            if closed is None:
                continue
            binance_closed = self._close_binance_trade(closed)
            del self.open_trades[key]
            self._finalize_closed_trade(managed, closed, cycle, managed.binance_opened, binance_closed)

    def _close_all_open_trades_on_exit(self, cycle: int) -> None:
        if not self.open_trades:
            return
        print(json.dumps({"type": "GRACEFUL_SHUTDOWN", "time": self._now_iso(), "cycle": cycle, "open_trades_count": len(self.open_trades), "symbols": [m.signal.symbol for m in self.open_trades.values()]}))
        for key, managed in list(self.open_trades.items()):
            if not managed.binance_opened:
                del self.open_trades[key]
                continue
            try:
                close_result = self.executor.close_trade(symbol=managed.signal.symbol, side=managed.signal.side, reason="GRACEFUL_SHUTDOWN")
                self._emit_event({"type": "BINANCE_ORDER", "time": self._now_iso(), "action": "SHUTDOWN_CLOSE", "symbol": managed.signal.symbol, "side": managed.signal.side, "result": close_result}, persist=True)
            except Exception as exc:
                self._emit_event({"type": "BINANCE_ORDER", "time": self._now_iso(), "action": "SHUTDOWN_CLOSE_FAILED", "symbol": managed.signal.symbol, "error": str(exc)}, persist=True)
            del self.open_trades[key]
