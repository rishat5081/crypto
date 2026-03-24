# Configuration Reference

All configuration lives in `config.json`. This document explains every parameter.

## `account`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `starting_balance_usd` | float | 10.0 | Paper trading balance |
| `risk_per_trade_pct` | float | 0.02 | Risk per trade as percentage of balance |

**Derived**: `risk_usd = starting_balance_usd * risk_per_trade_pct` = $0.20 per trade

## `execution`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `fee_bps_per_side` | float | 2 | Exchange fee in basis points per side |
| `slippage_bps_per_side` | float | 1 | Expected slippage in bps per side |

**Total cost**: (2 + 1) * 2 sides = 6 bps round trip = 0.06%

## `strategy`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `lookback_candles` | int | 260 | Number of candles to fetch for analysis |
| `ema_fast` | int | 21 | Fast EMA period |
| `ema_slow` | int | 55 | Slow EMA period |
| `rsi_period` | int | 14 | RSI calculation period |
| `atr_period` | int | 14 | ATR calculation period |
| `atr_multiplier` | float | 1.5 | TP/SL distance = ATR * this value |
| `risk_reward` | float | **1.5** | TP = SL distance × risk_reward. At ≤40% WR, need RR ≥ 1.78 to break even; 1.5 is the practical floor. |
| `min_atr_pct` | float | 0.0015 | Minimum ATR/price ratio (skip low-vol) |
| `max_atr_pct` | float | 0.03 | Maximum ATR/price ratio (skip extreme vol) |
| `funding_abs_limit` | float | 0.001 | Max absolute funding rate |
| `min_confidence` | float | 0.60 | Minimum confidence to generate signal (strategy-level gate) |
| `crossover_lookback` | int | 12 | Bars to look back for EMA crossover |
| `ema_trend` | int | **200** | Macro trend filter period. `0` = disabled. When set, LONGs only fire above EMA(ema_trend); SHORTs only below. Eliminates counter-trend trades. |
| `long_rsi_min` | float | **48** | Minimum RSI for LONG signals (raised from 45 — require directional conviction) |
| `long_rsi_max` | float | **70** | Maximum RSI for LONG signals (lowered from 72) |
| `short_rsi_min` | float | **22** | Minimum RSI for SHORT signals (raised from 18) |
| `short_rsi_max` | float | **47** | Maximum RSI for SHORT signals (lowered from 50 — ensure RSI clearly bearish) |

## `live_loop`

### Symbols & Timeframes

| Key | Type | Description |
|-----|------|-------------|
| `symbols` | string[] | Trading symbols (e.g., `["BTCUSDT", "ETHUSDT"]`) |
| `timeframes` | string[] | Candle timeframes. **Use `["15m"]` only** — 5m had 34.2% WR vs 37.7% for 15m in bulk testing |
| `lookback_candles` | int | Candles to fetch per symbol |
| `klines_window_size` | int | Symbols to scan per cycle (rotating window) |

### Timing

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `poll_seconds` | int | 12 | Seconds between API polls |
| `max_wait_candles` | int | 12 | Max candles before timeout exit |
| `max_wait_minutes_per_trade` | int | 180 | Hard time limit (safety cap) |

### Candidate Filters

| Key | Type | Current | Description |
|-----|------|---------|-------------|
| `min_rr_floor` | float | 0.6 | Minimum risk/reward ratio |
| `min_trend_strength` | float | 0.0012 | Min EMA gap / price |
| `min_candidate_confidence` | float | **0.68** | Min confidence for candidate list (raised from 0.65) |
| `min_candidate_expectancy_r` | float | **0.08** | Min expectancy for candidate list (raised from 0.05) |

### Execution Filters

| Key | Type | Current | Description |
|-----|------|---------|-------------|
| `execute_min_confidence` | float | **0.70** | Min confidence to take trade (raised from 0.62) |
| `execute_min_expectancy_r` | float | **0.10** | Min expectancy to take trade (raised from 0.05) |
| `execute_min_score` | float | **0.60** | Min composite score (raised from 0.55) |
| `execute_min_win_probability` | float | 0.50 | Min win probability to take trade |
| `require_dual_timeframe_confirm` | bool | false | Require signal on 2 timeframes |
| `min_score_gap` | float | 0.0 | Min gap between top 2 candidates |

