from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from unittest.mock import patch

from src.binance_futures_rest import BinanceFuturesRestClient
from src.config import load_config
from src.live_adaptive_trader import CandidateSignal, LiveAdaptivePaperTrader
from src.models import ClosedTrade, MarketContext


class _DisabledExecutor:
    enabled = False


class ReplayClient:
    def __init__(
        self,
        candles_by_market: Dict[Tuple[str, str], List],
        market_by_symbol: Dict[str, MarketContext],
        latest_price_by_symbol: Dict[str, float],
    ) -> None:
        self.candles_by_market = candles_by_market
        self.market_by_symbol = market_by_symbol
        self.latest_price_by_symbol = latest_price_by_symbol
        self.current_time_ms: int | None = None

    def set_time(self, current_time_ms: int) -> None:
        self.current_time_ms = int(current_time_ms)

    def _visible_candles(self, symbol: str, interval: str) -> List:
        candles = self.candles_by_market[(symbol, interval)]
        if self.current_time_ms is None:
            return list(candles)
        return [candle for candle in candles if int(candle.close_time_ms) <= self.current_time_ms]

    def _latest_visible_close(self, symbol: str) -> float:
        preferred_intervals = ["5m", "15m", "1m"]
        for interval in preferred_intervals:
            key = (symbol, interval)
            if key not in self.candles_by_market:
                continue
            visible = self._visible_candles(symbol, interval)
            if visible:
                return float(visible[-1].close)
        return float(self.latest_price_by_symbol[symbol])

    def fetch_klines(self, symbol: str, interval: str, limit: int = 300) -> List:
        candles = self._visible_candles(symbol, interval)
        return candles[-limit:] if limit > 0 else list(candles)

    def fetch_market_context(self, symbol: str) -> MarketContext:
        market = self.market_by_symbol[symbol]
        return MarketContext(
            mark_price=self._latest_visible_close(symbol),
            funding_rate=float(market.funding_rate),
            open_interest=float(market.open_interest),
        )

    def fetch_all_premium_index(self) -> Dict[str, MarketContext]:
        return {
            symbol: self.fetch_market_context(symbol)
            for symbol in self.market_by_symbol
        }

    def fetch_all_ticker_prices(self) -> Dict[str, float]:
        return {
            symbol: self._latest_visible_close(symbol)
            for symbol in self.latest_price_by_symbol
        }


def _utc_date_bounds(date_text: str) -> tuple[int, int]:
    day = datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc)
    start_ms = int(day.timestamp() * 1000)
    end_ms = start_ms + 86_400_000
    return start_ms, end_ms


def _utc_window_bounds(date_text: str, start_time_text: str | None, end_time_text: str | None) -> tuple[int, int]:
    day = datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc).date()

    def parse_clock(raw: str | None, fallback: dt_time) -> dt_time:
        if not raw:
            return fallback
        parts = str(raw).strip().split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid UTC clock value: {raw!r}. Expected HH:MM.")
        hour, minute = int(parts[0]), int(parts[1])
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError(f"Invalid UTC clock value: {raw!r}. Expected HH:MM.")
        return dt_time(hour=hour, minute=minute, tzinfo=timezone.utc)

    start_dt = datetime.combine(day, parse_clock(start_time_text, dt_time(0, 0, tzinfo=timezone.utc)))
    end_dt = datetime.combine(day, parse_clock(end_time_text, dt_time(23, 59, tzinfo=timezone.utc)), tzinfo=timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000) + 60_000
    if end_ms <= start_ms:
        raise ValueError("Replay end time must be after start time.")
    return start_ms, end_ms


def _timeframe_minutes(timeframe: str) -> int:
    raw = str(timeframe or "").strip().lower()
    if raw.endswith("m"):
        return max(1, int(raw[:-1] or "1"))
    if raw.endswith("h"):
        return max(1, int(raw[:-1] or "1")) * 60
    if raw.endswith("d"):
        return max(1, int(raw[:-1] or "1")) * 1440
    return 1


