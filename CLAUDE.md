# CLAUDE.md - Project Intelligence for AI Agents

> **Read this first.** This file gives any AI agent (Claude Code, Codex, Cursor, GitHub Copilot)
> complete context to work effectively in this codebase. It is auto-loaded by Claude Code on every session.

## What This Project Is

A **real-time cryptocurrency signal engine** that:
1. Pulls live market data from Binance Futures public REST API (no API key needed)
2. Generates LONG/SHORT signals using EMA crossover, pullback, and momentum strategies
3. Tracks paper trades with adaptive TP/SL, trailing stops, and risk management
4. Displays everything on a live web dashboard with Chart.js analytics
5. **Never places real orders** - pure paper trading with live data

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Data Source | Binance Futures REST API (public `fapi.binance.com`) |
| Frontend | Vanilla HTML/CSS/JS + Chart.js (no framework, no build step) |
| API Server | Python `http.server` (no framework) |
| Storage | JSON Lines files + optional MongoDB (`pymongo`) |
| Tests | pytest (33 tests) |
| CI/CD | GitHub Actions (7 workflows) |

## Project Structure

```
crypto/
├── src/                              # Core trading engine
│   ├── strategy.py                   # Signal generation (crossover/pullback/momentum)
│   ├── trade_engine.py               # Paper trade lifecycle & PnL
│   ├── models.py                     # Candle, Signal, OpenTrade, ClosedTrade, MarketContext
│   ├── live_adaptive_trader.py       # Main live loop (1200 lines, most complex file)
│   ├── binance_futures_rest.py       # Binance API client with retry + curl fallback
│   ├── indicators.py                 # ema(), ema_series(), rsi(), atr()
│   ├── ml_pipeline.py                # Walk-forward optimizer, logistic classifier
│   ├── scanner.py                    # Simple market scanner
│   ├── validator.py                  # 10-trade validation runner
│   ├── bulk_backtester.py            # Grid-search backtesting
│   ├── cache_loader.py               # Load cached market data
│   ├── alerts.py                     # Sound alerts (macOS/Windows)
│   ├── mock_data.py                  # Deterministic mock market data
│   └── config.py                     # Config loader + validator
├── frontend/
│   ├── server.py                     # Dashboard API (AnalyticsEngine, NewsFetcher, MongoStore)
│   ├── index.html                    # Dashboard UI (6 tabs + news sidebar)
│   ├── app.js                        # Polling, Chart.js rendering, section nav
│   └── styles.css                    # Dark theme, responsive grid
├── tests/                            # pytest unit tests (33 tests)
│   ├── test_config.py                # Config validation
│   ├── test_indicators.py            # EMA, RSI bounds
│   ├── test_strategy.py              # Signal generation
│   ├── test_trade_engine.py          # Trade TP/SL execution
│   └── test_ml_pipeline.py           # ML classifier, cost model
├── data/                             # Runtime data (JSON cache, JSONL logs)
│   └── live/                         # Cached klines, premium, OI per symbol
├── docs/                             # Documentation
├── config.json                       # All configuration (strategy, live loop, guards)
├── requirements.txt                  # pymongo>=4.8,<5
├── run_all.sh                        # One-command full setup + launch
├── run_live_adaptive.py              # Live trading entry point
├── run_ml_walkforward.py             # ML optimization
├── run_retune_thresholds.py          # Threshold retuning from history
├── deploy_ec2.sh                     # EC2 production deployment
└── fetch_live_cache.sh               # Fetch market data snapshots
```

## Build & Test Commands

```bash
# Install deps
pip install -r requirements.txt pytest

# Run all tests (must pass before any commit)
pytest tests/ -v

# Validate config
python -c "import json; json.load(open('config.json')); print('OK')"

# Start dashboard (runs on :8787)
cd frontend && python server.py &

# Run live trading
python run_live_adaptive.py --config config.json

# One-command full setup + launch
./run_all.sh
```

## How the Trading Loop Works

```
LiveAdaptivePaperTrader.run():
│
├─ For each cycle (up to max_cycles):
│   ├─ _refresh_batch_market_data()     → Fetch prices + funding rates
│   ├─ _signal_candidates()             → Generate signals across all symbols/timeframes
│   │   ├─ StrategyEngine.evaluate()    → Crossover / Pullback / Momentum detection
│   │   ├─ Filter by min_rr_floor, min_trend_strength
│   │   └─ Calculate score = (confidence*0.65) + (trend*100*0.25) + ((rr-cost)*0.10)
│   │
│   ├─ Apply execution filters:
│   │   ├─ execute_min_confidence (0.62)
│   │   ├─ execute_min_expectancy_r (0.05)
│   │   ├─ execute_min_score (0.55)
│   │   └─ execute_min_win_probability (0.50)
│   │
│   ├─ _wait_for_close(signal)          → Monitor trade until exit
│   │   ├─ Check TP/SL on each new candle
│   │   ├─ Trailing stop (activates at 0.5R, keeps 85%)
│   │   ├─ Break-even stop (at 0.8R)
│   │   ├─ Stagnation exit (6 bars, <0.1R progress)
│   │   ├─ Momentum reversal exit (3 adverse bars, -0.4R)
│   │   ├─ Candle timeout (12 candles)
│   │   └─ Network error protection (5 consecutive failures → force close)
│   │
│   ├─ _apply_feedback(trade)           → Tighten on loss, relax on win
│   ├─ _apply_loss_guard(trade)         → Pause after consecutive losses
│   └─ _apply_performance_guard()       → Cool down weak symbols
```

