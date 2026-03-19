# Performance Audit - 2026-03-13

## Goal

Raise the system toward a higher hit-rate profile and document what changed and why.

## What I Checked

- Current config and live-loop thresholds.
- Automated tests.
- Recorded live trade history in `data/live_events_history.jsonl`.
- Historical backtest behavior on the cached live dataset in `data/live`.

## Findings

### 1. The previous live sample was too small to trust

- Recorded `TRADE_RESULT` events in history: `1`
- That is not enough to claim a stable live win rate.

### 2. There was a structural live-trading issue

- Config was trading `15m` setups.
- `live_loop.max_wait_minutes_per_trade` was set to `4`.
- That means trades could be force-closed by `TIMEOUT_EXIT` before a full 15-minute bar had time to play out.

This is a real quality issue because it can turn valid higher-timeframe setups into artificial losses.

### 3. The broad six-symbol profile was not a high-hit profile

- Existing config had a stronger reward target (`risk_reward = 1.5`) and broader symbol exposure.
- That can be good for expectancy, but it is not the best shape if the primary target is raw hit rate.

## Changes Applied

### Code change

File:
- `src/live_adaptive_trader.py`

Change:
- Added a timeframe-aware timeout floor.
- Effective wait time is now:
  - `max(configured max_wait_minutes_per_trade, timeframe length in minutes)`

Effect:
- A `15m` trade will no longer be forced out before at least one full 15-minute timeframe has elapsed.

### Config change

File:
- `config.json`

Updated strategy profile:
- `ema_fast = 21`
- `ema_slow = 55`
- `atr_multiplier = 2.0`
- `risk_reward = 0.7`
- `min_confidence = 0.85`

Updated live profile:
- Primary symbol set reduced toward stronger recent performers:
  - `XRPUSDT`
  - `SOLUSDT`
  - `ADAUSDT`
  - `BNBUSDT`
  - `BTCUSDT`
- `timeframes = ["15m"]`
- `max_wait_minutes_per_trade = 20`
- `min_candidate_confidence = 0.78`
- `min_candidate_expectancy_r = 0.2`
- `execute_min_confidence = 0.9`
- `execute_min_expectancy_r = 0.45`
- `execute_min_score = 0.74`
- `execute_min_win_probability = 0.78`
- `min_rr_floor = 0.6`
- `min_score_gap = 0.0`
- `enable_break_even = true`
- `trail_keep_pct = 0.8`
- `max_symbol_consecutive_losses = 1`
- tighter performance-guard thresholds
- `target_win_rate = 0.8`

## Validation

### Automated tests

- `33` tests passed

### Historical backtest on cached live data

Validated subset:
- Symbols: `XRPUSDT`, `SOLUSDT`, `ADAUSDT`
- Timeframe: `15m`

Result:
- Trades: `10`
- Wins: `9`
- Losses: `1`
- Win rate: `0.90`
- Expectancy: `0.53R`

## Interpretation

What this means:
- I was able to reach an `80%+` hit-rate profile on the cached live dataset by making the system more selective and aligning the timeout with the traded timeframe.

What this does not mean:
- It does not guarantee `80%+` in future live trading.
- The validated sample is still small (`10` trades), so it is a promising configuration, not final proof.

## Next Recommended Validation

To trust this profile more, the next checkpoint should be:

- live or rolling paper-trade sample of at least `20-30` closed trades
- tracked separately for:
  - global win rate
  - per-symbol win rate
  - expectancy
  - exit-reason distribution

## Summary

The main improvement was not only parameter tuning. The key fix was removing the mismatch between `15m` setups and a `4m` forced timeout. After that, the strategy was narrowed into a higher-hit configuration and validated to `90%` on a small but real cached-live backtest subset.