def _signal_key(candidate: CandidateSignal) -> str:
    signal = candidate.signal
    return (
        f"{signal.symbol}|{signal.timeframe}|{signal.side}|{signal.signal_time_ms}|"
        f"{round(float(signal.entry), 8)}|{round(float(signal.stop_loss), 8)}|"
        f"{round(float(signal.take_profit), 8)}"
    )


def _signal_type(reason: str) -> str:
    upper = str(reason or "").upper()
    if "PULLBACK" in upper:
        return "PULLBACK"
    if "CROSSOVER" in upper:
        return "CROSSOVER"
    if "BB_REVERSION" in upper:
        return "BB_REVERSION"
    if "SUPERTREND" in upper:
        return "SUPERTREND"
    return "UNKNOWN"


def _regime(reason: str) -> str:
    match = re.search(r"REGIME=([A-Z]+)", str(reason or "").upper())
    return match.group(1) if match else "UNKNOWN"


def _bucket_counts(keys: Iterable[tuple[str, str, str, str]]) -> List[Dict[str, object]]:
    counts = Counter(keys)
    rows = [
        {
            "side": side,
            "timeframe": timeframe,
            "signal_type": signal_type,
            "regime": regime,
            "count": count,
        }
        for (side, timeframe, signal_type, regime), count in counts.items()
    ]
    rows.sort(key=lambda row: (-int(row["count"]), str(row["side"]), str(row["timeframe"])))
    return rows


def _recorded_today_stats(date_text: str, start_ms: int | None = None, end_ms: int | None = None) -> Dict[str, object] | None:
    try:
        from pymongo import MongoClient
    except Exception:
        return None

    client = MongoClient("mongodb://127.0.0.1:27017")
    db = client["crypto_trading_live"]
    docs = list(
        db.trade_history.find(
            {"event_time": {"$regex": f"^{re.escape(date_text)}"}, "synthetic": {"$ne": True}},
            {"_id": 0},
        ).sort("closed_at_ms", 1)
    )
    if start_ms is not None or end_ms is not None:
        filtered_docs = []
        for doc in docs:
            opened_at_ms = int(doc.get("opened_at_ms") or doc.get("closed_at_ms") or 0)
            if start_ms is not None and opened_at_ms < start_ms:
                continue
            if end_ms is not None and opened_at_ms >= end_ms:
                continue
            filtered_docs.append(doc)
        docs = filtered_docs
    if not docs:
        return {
            "count": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "net_r": 0.0,
            "net_usd": 0.0,
            "trades": [],
        }

    trades = []
    for doc in docs:
        meta = doc.get("trade_meta") or {}
        trades.append(
            {
                "event_time": doc.get("event_time"),
                "symbol": doc.get("symbol"),
                "side": doc.get("side"),
                "timeframe": doc.get("timeframe"),
                "result": doc.get("result"),
                "pnl_r": doc.get("pnl_r"),
                "pnl_usd": doc.get("pnl_usd"),
                "signal_type": meta.get("signal_type"),
                "regime": meta.get("regime"),
                "exit_type": meta.get("exit_type"),
                "reason": doc.get("reason"),
            }
        )

    wins = sum(1 for doc in docs if doc.get("result") == "WIN")
    count = len(docs)
    return {
        "count": count,
        "wins": wins,
        "losses": count - wins,
        "win_rate": round(wins / count, 4) if count else 0.0,
        "net_r": round(sum(float(doc.get("pnl_r") or 0.0) for doc in docs), 6),
        "net_usd": round(sum(float(doc.get("pnl_usd") or 0.0) for doc in docs), 6),
        "trades": trades,
    }