## Signal Types

| Type | Condition | Confidence Multiplier |
|------|-----------|----------------------|
| **Crossover** | EMA(21) crosses EMA(55) within 12 bars | 1.0x (full) |
| **Pullback** | Price within 1.2 ATR of fast EMA in trend (strength > 0.3%) | 0.92x |
| **Momentum** | Price moving in trend direction, EMA gap > 0.4% | 0.88x |

## Critical Config Parameters

| Parameter | Value | Why It Matters |
|-----------|-------|---------------|
| `atr_multiplier` | 1.5 | TP/SL distance. Was 2.0, changed to 1.5 so targets are reachable |
| `risk_reward` | 1.2 | TP = 1.2x SL distance. Break-even WR needed: 45% |
| `max_wait_candles` | 12 | Trade timeout in candles (3hrs for 15m, 1hr for 5m) |
| `trail_trigger_r` | 0.5 | Start trailing at 0.5R profit |
| `trail_keep_pct` | 0.85 | Keep 85% of peak R via trailing stop |
| `execute_min_confidence` | 0.62 | Gate for taking trades |

## Key Design Decisions

1. **Conservative fills**: Both TP+SL hit same candle → assume SL hit first
2. **WIN/LOSS from PnL**: If `pnl_r > 0`, result is always WIN (even if SL triggered after trailing stop moved it into profit)
3. **Candle-based timeout**: Uses candle count not minutes, scales naturally with timeframe
4. **Network resilience**: 3 Binance endpoints + curl fallback + 5-error force-close in trade monitor
5. **No real orders ever**: Pure paper trading, Binance public API only (no keys)
6. **Adaptive feedback is deliberately gentle**: Small tightening steps on loss to prevent filter lockout

## API Endpoints (Dashboard Server)

| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/state` | Live trading state, active trade, possible trades |
| GET | `/api/analytics` | Equity curve, drawdown, PnL distribution, streaks |
| GET | `/api/history?limit=N` | Closed trade history |
| GET | `/api/news?force=0\|1` | Crypto news headlines |
| GET | `/api/symbols?q=text&limit=N` | Binance symbol search |
| GET | `/api/storage` | MongoDB connection status |
| POST | `/api/config/symbols` | Update watchlist (JSON body: `{"symbols": [...]}`) |

## Common Modification Patterns

### Add a new symbol
Edit `config.json` → `live_loop.symbols` array. Or POST to `/api/config/symbols`.

**Current watchlist: 60 symbols** across 6 categories (Large Cap, DeFi, Layer-2, Gaming, AI/Infra, Other).
Before adding, verify the symbol is an active Binance Futures perpetual:
```bash
curl "https://fapi.binance.com/fapi/v1/ticker/price?symbol=NEWUSDT"
```

### Add a new signal type
1. `src/strategy.py` → `evaluate()`: Add detection logic after the momentum block
2. Apply confidence multiplier (e.g., `confidence *= 0.90`)
3. Include `signal_type` in reason string
4. Add test in `tests/test_strategy.py`

### Add a new exit type
1. `src/live_adaptive_trader.py` → `_wait_for_close()`: Add check after momentum reversal block
2. Use `_make_exit(active, latest, "YOUR_EXIT_TYPE")` helper
3. Add config parameter in `__init__` if configurable

### Add a new dashboard section
1. `frontend/index.html`: Add `<article class="card">` section
2. `frontend/styles.css`: Add styles
3. `frontend/app.js`: Add render function + polling
4. `frontend/server.py`: Add API endpoint if needed

## Gotchas & Warnings

- `config.json` has test values: `max_cycles: 50`, `enable_sound: false` — change for production
- `data/` contains large JSONL files — don't commit them
- No `.gitignore` exists yet — should add one for `__pycache__/`, `.venv/`, `data/*.jsonl`
- `src/__pycache__/*.pyc` files are tracked — should be gitignored
- Dashboard server has no auth — bind to localhost only in production
- `requirements.txt` only has `pymongo` — pytest/flake8/mypy are dev deps

## Recent Live Test Results (March 2026)

```
Trade 1: ETHUSDT SHORT → WIN +1.20R (TP hit, pullback entry)
Trade 2: DOTUSDT SHORT → WIN +0.72R (trailing stop, momentum entry)
Trade 3: ETHUSDT SHORT → WIN +1.20R (TP hit, momentum entry)
Total: 3W/0L, +3.12R
```
