#!/usr/bin/env python3
"""
Live Trade Test — scans Binance Futures for signals, executes paper trades,
waits for candle closes, verifies actual market outcomes, and self-tunes
if results are poor.

Usage:
    python3 run_live_trade_test.py --trades 20 --config config.json
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from src.binance_futures_rest import BinanceFuturesRestClient
from src.config import load_config
from src.indicators import ema
from src.ml_pipeline import MLWalkForwardOptimizer
from src.models import Candle, ClosedTrade, Signal
from src.strategy import StrategyEngine
from src.trade_engine import TradeEngine


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def current_r_multiple(side: str, entry: float, stop_loss: float, price: float) -> float:
    risk = max(abs(entry - stop_loss), 1e-9)
    pnl = price - entry if side == "LONG" else entry - price
    return pnl / risk


class LiveTradeTest:
    def __init__(
        self,
        config: Dict,
        target_trades: int = 20,
        symbols_override: Optional[List[str]] = None,
        timeframes_override: Optional[List[str]] = None,
        poll_seconds_override: Optional[int] = None,
        max_wait_minutes_override: Optional[int] = None,
        output_path: str = "data/live_trade_test_results.json",
    ):
        self.config = config
        self.target_trades = target_trades
        self.output_path = Path(output_path)

        self.client = BinanceFuturesRestClient()
        self.strategy_payload = copy.deepcopy(config["strategy"])
        self.base_strategy = StrategyEngine.from_dict(copy.deepcopy(config["strategy"]))

        acct = config["account"]
        self.risk_usd = float(acct["starting_balance_usd"]) * float(acct["risk_per_trade_pct"])

        execution_cfg = config.get("execution", {})
        self.cost_model = MLWalkForwardOptimizer(
            risk_usd=self.risk_usd,
            fee_bps_per_side=float(execution_cfg.get("fee_bps_per_side", 0.0)),
            slippage_bps_per_side=float(execution_cfg.get("slippage_bps_per_side", 0.0)),
        )

        live_cfg = config.get("live_loop", {})
        self.symbols = live_cfg.get("symbols", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"])
        self.timeframes = live_cfg.get("timeframes", ["5m", "15m"])
        self.lookback = int(live_cfg.get("lookback_candles", 260))
        self.poll_seconds = int(live_cfg.get("poll_seconds", 12))
        self.max_wait_minutes = int(live_cfg.get("max_wait_minutes_per_trade", 4))
        if symbols_override:
            self.symbols = symbols_override
        if timeframes_override:
            self.timeframes = timeframes_override
        if poll_seconds_override is not None:
            self.poll_seconds = int(poll_seconds_override)
        if max_wait_minutes_override is not None:
            self.max_wait_minutes = int(max_wait_minutes_override)

        # Execution thresholds — start with candidate-level (relaxed) to collect data
        self.min_confidence = 0.68
        self.min_expectancy_r = -0.02
        self.min_rr = 0.35
        self.min_trend_strength = 0.0012

        # Break-even settings
        self.enable_break_even = bool(live_cfg.get("enable_break_even", True))
        self.break_even_trigger_r = float(live_cfg.get("break_even_trigger_r", 0.5))
        self.break_even_offset_r = float(live_cfg.get("break_even_offset_r", 0.02))
        self.max_adverse_r_cut = float(live_cfg.get("max_adverse_r_cut", 0.9))
        self.max_stagnation_bars = int(live_cfg.get("max_stagnation_bars", 8))
        self.min_progress_r = float(live_cfg.get("min_progress_r_for_stagnation", 0.15))

        # Results tracking
        self.all_trades: List[Dict] = []
        self.tuning_rounds = 0

    def _scan_signals(self) -> List[Dict]:
        """Scan all symbols/timeframes and return scored candidates."""
        candidates = []
        for symbol in self.symbols:
            try:
                market = self.client.fetch_market_context(symbol)
                for tf in self.timeframes:
                    candles = self.client.fetch_klines(symbol=symbol, interval=tf, limit=self.lookback)
                    if len(candles) < max(60, int(self.strategy_payload["ema_slow"])):
                        continue

                    strategy_data = copy.deepcopy(self.strategy_payload)
                    strategy_data["min_confidence"] = self.min_confidence
                    strategy = StrategyEngine.from_dict(strategy_data)

                    signal = strategy.evaluate(symbol, tf, candles, market)
                    if signal is None:
                        continue

                    rr = abs(signal.take_profit - signal.entry) / max(abs(signal.entry - signal.stop_loss), 1e-9)
                    if rr < self.min_rr:
                        continue

                    closes = [c.close for c in candles]
                    ema_fast_v = ema(closes, int(strategy_data["ema_fast"]))
                    ema_slow_v = ema(closes, int(strategy_data["ema_slow"]))
                    trend_strength = abs(ema_fast_v - ema_slow_v) / max(signal.entry, 1e-9)
                    if trend_strength < self.min_trend_strength:
                        continue

                    cost_r = self.cost_model.trade_cost_r(signal.entry, signal.stop_loss)
                    expectancy_r = (signal.confidence * rr) - ((1.0 - signal.confidence) * 1.0) - cost_r
                    if expectancy_r < self.min_expectancy_r:
                        continue

                    score = (signal.confidence * 0.65) + (trend_strength * 100.0 * 0.25) + ((rr - cost_r) * 0.10)

                    candidates.append({
                        "signal": signal,
                        "rr": rr,
                        "trend_strength": trend_strength,
                        "cost_r": cost_r,
                        "expectancy_r": expectancy_r,
                        "score": score,
                    })
            except Exception as exc:
                print(f"  [!] Error fetching {symbol}: {exc}")

        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates

    def _wait_for_trade_close(self, signal: Signal) -> ClosedTrade:
        """Open a paper trade and wait for TP/SL hit or timeout."""
        engine = TradeEngine(risk_usd=self.risk_usd)
        engine.maybe_open_trade(signal)

        start = time.time()
        max_wait_sec = self.max_wait_minutes * 60
        last_seen_ms = signal.signal_time_ms
        best_r = 0.0
        bars_seen = 0
        moved_to_be = False

        while True:
            candles = self.client.fetch_klines(symbol=signal.symbol, interval=signal.timeframe, limit=10)
            now_ms = int(time.time() * 1000)
            closed_candles = [c for c in candles if c.close_time_ms < now_ms]

            if closed_candles:
                latest = closed_candles[-1]
                if latest.close_time_ms > last_seen_ms:
                    last_seen_ms = latest.close_time_ms
                    active = engine.active_trade
                    if active is None:
                        raise RuntimeError("Active trade missing")

                    bars_seen += 1
                    favorable = latest.high if active.side == "LONG" else latest.low
                    peak_r = current_r_multiple(active.side, active.entry, active.stop_loss, favorable)
                    best_r = max(best_r, peak_r)

                    # Check TP/SL first
                    closed = engine.on_candle(latest)
                    if closed:
                        return closed

                    active = engine.active_trade
                    if active is None:
                        raise RuntimeError("Active trade missing after candle")

                    # Apply break-even for next candle
                    if self.enable_break_even and not moved_to_be and best_r >= self.break_even_trigger_r:
                        risk = max(abs(active.entry - active.stop_loss), 1e-9)
                        if active.side == "LONG":
                            be_stop = active.entry + (self.break_even_offset_r * risk)
                            if be_stop > active.stop_loss:
                                active.stop_loss = be_stop
                                moved_to_be = True
                        else:
                            be_stop = active.entry + (self.break_even_offset_r * risk)
                            if be_stop < active.stop_loss:
                                active.stop_loss = be_stop
                                moved_to_be = True
                        if moved_to_be:
                            print(f"      [BE] Stop moved to break-even: {active.stop_loss:.6f}")

                    # Adverse cut
                    worst = latest.low if active.side == "LONG" else latest.high
                    adverse_r = current_r_multiple(active.side, active.entry, active.stop_loss, worst)
                    if adverse_r <= -self.max_adverse_r_cut:
                        risk = max(abs(active.entry - active.stop_loss), 1e-9)
                        pnl = latest.close - active.entry if active.side == "LONG" else active.entry - latest.close
                        net_r = (pnl / risk) - self.cost_model.trade_cost_r(active.entry, active.stop_loss)
                        return ClosedTrade(
                            symbol=active.symbol, timeframe=active.timeframe, side=active.side,
                            entry=active.entry, take_profit=active.take_profit, stop_loss=active.stop_loss,
                            exit_price=latest.close, result="WIN" if net_r > 0 else "LOSS",
                            opened_at_ms=active.opened_at_ms, closed_at_ms=latest.close_time_ms,
                            pnl_r=net_r, pnl_usd=net_r * self.risk_usd, reason="ADVERSE_CUT",
                        )

                    # Stagnation exit
                    if bars_seen >= self.max_stagnation_bars and best_r < self.min_progress_r:
                        risk = max(abs(active.entry - active.stop_loss), 1e-9)
                        pnl = latest.close - active.entry if active.side == "LONG" else active.entry - latest.close
                        net_r = (pnl / risk) - self.cost_model.trade_cost_r(active.entry, active.stop_loss)
                        return ClosedTrade(
                            symbol=active.symbol, timeframe=active.timeframe, side=active.side,
                            entry=active.entry, take_profit=active.take_profit, stop_loss=active.stop_loss,
                            exit_price=latest.close, result="WIN" if net_r > 0 else "LOSS",
                            opened_at_ms=active.opened_at_ms, closed_at_ms=latest.close_time_ms,
                            pnl_r=net_r, pnl_usd=net_r * self.risk_usd, reason="STAGNATION_EXIT",
                        )

                    elapsed = time.time() - start
                    now_r = current_r_multiple(active.side, active.entry, active.stop_loss, latest.close)
                    print(f"      Bar {bars_seen}: now_r={now_r:.4f}, best_r={best_r:.4f}, "
                          f"elapsed={elapsed:.0f}s/{max_wait_sec}s")

            # Timeout
            if time.time() - start >= max_wait_sec:
                latest = closed_candles[-1] if closed_candles else candles[-1]
                active = engine.active_trade
                if active is None:
                    raise RuntimeError("Active trade missing at timeout")
                risk = max(abs(active.entry - active.stop_loss), 1e-9)
                pnl = latest.close - active.entry if active.side == "LONG" else active.entry - latest.close
                net_r = (pnl / risk) - self.cost_model.trade_cost_r(active.entry, active.stop_loss)
                return ClosedTrade(
                    symbol=active.symbol, timeframe=active.timeframe, side=active.side,
                    entry=active.entry, take_profit=active.take_profit, stop_loss=active.stop_loss,
                    exit_price=latest.close, result="WIN" if net_r > 0 else "LOSS",
                    opened_at_ms=active.opened_at_ms, closed_at_ms=latest.close_time_ms,
                    pnl_r=net_r, pnl_usd=net_r * self.risk_usd, reason="TIMEOUT_EXIT",
                )

            time.sleep(self.poll_seconds)

    def _verify_trade_on_market(self, trade: ClosedTrade) -> Dict:
        """After a trade closes, fetch fresh candle data to independently verify."""
        try:
            candles = self.client.fetch_klines(symbol=trade.symbol, interval=trade.timeframe, limit=20)
            # Find candles overlapping the trade period
            trade_candles = [c for c in candles
                            if c.open_time_ms >= trade.opened_at_ms - 60000
                            and c.close_time_ms <= trade.closed_at_ms + 60000]

            if not trade_candles:
                trade_candles = candles[-5:]

            highs = [c.high for c in trade_candles]
            lows = [c.low for c in trade_candles]
            max_high = max(highs) if highs else trade.entry
            min_low = min(lows) if lows else trade.entry

            if trade.side == "LONG":
                actual_best_r = current_r_multiple("LONG", trade.entry, trade.stop_loss, max_high)
                actual_worst_r = current_r_multiple("LONG", trade.entry, trade.stop_loss, min_low)
                would_hit_tp = max_high >= trade.take_profit
                would_hit_sl = min_low <= trade.stop_loss
            else:
                actual_best_r = current_r_multiple("SHORT", trade.entry, trade.stop_loss, min_low)
                actual_worst_r = current_r_multiple("SHORT", trade.entry, trade.stop_loss, max_high)
                would_hit_tp = min_low <= trade.take_profit
                would_hit_sl = max_high >= trade.stop_loss

            return {
                "verified": True,
                "candles_checked": len(trade_candles),
                "market_high": max_high,
                "market_low": min_low,
                "actual_best_r": round(actual_best_r, 4),
                "actual_worst_r": round(actual_worst_r, 4),
                "would_hit_tp": would_hit_tp,
                "would_hit_sl": would_hit_sl,
                "match": (would_hit_tp and trade.result == "WIN") or (would_hit_sl and trade.result == "LOSS") or "TIMEOUT" in trade.reason or "STAGNATION" in trade.reason or "ADVERSE" in trade.reason,
            }
        except Exception as exc:
            return {"verified": False, "error": str(exc)}

    def _analyze_results(self) -> Dict:
        """Compute aggregate statistics from all completed trades."""
        trades = self.all_trades
        n = len(trades)
        if n == 0:
            return {"trades": 0, "win_rate": 0, "expectancy_r": 0, "needs_tuning": True}

        wins = sum(1 for t in trades if t["result"] == "WIN")
        losses = n - wins
        win_rate = wins / n
        total_r = sum(t["pnl_r"] for t in trades)
        expectancy_r = total_r / n
        total_usd = sum(t["pnl_usd"] for t in trades)

        # Per-exit-reason breakdown
        reasons = {}
        for t in trades:
            base_reason = t["reason"].split("|")[0].strip() if "|" in t["reason"] else ("TP/SL" if t["result"] in ("WIN", "LOSS") else t["reason"])
            if base_reason not in reasons:
                reasons[base_reason] = {"count": 0, "wins": 0, "total_r": 0.0}
            reasons[base_reason]["count"] += 1
            if t["result"] == "WIN":
                reasons[base_reason]["wins"] += 1
            reasons[base_reason]["total_r"] += t["pnl_r"]

        # Per-symbol breakdown
        symbols = {}
        for t in trades:
            s = t["symbol"]
            if s not in symbols:
                symbols[s] = {"count": 0, "wins": 0, "total_r": 0.0}
            symbols[s]["count"] += 1
            if t["result"] == "WIN":
                symbols[s]["wins"] += 1
            symbols[s]["total_r"] += t["pnl_r"]

        # Verification match rate
        verified = [t for t in trades if t.get("verification", {}).get("verified")]
        match_rate = sum(1 for t in verified if t["verification"].get("match")) / max(len(verified), 1)

        needs_tuning = win_rate < 0.50 or expectancy_r < 0.0

        return {
            "trades": n,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 4),
            "expectancy_r": round(expectancy_r, 4),
            "total_r": round(total_r, 4),
            "total_usd": round(total_usd, 4),
            "verification_match_rate": round(match_rate, 4),
            "by_reason": reasons,
            "by_symbol": symbols,
            "needs_tuning": needs_tuning,
        }

    def _self_tune(self, analysis: Dict) -> None:
        """If results are poor, tighten thresholds to improve quality."""
        self.tuning_rounds += 1
        print(f"\n{'='*60}")
        print(f"  SELF-TUNING ROUND {self.tuning_rounds}")
        print(f"{'='*60}")
        print(f"  Before: confidence>={self.min_confidence:.3f}, "
              f"expectancy_r>={self.min_expectancy_r:.3f}, "
              f"trend>={self.min_trend_strength:.5f}, "
              f"rr>={self.min_rr:.3f}")

        wr = analysis["win_rate"]
        exp_r = analysis["expectancy_r"]

        if wr < 0.45:
            # Heavy tightening — too many losses
            self.min_confidence = min(0.90, self.min_confidence + 0.04)
            self.min_expectancy_r = min(0.15, self.min_expectancy_r + 0.03)
            self.min_trend_strength = min(0.004, self.min_trend_strength + 0.0003)
            self.min_rr = min(0.8, self.min_rr + 0.05)
        elif wr < 0.50 or exp_r < 0.0:
            # Moderate tightening
            self.min_confidence = min(0.88, self.min_confidence + 0.02)
            self.min_expectancy_r = min(0.12, self.min_expectancy_r + 0.02)
            self.min_trend_strength = min(0.003, self.min_trend_strength + 0.0002)
            self.min_rr = min(0.7, self.min_rr + 0.03)

        # Check which symbols are underperforming and drop them
        by_symbol = analysis.get("by_symbol", {})
        for sym, stats in by_symbol.items():
            if stats["count"] >= 3:
                sym_wr = stats["wins"] / stats["count"]
                sym_exp = stats["total_r"] / stats["count"]
                if sym_wr < 0.35 or sym_exp < -0.15:
                    if sym in self.symbols and len(self.symbols) > 3:
                        self.symbols.remove(sym)
                        print(f"  [DROP] Removed {sym} (WR={sym_wr:.2f}, exp_R={sym_exp:.3f})")

        # Check which exit reasons dominate losses
        by_reason = analysis.get("by_reason", {})
        for reason, stats in by_reason.items():
            if stats["count"] >= 3:
                r_wr = stats["wins"] / stats["count"]
                if "STAGNATION" in reason and r_wr < 0.4:
                    self.max_stagnation_bars = max(4, self.max_stagnation_bars - 1)
                    print(f"  [TUNE] Reduced max_stagnation_bars to {self.max_stagnation_bars}")
                if "TIMEOUT" in reason and stats["total_r"] / stats["count"] < 0:
                    self.max_wait_minutes = max(2, self.max_wait_minutes - 1)
                    print(f"  [TUNE] Reduced max_wait_minutes to {self.max_wait_minutes}")

        print(f"  After: confidence>={self.min_confidence:.3f}, "
              f"expectancy_r>={self.min_expectancy_r:.3f}, "
              f"trend>={self.min_trend_strength:.5f}, "
              f"rr>={self.min_rr:.3f}")
        print(f"  Active symbols: {self.symbols}")
        print(f"{'='*60}\n")

    def run(self) -> Dict:
        print(f"\n{'#'*60}")
        print(f"  LIVE TRADE TEST — Target: {self.target_trades} trades")
        print(f"  Symbols: {self.symbols}")
        print(f"  Timeframes: {self.timeframes}")
        print(f"  Started: {now_iso()}")
        print(f"{'#'*60}\n")
        sys.stdout.flush()

        scan_cycle = 0
        max_scan_cycles = self.target_trades * 50  # Safety limit
        batch_size = 5  # Analyze and tune every N trades

        while len(self.all_trades) < self.target_trades and scan_cycle < max_scan_cycles:
            scan_cycle += 1
            trade_num = len(self.all_trades) + 1

            print(f"\n--- Scan Cycle {scan_cycle} | Trade {trade_num}/{self.target_trades} | {now_iso()} ---")
            sys.stdout.flush()

            # 1. Scan for signals
            candidates = self._scan_signals()
            print(f"  Found {len(candidates)} candidates")

            if not candidates:
                print(f"  No signals. Waiting {self.poll_seconds}s...")
                sys.stdout.flush()
                time.sleep(self.poll_seconds)
                continue

            # Show top candidates
            for i, c in enumerate(candidates[:5]):
                sig = c["signal"]
                print(f"  #{i+1} {sig.symbol} {sig.timeframe} {sig.side} | "
                      f"conf={sig.confidence:.3f} RR={c['rr']:.2f} "
                      f"exp_R={c['expectancy_r']:.3f} score={c['score']:.3f}")

            # 2. Execute the best candidate
            best = candidates[0]
            sig = best["signal"]
            print(f"\n  >>> EXECUTING: {sig.symbol} {sig.timeframe} {sig.side} @ {sig.entry:.6f}")
            print(f"      TP={sig.take_profit:.6f} SL={sig.stop_loss:.6f} conf={sig.confidence:.3f}")
            sys.stdout.flush()

            try:
                closed = self._wait_for_trade_close(sig)
            except Exception as exc:
                print(f"  [!] Trade execution error: {exc}")
                sys.stdout.flush()
                time.sleep(self.poll_seconds)
                continue

            # 3. Verify against actual market data
            verification = self._verify_trade_on_market(closed)

            result_emoji = "WIN" if closed.result == "WIN" else "LOSS"
            trade_record = {
                "trade_num": trade_num,
                "time": now_iso(),
                "symbol": closed.symbol,
                "timeframe": closed.timeframe,
                "side": closed.side,
                "entry": closed.entry,
                "take_profit": closed.take_profit,
                "stop_loss": closed.stop_loss,
                "exit_price": closed.exit_price,
                "result": closed.result,
                "pnl_r": round(closed.pnl_r, 4),
                "pnl_usd": round(closed.pnl_usd, 4),
                "reason": closed.reason,
                "confidence": round(sig.confidence, 4),
                "rr": round(best["rr"], 4),
                "expectancy_r": round(best["expectancy_r"], 4),
                "score": round(best["score"], 4),
                "verification": verification,
            }
            self.all_trades.append(trade_record)

            print(f"\n  <<< RESULT: {result_emoji} | pnl_R={closed.pnl_r:+.4f} | "
                  f"exit={closed.exit_price:.6f} | {closed.reason}")
            if verification.get("verified"):
                print(f"      Verification: best_R={verification['actual_best_r']}, "
                      f"worst_R={verification['actual_worst_r']}, "
                      f"match={verification['match']}")
            sys.stdout.flush()

            # 4. Running stats
            wins = sum(1 for t in self.all_trades if t["result"] == "WIN")
            total = len(self.all_trades)
            wr = wins / total
            avg_r = sum(t["pnl_r"] for t in self.all_trades) / total
            print(f"\n  Running: {wins}W/{total-wins}L ({wr:.1%} WR) | avg_R={avg_r:+.4f} | "
                  f"total_R={sum(t['pnl_r'] for t in self.all_trades):+.4f}")
            sys.stdout.flush()

            # 5. Self-tune check every batch_size trades
            if total % batch_size == 0 and total > 0:
                analysis = self._analyze_results()
                if analysis["needs_tuning"]:
                    self._self_tune(analysis)
                else:
                    print(f"\n  [OK] Performance acceptable (WR={analysis['win_rate']:.1%}, "
                          f"exp_R={analysis['expectancy_r']:+.4f}) — no tuning needed")
                sys.stdout.flush()

        # Final analysis
        print(f"\n\n{'#'*60}")
        print(f"  FINAL RESULTS — {len(self.all_trades)} trades completed")
        print(f"{'#'*60}\n")

        analysis = self._analyze_results()
        print(f"  Win Rate:      {analysis['win_rate']:.1%} ({analysis['wins']}W / {analysis['losses']}L)")
        print(f"  Expectancy:    {analysis['expectancy_r']:+.4f} R per trade")
        print(f"  Total P&L:     {analysis['total_r']:+.4f} R ({analysis['total_usd']:+.4f} USD)")
        print(f"  Verification:  {analysis['verification_match_rate']:.1%} match rate")
        print(f"  Tuning rounds: {self.tuning_rounds}")

        print(f"\n  By Exit Reason:")
        for reason, stats in analysis.get("by_reason", {}).items():
            wr = stats["wins"] / max(stats["count"], 1)
            avg = stats["total_r"] / max(stats["count"], 1)
            print(f"    {reason:20s}: {stats['count']} trades, {wr:.0%} WR, {avg:+.3f} avg R")

        print(f"\n  By Symbol:")
        for sym, stats in analysis.get("by_symbol", {}).items():
            wr = stats["wins"] / max(stats["count"], 1)
            avg = stats["total_r"] / max(stats["count"], 1)
            print(f"    {sym:12s}: {stats['count']} trades, {wr:.0%} WR, {avg:+.3f} avg R")

        print(f"\n  Trade Log:")
        for t in self.all_trades:
            v = "OK" if t.get("verification", {}).get("match") else "??"
            print(f"    #{t['trade_num']:3d} {t['symbol']:10s} {t['timeframe']:3s} {t['side']:5s} "
                  f"| {t['result']:4s} {t['pnl_r']:+.4f}R | conf={t['confidence']:.3f} "
                  f"| {t['reason'][:20]:20s} | [{v}]")

        sys.stdout.flush()

        # Save results to file
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", encoding="utf-8") as f:
            json.dump({
                "completed_at": now_iso(),
                "analysis": analysis,
                "trades": self.all_trades,
                "tuning_rounds": self.tuning_rounds,
                "final_thresholds": {
                    "min_confidence": self.min_confidence,
                    "min_expectancy_r": self.min_expectancy_r,
                    "min_trend_strength": self.min_trend_strength,
                    "min_rr": self.min_rr,
                    "symbols": self.symbols,
                },
            }, f, indent=2)
        print(f"\n  Results saved to {self.output_path}")

        return analysis


def main():
    parser = argparse.ArgumentParser(description="Live trade test with self-tuning")
    parser.add_argument("--trades", type=int, default=20, help="Number of trades to complete")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--symbols", default="", help="Comma-separated symbol override")
    parser.add_argument("--timeframes", default="", help="Comma-separated timeframe override")
    parser.add_argument("--poll-seconds", type=int, default=None, help="Override scan poll interval")
    parser.add_argument("--max-wait-minutes", type=int, default=None, help="Override max wait per trade")
    parser.add_argument("--output", default="data/live_trade_test_results.json", help="Path to results JSON")
    args = parser.parse_args()

    config = load_config(args.config)
    symbols_override = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    timeframes_override = [tf.strip() for tf in args.timeframes.split(",") if tf.strip()]
    tester = LiveTradeTest(
        config,
        target_trades=args.trades,
        symbols_override=symbols_override or None,
        timeframes_override=timeframes_override or None,
        poll_seconds_override=args.poll_seconds,
        max_wait_minutes_override=args.max_wait_minutes,
        output_path=args.output,
    )
    tester.run()


if __name__ == "__main__":
    main()