def _build_replay_client(
    config: Dict,
    symbols: List[str],
    timeframes: List[str],
    start_ms: int,
    end_ms: int,
) -> ReplayClient:
    rest = BinanceFuturesRestClient(allow_mock_fallback=False, force_mock=False)
    candles_by_market: Dict[Tuple[str, str], List] = {}
    market_by_symbol: Dict[str, MarketContext] = {}
    latest_price_by_symbol: Dict[str, float] = {}
    ema_slow = int(config["strategy"]["ema_slow"])
    lookback = int(config.get("live_loop", {}).get("lookback_candles", 260))

    for symbol in symbols:
        market = rest.fetch_market_context(symbol)
        market_by_symbol[symbol] = market
        latest_price_by_symbol[symbol] = float(market.mark_price)
        for timeframe in timeframes:
            tf_minutes = _timeframe_minutes(timeframe)
            bars_today = math.ceil(max(0, end_ms - start_ms) / (tf_minutes * 60_000))
            limit = max(lookback, bars_today + ema_slow + 20)
            candles_by_market[(symbol, timeframe)] = rest.fetch_klines(symbol=symbol, interval=timeframe, limit=limit)

    return ReplayClient(candles_by_market, market_by_symbol, latest_price_by_symbol)


def _event_times(
    replay_client: ReplayClient,
    symbols: List[str],
    timeframes: List[str],
    start_ms: int,
    end_ms: int,
) -> List[int]:
    event_ms: set[int] = set()
    for symbol in symbols:
        for timeframe in timeframes:
            for candle in replay_client.fetch_klines(symbol, timeframe, limit=100000):
                close_ms = int(candle.close_time_ms)
                if start_ms <= close_ms < end_ms:
                    event_ms.add(close_ms)
    return sorted(event_ms)