**Expectancy formula**: `conf × RR − (1−conf) × 1.0 − cost_r`
At conf=0.70, RR=1.5: `0.70 × 1.5 − 0.30 × 1.0 = +0.75R` expected per trade before cost.

### Filter Relaxation

| Key | Type | Current | Description |
|-----|------|---------|-------------|
| `relax_after_filter_blocks` | int | 6 | Cycles before auto-relaxing |
| `relax_conf_step` | float | 0.005 | Step to lower confidence per relax |
| `relax_min_execute_confidence` | float | **0.67** | Floor for confidence relaxation (raised from 0.60) |
| `relax_min_execute_expectancy_r` | float | **0.08** | Floor for expectancy relaxation (raised from 0.03) |
| `relax_min_execute_score` | float | **0.58** | Floor for score relaxation (raised from 0.50) |

> **Important**: relaxation floors must be set high enough to prevent the auto-relax mechanism from reverting the quality improvements made in v1.4.

### Risk Management

| Key | Type | Current | Description |
|-----|------|---------|-------------|
| `enable_break_even` | bool | true | Move SL to break-even |
| `break_even_trigger_r` | float | **0.6** | R-multiple to trigger break-even (lowered from 0.8 — locks BE 2 candles sooner) |
| `break_even_offset_r` | float | **0.05** | BE stop = entry + 0.05×risk. Ensures pnl_r > 0 → classified WIN (was 0.02 → often 0.0R = LOSS) |
| `enable_trailing_stop` | bool | true | Enable trailing stop |
| `trail_trigger_r` | float | **0.3** | R-multiple to activate trailing (lowered from 0.5 — critical fix) |
| `trail_keep_pct` | float | **0.92** | Keep 92% of peak R via trail (raised from 0.85) |
| `max_adverse_r_cut` | float | **0.85** | Force close at this adverse R (lowered from 1.1 — cut losses 22% sooner) |
| `max_stagnation_bars` | int | 6 | Bars before stagnation exit |
| `min_progress_r_for_stagnation` | float | 0.10 | Min best_r to avoid stagnation exit |
| `momentum_reversal_bars` | int | 3 | Consecutive adverse bars for reversal exit |
| `momentum_reversal_r` | float | -0.4 | R threshold for reversal exit |

#### Trail stop mechanics

When `best_r >= trail_trigger_r`:
```
trail_sl_r  = best_r × trail_keep_pct
LONG  exit  = entry  + trail_sl_r × original_risk   (locks profit above entry)
SHORT exit  = entry  − trail_sl_r × original_risk   (locks profit below entry)
```

Example — DOTUSDT SHORT (live 2026-03-24):
- Entry: $1.376 | SL: $1.3926 | risk = $0.0166
- Candle low reached $1.367 → best_r = +0.542R → trail activated
- Trail SL = 1.376 − (0.542 × 0.92 × 0.0166) = **$1.3705**
- Trade exited at close = $1.3705 → **+0.390R WIN**

### Loss Guard

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `loss_guard.enabled` | bool | true | Enable loss guard |
| `loss_guard.max_global_consecutive_losses` | int | 3 | Global loss streak limit |
| `loss_guard.global_pause_cycles` | int | 3 | Pause cycles after global streak |
| `loss_guard.max_symbol_consecutive_losses` | int | 3 | Per-symbol loss streak limit |
| `loss_guard.symbol_pause_cycles` | int | 4 | Pause cycles per symbol |

### Performance Guard

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `performance_guard.enabled` | bool | true | Enable performance guard |
| `performance_guard.rolling_window_trades` | int | 12 | Window for symbol stats |
| `performance_guard.min_symbol_trades` | int | 2 | Min trades before evaluating |
| `performance_guard.min_symbol_win_rate` | float | 0.40 | Below this = cooldown |
| `performance_guard.cooldown_cycles` | int | 6 | Cycles to pause weak symbol |
| `performance_guard.min_active_symbols` | int | 3 | Never go below this |

### Session Control

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `top_n` | int | 1 | Trade top N candidates per cycle |
| `max_cycles` | int | 50 | Max trading cycles (set higher for production) |
| `target_trades` | int | 3 | Target number of trades |
