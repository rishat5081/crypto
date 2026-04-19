from __future__ import annotations

import copy
from typing import Dict, Iterable, List, Sequence, Tuple

from src.bulk_backtester import MarketDataset
from src.indicators import atr, ema, rsi
from src.ml.preprocessing import LogisticBinaryClassifier, StandardScaler
from src.ml.types import FoldResult, SignalSample, WalkForwardResult, regime_from_reason, signal_type_from_reason
from src.strategies import StrategyService


class MLWalkForwardOptimizer:
    def __init__(self, risk_usd: float, fee_bps_per_side: float = 0.0, slippage_bps_per_side: float = 0.0):
        self.risk_usd = risk_usd
        self.fee_bps_per_side = fee_bps_per_side
        self.slippage_bps_per_side = slippage_bps_per_side

    @staticmethod
    def _safe_div(a: float, b: float) -> float:
        if abs(b) < 1e-12:
            return 0.0
        return a / b

    def trade_cost_r(self, entry: float, stop_loss: float) -> float:
        risk_per_unit = abs(entry - stop_loss)
        if risk_per_unit < 1e-12:
            return 0.0
        roundtrip_bps = 2.0 * (self.fee_bps_per_side + self.slippage_bps_per_side)
        roundtrip_cost_per_unit = entry * (roundtrip_bps / 10_000.0)
        return roundtrip_cost_per_unit / risk_per_unit

    def _feature_vector(
        self,
        dataset: MarketDataset,
        candles,
        idx: int,
        entry: float,
        stop_loss: float,
        take_profit: float,
        side: str,
        confidence: float,
        ema_fast_period: int,
        ema_slow_period: int,
        rsi_period: int,
        atr_period: int,
    ) -> List[float]:
        window = candles[: idx + 1]
        closes = [c.close for c in window]
        ema_fast_v = ema(closes, ema_fast_period)
        ema_slow_v = ema(closes, ema_slow_period)
        rsi_v = rsi(closes, rsi_period)
        atr_v = atr(window, atr_period)
        candle = candles[idx]
        body = candle.close - candle.open
        total_range = max(candle.high - candle.low, 1e-9)
        upper_wick = candle.high - max(candle.open, candle.close)
        lower_wick = min(candle.open, candle.close) - candle.low
        prev3 = candles[idx - 3].close if idx >= 3 else candles[0].close
        prev6 = candles[idx - 6].close if idx >= 6 else candles[0].close
        prev12 = candles[idx - 12].close if idx >= 12 else candles[0].close
        vol_slice = [c.volume for c in candles[max(0, idx - 20) : idx + 1]]
        vol_mean = sum(vol_slice) / max(1, len(vol_slice))
        rr = self._safe_div(abs(take_profit - entry), abs(entry - stop_loss))
        side_num = 1.0 if side == "LONG" else -1.0
        return [
            side_num,
            self._safe_div(entry - ema_fast_v, entry),
            self._safe_div(ema_fast_v - ema_slow_v, entry),
            rsi_v / 100.0,
            self._safe_div(atr_v, entry),
            self._safe_div(body, total_range),
            self._safe_div(upper_wick, total_range),
            self._safe_div(lower_wick, total_range),
            self._safe_div(candle.close - prev3, prev3),
            self._safe_div(candle.close - prev6, prev6),
            self._safe_div(candle.close - prev12, prev12),
            self._safe_div(candle.volume - vol_mean, vol_mean),
            confidence,
            rr,
        ]

    def _simulate_outcome(self, side: str, entry: float, take_profit: float, stop_loss: float, candles, start_idx: int, max_horizon_bars: int) -> Tuple[bool, int] | None:
        end = min(len(candles), start_idx + max_horizon_bars)
        for i in range(start_idx, end):
            candle = candles[i]
            if side == "LONG":
                hit_sl = candle.low <= stop_loss
                hit_tp = candle.high >= take_profit
                if not hit_sl and not hit_tp:
                    continue
                if hit_sl:
                    return False, candle.close_time_ms
                return True, candle.close_time_ms
            hit_sl = candle.high >= stop_loss
            hit_tp = candle.low <= take_profit
            if not hit_sl and not hit_tp:
                continue
            if hit_sl:
                return False, candle.close_time_ms
            return True, candle.close_time_ms
        return None

    def generate_samples(self, datasets: List[MarketDataset], strategy_payload: Dict, max_horizon_bars: int = 120) -> List[SignalSample]:
        strategy = StrategyService.from_config(copy.deepcopy(strategy_payload))
        samples: List[SignalSample] = []
        for dataset in datasets:
            candles = dataset.candles
            warmup = max(strategy.params.ema_slow, strategy.params.rsi_period + 2, strategy.params.atr_period + 2)
            for idx in range(warmup, len(candles) - 1):
                signal = strategy.evaluate(dataset.symbol, dataset.timeframe, candles[: idx + 1], dataset.market)
                if signal is None:
                    continue
                outcome = self._simulate_outcome(
                    side=signal.side,
                    entry=signal.entry,
                    take_profit=signal.take_profit,
                    stop_loss=signal.stop_loss,
                    candles=candles,
                    start_idx=idx + 1,
                    max_horizon_bars=max_horizon_bars,
                )
                if outcome is None:
                    continue
                is_win, close_time_ms = outcome
                rr = self._safe_div(abs(signal.take_profit - signal.entry), abs(signal.entry - signal.stop_loss))
                gross_pnl_r = rr if is_win else -1.0
                cost_r = self.trade_cost_r(signal.entry, signal.stop_loss)
                pnl_r = gross_pnl_r - cost_r
                features = self._feature_vector(
                    dataset=dataset,
                    candles=candles,
                    idx=idx,
                    entry=signal.entry,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    side=signal.side,
                    confidence=signal.confidence,
                    ema_fast_period=strategy.params.ema_fast,
                    ema_slow_period=strategy.params.ema_slow,
                    rsi_period=strategy.params.rsi_period,
                    atr_period=strategy.params.atr_period,
                )
                samples.append(
                    SignalSample(
                        symbol=dataset.symbol,
                        timeframe=dataset.timeframe,
                        side=signal.side,
                        open_time_ms=signal.signal_time_ms,
                        close_time_ms=close_time_ms,
                        features=features,
                        label=1 if pnl_r > 0 else 0,
                        pnl_r=pnl_r,
                        confidence=signal.confidence,
                        signal_type=signal_type_from_reason(signal.reason),
                        regime=regime_from_reason(signal.reason),
                    )
                )
        samples.sort(key=lambda sample: sample.open_time_ms)
        return samples

    def _select_sequential_trades(self, samples: Sequence[SignalSample], probs: Sequence[float], threshold: float, start_available_ms: int) -> Tuple[List[SignalSample], int]:
        selected: List[SignalSample] = []
        available_ms = start_available_ms
        for sample, probability in sorted(zip(samples, probs), key=lambda item: item[0].open_time_ms):
            if probability < threshold or sample.open_time_ms < available_ms:
                continue
            selected.append(sample)
            available_ms = sample.close_time_ms
        return selected, available_ms

    @staticmethod
    def _score_samples(samples: Sequence[SignalSample]) -> Tuple[int, int, float, float]:
        trades = len(samples)
        if trades == 0:
            return 0, 0, 0.0, 0.0
        wins = sum(1 for sample in samples if sample.label == 1)
        losses = trades - wins
        win_rate = wins / trades
        expectancy_r = sum(sample.pnl_r for sample in samples) / trades
        return wins, losses, win_rate, expectancy_r

    @staticmethod
    def _bucket_samples(samples: Sequence[SignalSample], key_getter) -> List[Dict]:
        buckets: Dict[str, Dict[str, float]] = {}
        for sample in samples:
            key = str(key_getter(sample) or "UNKNOWN")
            bucket = buckets.setdefault(key, {"label": key, "trades": 0, "wins": 0, "losses": 0, "pnl_r": 0.0})
            bucket["trades"] += 1
            if sample.label == 1:
                bucket["wins"] += 1
            else:
                bucket["losses"] += 1
            bucket["pnl_r"] += sample.pnl_r
        output: List[Dict] = []
        for key in sorted(buckets.keys()):
            bucket = buckets[key]
            trades = int(bucket["trades"])
            output.append(
                {
                    "label": bucket["label"],
                    "trades": trades,
                    "wins": int(bucket["wins"]),
                    "losses": int(bucket["losses"]),
                    "win_rate": round(bucket["wins"] / trades, 4) if trades else 0.0,
                    "expectancy_r": round(bucket["pnl_r"] / trades, 4) if trades else 0.0,
                }
            )
        output.sort(key=lambda row: (row["expectancy_r"], row["label"]))
        return output

    def walk_forward(self, samples: List[SignalSample], strategy_payload: Dict, target_trades: int, folds: int = 6, initial_train_frac: float = 0.55, threshold_grid: Iterable[float] | None = None) -> WalkForwardResult:
        if threshold_grid is None:
            threshold_grid = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]
        if len(samples) < 250:
            raise RuntimeError("Not enough labeled signals for walk-forward")
        threshold_grid = list(threshold_grid)
        n = len(samples)
        train_start = int(n * initial_train_frac)
        step = max(1, (n - train_start) // folds)
        selected_all: List[SignalSample] = []
        fold_results: List[FoldResult] = []
        available_ms = -1
        for fold_index in range(folds):
            train_end = train_start + (fold_index * step)
            test_end = n if fold_index == folds - 1 else min(n, train_end + step)
            if train_end < 120 or test_end - train_end < 20:
                continue
            train_pool = samples[:train_end]
            test_samples = samples[train_end:test_end]
            calib_size = max(30, int(len(train_pool) * 0.2))
            fit_samples = train_pool[:-calib_size]
            calib_samples = train_pool[-calib_size:]
            if len(fit_samples) < 80:
                continue
            scaler = StandardScaler()
            scaler.fit([sample.features for sample in fit_samples])
            x_fit = scaler.transform([sample.features for sample in fit_samples])
            y_fit = [sample.label for sample in fit_samples]
            model = LogisticBinaryClassifier(learning_rate=0.05, epochs=260, l2=0.0008)
            model.fit(x_fit, y_fit)
            x_calib = scaler.transform([sample.features for sample in calib_samples])
            p_calib = model.predict_proba(x_calib)
            best_threshold = 0.6
            best_score = None
            for threshold in threshold_grid:
                picked, _ = self._select_sequential_trades(calib_samples, p_calib, threshold, start_available_ms=-1)
                wins, losses, win_rate, expectancy_r = self._score_samples(picked)
                trades = len(picked)
                if trades < 5:
                    continue
                score = (1 if expectancy_r > 0 else 0, expectancy_r, win_rate, wins, trades)
                if best_score is None or score > best_score:
                    best_score = score
                    best_threshold = threshold
            x_test = scaler.transform([sample.features for sample in test_samples])
            p_test = model.predict_proba(x_test)
            chosen, available_ms = self._select_sequential_trades(test_samples, p_test, threshold=best_threshold, start_available_ms=available_ms)
            wins, losses, win_rate, expectancy_r = self._score_samples(chosen)
            fold_results.append(FoldResult(fold_index=fold_index + 1, threshold=best_threshold, trades=len(chosen), wins=wins, losses=losses, win_rate=win_rate, expectancy_r=expectancy_r))
            selected_all.extend(chosen)
            if len(selected_all) >= target_trades:
                break
        selected_all.sort(key=lambda sample: sample.open_time_ms)
        selected_all = selected_all[:target_trades]
        wins, losses, win_rate, expectancy_r = self._score_samples(selected_all)
        per_market: Dict[Tuple[str, str], Dict] = {}
        for sample in selected_all:
            key = (sample.symbol, sample.timeframe)
            if key not in per_market:
                per_market[key] = {"symbol": sample.symbol, "timeframe": sample.timeframe, "trades": 0, "wins": 0, "losses": 0}
            rec = per_market[key]
            rec["trades"] += 1
            if sample.label == 1:
                rec["wins"] += 1
            else:
                rec["losses"] += 1
        per_market_list = []
        for key in sorted(per_market.keys()):
            rec = per_market[key]
            rec["win_rate"] = rec["wins"] / rec["trades"] if rec["trades"] else 0.0
            per_market_list.append(rec)
        return WalkForwardResult(
            strategy=copy.deepcopy(strategy_payload),
            tested_signals=len(samples),
            total_selected_trades=len(selected_all),
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            expectancy_r=expectancy_r,
            folds=fold_results,
            per_market=per_market_list,
            tested_thresholds=threshold_grid,
            per_signal_type=self._bucket_samples(selected_all, lambda sample: sample.signal_type),
            per_regime=self._bucket_samples(selected_all, lambda sample: sample.regime),
        )

    def optimize(self, datasets: List[MarketDataset], base_strategy: Dict, target_trades: int, target_wins: int, max_candidates: int = 48) -> Tuple[WalkForwardResult, int]:
        candidates: List[Dict] = []
        for ema_fast in [8, 13, 21]:
            for ema_slow in [34, 55, 89]:
                if ema_fast >= ema_slow:
                    continue
                for atr_mult in [0.7, 0.9, 1.1, 1.4, 1.8]:
                    for rr in [1.2, 1.0, 1.5, 0.8]:
                        for min_conf in [0.65, 0.7, 0.75, 0.8, 0.85]:
                            candidate = copy.deepcopy(base_strategy)
                            candidate["ema_fast"] = ema_fast
                            candidate["ema_slow"] = ema_slow
                            candidate["atr_multiplier"] = atr_mult
                            candidate["risk_reward"] = rr
                            candidate["min_confidence"] = min_conf
                            candidate["long_rsi_min"] = 55
                            candidate["long_rsi_max"] = 72
                            candidate["short_rsi_min"] = 28
                            candidate["short_rsi_max"] = 48
                            candidates.append(candidate)
        tested = 0
        best: WalkForwardResult | None = None
        for strategy_payload in candidates[:max_candidates]:
            samples = self.generate_samples(datasets, strategy_payload)
            if len(samples) < 250:
                tested += 1
                continue
            result = self.walk_forward(samples=samples, strategy_payload=strategy_payload, target_trades=target_trades)
            tested += 1
            score = (1 if result.expectancy_r > 0 else 0, result.expectancy_r, result.win_rate, result.wins, result.total_selected_trades)
            best_score = (1 if best.expectancy_r > 0 else 0, best.expectancy_r, best.win_rate, best.wins, best.total_selected_trades) if best is not None else None
            if best is None or (best_score is not None and score > best_score):
                best = result
            if result.total_selected_trades >= target_trades and result.wins >= target_wins and result.expectancy_r > 0:
                return result, tested
        if best is None:
            raise RuntimeError("ML optimizer did not produce valid results")
        return best, tested