def run_replay(
    config: Dict,
    replay_date: str,
    start_time_text: str | None = None,
    end_time_text: str | None = None,
) -> Dict[str, object]:
    symbols = [str(symbol).upper() for symbol in (config.get("live_loop", {}).get("symbols") or [])]
    timeframes = [str(timeframe) for timeframe in (config.get("live_loop", {}).get("timeframes") or ["5m", "15m"])]
    start_ms, end_ms = _utc_window_bounds(replay_date, start_time_text, end_time_text)
    replay_client = _build_replay_client(config, symbols, timeframes, start_ms, end_ms)
    event_times = _event_times(replay_client, symbols, timeframes, start_ms, end_ms)

    with patch("src.live_adaptive_trader.BinanceExecutor.from_env", return_value=_DisabledExecutor()):
        trader = LiveAdaptivePaperTrader(config)
    trader.client = replay_client
    trader._current_utc_day = lambda: replay_date  # type: ignore[method-assign]

    cycle = 0
    raw_seen: set[str] = set()
    qualified_seen: set[str] = set()
    opened_seen: set[str] = set()
    raw_keys: List[tuple[str, str, str, str]] = []
    qualified_keys: List[tuple[str, str, str, str]] = []
    opened_keys: List[tuple[str, str, str, str]] = []
    opened_trades: List[Dict[str, object]] = []

    def build_key_tuple(candidate: CandidateSignal) -> tuple[str, str, str, str]:
        return (
            candidate.signal.side,
            candidate.signal.timeframe,
            _signal_type(candidate.signal.reason),
            _regime(candidate.signal.reason),
        )

    with patch("src.live_adaptive_trader.print", lambda *args, **kwargs: None), patch(
        "src.live_adaptive_trader.time.sleep", lambda *_args, **_kwargs: None
    ):
        for event_ms in event_times:
            cycle += 1
            replay_client.set_time(event_ms)
            trader._ticker_cache = {
                symbol: next(
                    (
                        candle.close
                        for candle in reversed(replay_client.fetch_klines(symbol, timeframes[0], limit=100000))
                        if int(candle.close_time_ms) <= event_ms
                    ),
                    replay_client.latest_price_by_symbol[symbol],
                )
                for symbol in symbols
            }

            with patch("src.live_adaptive_trader.time.time", return_value=event_ms / 1000.0):
                trader._decrement_cooldowns()
                trader._update_open_trades(cycle)

                daily_realized = trader._daily_realized_pnl(replay_date)
                if (
                    trader.daily_loss_limit_r > 0
                    and trader._daily_loss_pause_day is None
                    and float(daily_realized["pnl_r"]) <= (-1.0 * trader.daily_loss_limit_r)
                ):
                    trader._daily_loss_pause_day = replay_date

                if trader._daily_loss_pause_day == replay_date:
                    continue

                candidates = trader._signal_candidates()
                candidate_win_prob = {id(candidate): trader._estimate_win_probability(candidate) for candidate in candidates}
                execution_candidates: List[CandidateSignal] = []
                for candidate in candidates:
                    key = _signal_key(candidate)
                    if key not in raw_seen:
                        raw_seen.add(key)
                        raw_keys.append(build_key_tuple(candidate))
                    if candidate.signal.confidence < trader.min_candidate_confidence:
                        continue
                    if candidate.expectancy_r < trader.min_candidate_expectancy_r:
                        continue
                    execution_candidates.append(candidate)

                confirmations: Dict[tuple[str, str], set[str]] = defaultdict(set)
                for candidate in execution_candidates:
                    confirmations[(candidate.signal.symbol, candidate.signal.side)].add(candidate.signal.timeframe)

                qualified: List[CandidateSignal] = []
                open_trade_symbols = trader._open_trade_symbols()
                for candidate in execution_candidates:
                    signal_type = trader._signal_type_from_reason(candidate.signal.reason)
                    is_crossover = signal_type == "CROSSOVER"
                    min_confidence = trader.crossover_execute_min_confidence if is_crossover else trader.execute_min_confidence
                    min_expectancy_r = (
                        trader.crossover_execute_min_expectancy_r if is_crossover else trader.execute_min_expectancy_r
                    )
                    min_score = trader.crossover_execute_min_score if is_crossover else trader.execute_min_score
                    min_win_probability = (
                        trader.crossover_execute_min_win_probability
                        if is_crossover
                        else trader.execute_min_win_probability
                    )
                    if candidate.signal.confidence < min_confidence:
                        continue
                    if candidate.expectancy_r < min_expectancy_r:
                        continue
                    if candidate.score < min_score:
                        continue
                    if candidate_win_prob[id(candidate)] < min_win_probability:
                        continue
                    if trader.require_dual_timeframe_confirm and len(confirmations[(candidate.signal.symbol, candidate.signal.side)]) < 2:
                        continue
                    if candidate.signal.timeframe not in trader.execute_timeframes:
                        continue
                    if trader.allowed_execution_regimes and trader._signal_regime_from_reason(candidate.signal.reason) not in trader.allowed_execution_regimes:
                        continue
                    if candidate.signal.symbol in open_trade_symbols:
                        continue
                    policy_decision = trader.policy_engine.evaluate_candidate(signal_type, candidate.signal.side)
                    if not policy_decision.allowed:
                        continue
                    qualified.append(candidate)
                    key = _signal_key(candidate)
                    if key not in qualified_seen:
                        qualified_seen.add(key)
                        qualified_keys.append(build_key_tuple(candidate))

                if not qualified:
                    continue

                available_slots = max(0, trader.max_open_trades - len(trader.open_trades))
                if available_slots <= 0:
                    continue

                if len(qualified) > 1 and (qualified[0].score - qualified[1].score) < trader.min_score_gap:
                    continue

                selected_candidates: List[CandidateSignal] = []
                seen_symbols = set(trader._open_trade_symbols())
                open_long_count = sum(1 for managed in trader.open_trades.values() if managed.signal.side == "LONG")
                open_short_count = sum(1 for managed in trader.open_trades.values() if managed.signal.side == "SHORT")
                for candidate in qualified:
                    if candidate.signal.symbol in seen_symbols:
                        continue
                    if candidate.signal.side == "LONG" and open_long_count >= trader.max_same_direction_trades:
                        continue
                    if candidate.signal.side == "SHORT" and open_short_count >= trader.max_same_direction_trades:
                        continue
                    selected_candidates.append(candidate)
                    seen_symbols.add(candidate.signal.symbol)
                    if candidate.signal.side == "LONG":
                        open_long_count += 1
                    else:
                        open_short_count += 1
                    if len(selected_candidates) >= min(trader.top_n, available_slots):
                        break

                for selected in selected_candidates:
                    key = _signal_key(selected)
                    if key not in opened_seen:
                        opened_seen.add(key)
                        opened_keys.append(build_key_tuple(selected))
                    trader.open_trades[
                        f"{selected.signal.symbol}:{selected.signal.timeframe}:{selected.signal.side}"
                    ] = trader._make_managed_trade(selected.signal, False)
                    opened_trades.append(
                        {
                            "opened_at": datetime.fromtimestamp(event_ms / 1000.0, tz=timezone.utc).isoformat(),
                            "symbol": selected.signal.symbol,
                            "timeframe": selected.signal.timeframe,
                            "side": selected.signal.side,
                            "confidence": round(selected.signal.confidence, 6),
                            "score": round(selected.score, 6),
                            "win_probability": round(candidate_win_prob[id(selected)], 6),
                            "entry": selected.signal.entry,
                            "take_profit": selected.signal.take_profit,
                            "stop_loss": selected.signal.stop_loss,
                            "reason": selected.signal.reason,
                        }
                    )

    summary = trader._summary()
    replay_trades = [asdict(trade) for trade in trader.recent_trades if trade.closed_at_ms >= start_ms]
    return {
        "date": replay_date,
        "window_utc": {
            "start": datetime.fromtimestamp(start_ms / 1000.0, tz=timezone.utc).isoformat(),
            "end": datetime.fromtimestamp(end_ms / 1000.0, tz=timezone.utc).isoformat(),
        },
        "market_context_mode": "event_time_price_current_funding_oi",
        "symbols": symbols,
        "timeframes": timeframes,
        "event_points": len(event_times),
        "recorded_today": _recorded_today_stats(replay_date, start_ms=start_ms, end_ms=end_ms),
        "replay_summary": {
            "count": len(replay_trades),
            "wins": sum(1 for trade in replay_trades if trade["result"] == "WIN"),
            "losses": sum(1 for trade in replay_trades if trade["result"] == "LOSS"),
            "win_rate": round(summary["win_rate"], 4),
            "expectancy_r": round(summary["expectancy_r"], 6),
            "net_r": round(sum(float(trade["pnl_r"]) for trade in replay_trades), 6),
            "net_usd": round(sum(float(trade["pnl_usd"]) for trade in replay_trades), 6),
            "open_trades_end": summary["open_trades"],
        },
        "raw_signals": {
            "count": len(raw_seen),
            "by_side": dict(Counter(side for side, _, _, _ in raw_keys)),
            "breakdown": _bucket_counts(raw_keys),
        },
        "qualified_signals": {
            "count": len(qualified_seen),
            "by_side": dict(Counter(side for side, _, _, _ in qualified_keys)),
            "breakdown": _bucket_counts(qualified_keys),
        },
        "opened_signals": {
            "count": len(opened_seen),
            "by_side": dict(Counter(side for side, _, _, _ in opened_keys)),
            "breakdown": _bucket_counts(opened_keys),
        },
        "replay_trades": replay_trades,
        "opened_trades": opened_trades,
        "limitations": [
            "Historical funding/open-interest snapshots were not stored, so replay uses current Binance market context per symbol.",
            "Cooldown and risk-guard cycles are approximated on candle-event steps rather than 12-second live polling steps.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay today's strategy signals/trades with current live filters.")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--date", default=datetime.now(timezone.utc).date().isoformat(), help="UTC date in YYYY-MM-DD")
    parser.add_argument("--start-time", default=None, help="Optional UTC start time in HH:MM")
    parser.add_argument("--end-time", default=None, help="Optional UTC end time in HH:MM")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = load_config(str(config_path))
    report = run_replay(config, args.date, start_time_text=args.start_time, end_time_text=args.end_time)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
