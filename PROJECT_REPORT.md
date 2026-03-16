# Crypto Futures Trading System — Project Report

## What Is This Project?

A **data-only crypto futures decision-support platform** that monitors Binance USDT perpetual futures markets in real-time, generates LONG/SHORT trade signals using technical analysis + machine learning, executes paper trades (no real orders), and continuously adapts its strategy based on outcomes. It includes a live web dashboard for monitoring.

**It does NOT execute real trades.** All positions are simulated in paper mode.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        STARTUP PIPELINE                      │
│                                                               │
│  run_all.sh                                                   │
│    ├── fetch_live_cache.sh ──→ data/live/*.json               │
│    ├── discover_symbols.py ──→ config.json (100 symbols)      │
│    ├── run_ml_walkforward.py ──→ ML optimization              │
│    ├── run_retune_thresholds.py ──→ threshold tuning          │
│    └── run_live_adaptive.py ──→ LIVE LOOP                     │
│                                                               │
├─────────────────────────────────────────────────────────────┤
│                        LIVE LOOP                              │
│                                                               │
│  LiveAdaptivePaperTrader (12s cycles)                         │
│    ├── Batch market data (premium + ticker — 2 API calls)     │
│    ├── Rotating klines window (20 of 100 symbols per cycle)   │
│    ├── StrategyEngine.evaluate() → Signal candidates          │
│    ├── ML win probability estimation                          │
│    ├── Execution gate filters                                 │
│    ├── Paper trade open → wait for TP/SL/timeout              │
│    ├── Risk management (break-even, adverse cut, stagnation)  │
│    ├── Adaptive feedback (tighten on loss, relax on win)      │
│    └── JSONL event stream → data/live_events.jsonl            │
│                                                               │
├─────────────────────────────────────────────────────────────┤
│                        FRONTEND                               │
│                                                               │
│  frontend/server.py (Flask-like HTTP on port 8787)            │
│    ├── /api/state      → live event cache (500ms poll)        │
│    ├── /api/history    → closed trade archive                 │
│    ├── /api/news       → RSS market news                      │
│    ├── /api/symbols    → Binance symbol catalog               │
│    ├── /api/config/*   → runtime symbol/config updates        │
│    └── index.html      → dashboard UI                         │
│                                                               │
├─────────────────────────────────────────────────────────────┤
│                     PERSISTENCE                               │
│                                                               │
│  data/live_events.jsonl          (rolling current events)     │
│  data/live_events_history.jsonl  (historical archive)         │
│  MongoDB (optional)              (trade_history, events)      │
└─────────────────────────────────────────────────────────────┘
```

---

## File-by-File Breakdown

### Core Source Modules (`src/`)

| File | Lines | Purpose |
|------|-------|---------|
| **`models.py`** | 125 | Data contracts: `Candle`, `MarketContext`, `Signal`, `ClosedTrade`, `OpenTrade`. Frozen dataclasses used everywhere. |
| **`indicators.py`** | 85 | Technical indicators: `ema()`, `ema_series()`, `rsi()`, `atr()`. Pure math, no side effects. |
| **`strategy.py`** | 178 | Signal generation engine. Evaluates EMA crossovers + RSI + ATR + funding rate to produce LONG/SHORT signals with confidence scores. Self-tunes after each trade. |
| **`binance_futures_rest.py`** | 165 | Binance Futures REST client. Fetches klines, premium index, ticker prices. Supports batch endpoints (all symbols in 1 call), 3-host failover, curl fallback, and mock data fallback. |
| **`trade_engine.py`** | 43 | Paper trade state machine. Opens one trade at a time, checks TP/SL against each new candle, returns `ClosedTrade` on hit. Conservative fill: SL wins when both TP and SL hit same candle. |
| **`live_adaptive_trader.py`** | ~1100 | **The brain.** Orchestrates the full live loop: batch market data, rotating klines window, signal ranking, execution gates, trade monitoring with break-even/adverse-cut/stagnation rules, adaptive feedback, performance guards, loss guards, and JSONL event emission. |
| **`ml_pipeline.py`** | 587 | ML layer. 14-feature engineering, logistic binary classifier (gradient descent), walk-forward cross-validation (6 folds), probability threshold calibration. Estimates win probability for each candidate signal. |
| **`scanner.py`** | 119 | Simple signal scanner. Loops symbols/timeframes, prints signals as JSONL. Lighter alternative to the full live trader. |
| **`bulk_backtester.py`** | 215 | Grid search optimizer. Tests combinations of EMA periods, ATR multipliers, R/R ratios across multiple markets. Finds best parameter set by win rate + expectancy. |
| **`cache_loader.py`** | 49 | Loads pre-fetched JSON files from `data/live/` into typed `MarketDataset` objects for offline optimization. |
| **`validator.py`** | 124 | Quality gate. Simulates 10 sequential trades and reports win rate + expectancy. Must pass before going live. |
| **`config.py`** | 68 | Config validation. Checks required sections, strategy keys, RSI/ATR ranges, relax floor consistency. |
| **`mock_data.py`** | 103 | Deterministic fake market data (seeded random). Used for testing and when API is unreachable. |
| **`alerts.py`** | 26 | Sound alerts. Terminal bell + OS-specific audio (macOS Glass.aiff) on new trade signals. |

### Entry Point Scripts (root)

| File | Purpose |
|------|---------|
| **`run_live_adaptive.py`** | Main entrypoint. Loads config → runs `LiveAdaptivePaperTrader.run()` → prints summary. |
| **`run_scanner.py`** | Runs the simple signal scanner (one-shot or forever mode). |
| **`run_validate_10.py`** | Quality gate: validates 10 trades before going live. |
| **`run_ml_walkforward.py`** | Runs ML walk-forward optimization. Can `--apply-best` to write winning strategy to config. |
| **`run_bulk_optimize.py`** | Brute-force parameter grid search across all markets. |
| **`run_retune_thresholds.py`** | Post-run threshold tuning from historical trade events. |
| **`discover_symbols.py`** | Discovers top 100 USDT perpetual pairs by 24h volume, updates `config.json`. |
| **`run_all.sh`** | One-command launcher: cache fetch → ML optimize → retune → start live trader + frontend. |
| **`fetch_live_cache.sh`** | Pre-fetches klines + premium data for all symbols from config (parallel, 8 workers). |
| **`deploy_ec2.sh`** | Production deployment: installs deps, sets up MongoDB, creates systemd service. |

### Frontend (`frontend/`)

| File | Lines | Purpose |
|------|-------|---------|
| **`server.py`** | 1291 | HTTP API server. Aggregates JSONL events into state, serves trade history, market news (RSS), symbol catalog, and config management. Optional MongoDB persistence. |
| **`index.html`** | 255 | Dashboard UI. Shows active trade, latest result, market info, probability-bucketed candidates, history, news, logs, symbol search. |
| **`app.js`** | 840 | Frontend logic. Polls `/api/state` every 500ms, renders all dashboard sections, handles symbol search and config updates. |
| **`styles.css`** | 660 | Dark theme styling with animated background, color-coded trade results (green=WIN, red=LOSS), responsive grid layout. |

### Tests (`tests/`)

| File | Tests | What It Covers |
|------|-------|----------------|
| **`test_config.py`** | 6 | Config validation: missing sections, bad ranges, relax floors |
| **`test_indicators.py`** | 2 | EMA output type, RSI bounds (0-100) |
| **`test_strategy.py`** | 10 | Signal generation (uptrend/downtrend), filtering (funding, confidence, ATR), adaptive tuning |
| **`test_trade_engine.py`** | 11 | LONG/SHORT TP/SL hits, conservative fill, PnL R-multiple accuracy |
| **`test_ml_pipeline.py`** | 3 | Logistic classifier learning, trade cost calculation |

---

## How Signal Generation Works

```
Candle Data (300 bars)
    │
    ▼
┌──────────────────────────────┐
│  1. Compute EMA fast (21)    │
│     Compute EMA slow (55)    │
│     Compute RSI (14)         │
│     Compute ATR (14)         │
└──────────────┬───────────────┘
               │
    ▼
┌──────────────────────────────┐
│  2. Filter checks:           │
│     - Enough candles?        │
│     - ATR in 0.15%-3% range? │
│     - |Funding rate| < 0.1%? │
└──────────────┬───────────────┘
               │
    ▼
┌──────────────────────────────┐
│  3. Detect EMA crossover     │
│     in last 5 bars           │
│                              │
│  LONG: fast > slow +         │
│        bullish cross +       │
│        RSI 55-72             │
│                              │
│  SHORT: fast < slow +        │
│         bearish cross +      │
│         RSI 28-48            │
└──────────────┬───────────────┘
               │
    ▼
┌──────────────────────────────┐
│  4. Score confidence:        │
│     25% base                 │
│     35% trend strength       │
│     15% RSI quality          │
│     15% volatility fit       │
│     10% funding favorability │
│                              │
│  5. Set TP/SL:               │
│     SL = entry ± ATR × 2.0  │
│     TP = entry ± SL × 1.5   │
└──────────────────────────────┘
```

---

## How the Live Trading Loop Works

Each 12-second cycle:

1. **Batch Market Data** — 2 API calls fetch premium index + ticker prices for ALL symbols (weight: 12)
2. **Rotating Klines Window** — Fetch 15m candles for 20 of 100 symbols (weight: 100). All 100 scanned every 60 seconds.
3. **Signal Candidates** — Run `StrategyEngine.evaluate()` on each symbol/timeframe. Filter by confidence, R/R, trend strength, expectancy.
4. **ML Scoring** — Estimate win probability using logistic classifier trained on historical features.
5. **Execution Gate** — Top candidate must pass: confidence >= 0.86, expectancy_r >= 0.12, score >= 0.66, win_probability >= 0.60
6. **Paper Trade** — Open position, monitor candle-by-candle for TP/SL hit. Apply break-even stops, adverse cuts, stagnation exits.
7. **Adaptive Feedback** — On LOSS: tighten all thresholds. On WIN: relax slightly. Per-symbol confidence tracking.
8. **Guards** — Loss guard pauses after 2 consecutive losses. Performance guard cools down symbols with <45% win rate over 12 trades.

### Rate Limit Budget (per 12s cycle, 100 symbols)

| API Call | Count | Weight | Total |
|----------|-------|--------|-------|
| Batch ticker/price | 1 | 2 | 2 |
| Batch premiumIndex | 1 | 10 | 10 |
| Klines (20 window) | 20 | 5 | 100 |
| **Total per cycle** | | | **112** |
| **Per minute (5 cycles)** | | | **560 / 2400 limit** |

---

## Risk Management Stack

| Layer | Mechanism | Trigger | Action |
|-------|-----------|---------|--------|
| **Per-trade** | Break-even stop | Price moves 50%+ of risk in favor | Move SL to entry + 2% of risk |
| **Per-trade** | Adverse cut | Worst intra-candle loss > 110% of risk | Close at market |
| **Per-trade** | Stagnation exit | <15% progress after 8 bars | Close at market |
| **Per-trade** | Timeout | Exceeds max_wait_minutes (4 min) | Close at market |
| **Per-symbol** | Loss guard | 2+ consecutive losses on symbol | Pause symbol for 8 cycles |
| **Per-symbol** | Performance guard | <45% win rate over 12 trades | Cooldown for 6 cycles |
| **Global** | Loss guard | 2+ consecutive losses system-wide | Pause ALL trading for 5 cycles, tighten thresholds |
| **Global** | Performance guard | System win rate drops | Tighten candidate/execution thresholds |
| **Adaptive** | Filter relaxation | 6+ cycles with no viable candidates | Slightly relax execution gates |

---

## Configuration Reference

### Strategy Parameters
| Key | Default | Description |
|-----|---------|-------------|
| `ema_fast` | 21 | Fast EMA period |
| `ema_slow` | 55 | Slow EMA period |
| `rsi_period` | 14 | RSI lookback |
| `atr_period` | 14 | ATR lookback |
| `atr_multiplier` | 2.0 | SL distance = ATR x this |
| `risk_reward` | 1.5 | TP/SL ratio |
| `min_confidence` | 0.82 | Signal generation floor |
| `funding_abs_limit` | 0.001 | Max absolute funding rate |

### Live Loop Parameters
| Key | Default | Description |
|-----|---------|-------------|
| `poll_seconds` | 12 | Cycle interval |
| `klines_window_size` | 20 | Symbols scanned per cycle |
| `execute_min_confidence` | 0.86 | Execution gate |
| `execute_min_expectancy_r` | 0.12 | Execution gate |
| `execute_min_score` | 0.66 | Execution gate |
| `max_wait_minutes_per_trade` | 4 | Trade timeout |
| `top_n` | 1 | Trades executed per cycle |

### Account Parameters
| Key | Default | Description |
|-----|---------|-------------|
| `starting_balance_usd` | 10.0 | Paper balance |
| `risk_per_trade_pct` | 0.02 | 2% risk per trade |
| `fee_bps_per_side` | 2 | Trading fee (basis points) |
| `slippage_bps_per_side` | 1 | Slippage estimate |

---

## External Integrations

| Service | Endpoints Used | Purpose |
|---------|----------------|---------|
| **Binance Futures API** | `/fapi/v1/klines`, `/fapi/v1/premiumIndex`, `/fapi/v1/ticker/price`, `/fapi/v1/exchangeInfo`, `/fapi/v1/ticker/24hr` | Market data (candles, funding, prices, symbol catalog) |
| **MongoDB** | `runtime_events`, `trade_history`, `config_snapshots` | Persistence (optional) |
| **RSS Feeds** | CoinTelegraph, CryptoSlate, Blockcypher | Market news for dashboard |

---

## Deployment Options

| Method | Command | Description |
|--------|---------|-------------|
| **Local** | `bash run_all.sh` | Full pipeline: cache + optimize + live + frontend |
| **EC2** | `bash deploy_ec2.sh` | Installs deps, MongoDB, systemd service, 24/7 uptime |
| **Manual** | `python3 run_live_adaptive.py` | Just the live trader (no frontend/optimization) |

---

## Output Events (JSONL)

The system emits structured JSON events to `data/live_events.jsonl`:

| Event Type | When | Key Fields |
|------------|------|------------|
| `RUN_STAGE` | Startup phases | stage, description |
| `LIVE_MARKET` | Every cycle | snapshots (symbol, price) |
| `POSSIBLE_TRADES` | Every cycle | candidates with probability buckets |
| `OPEN_TRADE` | Trade opened | symbol, side, entry, TP, SL, confidence, score |
| `TRADE_RESULT` | Trade closed | result (WIN/LOSS), pnl_r, pnl_usd, exit_price |
| `NO_SIGNAL` | No candidates | reason (NO_CANDIDATES, GLOBAL_RISK_OFF, etc.) |
| `SYMBOL_COOLDOWN_APPLIED` | Guard triggered | symbol, stats, cooldown_cycles |
| `GUARD_RETUNE` | Threshold adjustment | direction (TIGHTEN/RELAX), before/after values |
| `LOSS_GUARD_GLOBAL_PAUSE` | System paused | consecutive_losses, pause_cycles |
| `EXECUTION_FILTER_RELAX` | Filters loosened | before/after threshold values |
