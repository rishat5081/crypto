# Crypto Futures Data-Only Signal System

This folder contains a complete data-only crypto futures scanner with:

- public REST market data pulling (no order placement)
- signal generation (LONG/SHORT)
- entry, take-profit, and stop-loss output
- audible alert when a new trade signal is opened
- one-active-trade-at-a-time lifecycle tracking
- adaptive tuning based on closed-trade outcomes
- live frontend dashboard for TP/SL monitoring
- large multi-coin possible trade pool (up to 1000+) with probability buckets
- right-side market news panel (auto-refresh + manual refresh)
- searchable Binance futures symbol catalog with multi-coin runtime watchlist updates (no restart)
- persistent History tab that stores closed trades from `data/live_events_history.jsonl`
- visual runtime logs panel showing per-coin activity + recent system events
- MongoDB-backed storage for runtime events, trades, runtime controls, and config snapshots

## One Command Setup + Run

```bash
cd /Users/user/Desktop/Work/crypto && ./run_all.sh
```

Prerequisite: a reachable MongoDB server (local or remote), e.g. local `mongod` on `127.0.0.1:27017`.

That single command will:

- detect your OS
- install Python (if missing) using available package manager
- create `.venv` and install Python packages
- start frontend dashboard at `http://127.0.0.1:8787`
- connect to MongoDB and auto-create database `crypto_trading_live` on first writes
- pull latest live market data
- optimize and apply the best strategy from recent data
- retune live thresholds from longer multi-coin trade history
- start the live adaptive loop (find signal, wait for closure, verify result, retune, repeat)

## Frontend Folder

- `frontend/index.html`: dashboard UI
- `frontend/styles.css`: dashboard styling
- `frontend/app.js`: live data polling + rendering
- `frontend/server.py`: local API + static file server

## Files

- `config.json`: pairs, timeframes, strategy, risk, and validation settings
- `requirements.txt`: Python package dependencies
- `run_all.sh`: one-command launcher for full setup + trading flow + UI
- `fetch_live_cache.sh`: fetch live Binance market snapshots into local JSON cache
- `run_ml_walkforward.py`: ML walk-forward optimizer (feature model + sequential trade validation)
- `run_retune_thresholds.py`: retune `live_loop` thresholds from recent `TRADE_RESULT` history
- `run_live_adaptive.py`: continuous live paper-trading loop with auto-feedback tuning
- `src/binance_futures_rest.py`: public Binance futures data client
- `src/strategy.py`: setup logic + adaptive tuning
- `src/trade_engine.py`: paper trade lifecycle and PnL
- `src/alerts.py`: terminal + OS sound alerts

## Output

Runtime prints JSON lines, including:

- `OPEN_TRADE` with pair, timeframe, side, entry, TP, SL, confidence
- `TRADE_RESULT` with result (`WIN`/`LOSS`) and PnL
- `POSSIBLE_TRADES` with large ranked candidate pool and probability categories (`70%+`, `50-69%`, `30-49%`, `20-29%`, `<20%`)
- `RUNTIME_SYMBOLS_UPDATED` when UI symbol updates are applied live

Frontend consumes event stream from:

- `data/live_events.jsonl`
- historical stream retained in `data/live_events_history.jsonl` for threshold retuning

MongoDB stores runtime data in collections:

- `runtime_events`: all ingested live events (`RUN_STAGE`, `LIVE_MARKET`, `POSSIBLE_TRADES`, `OPEN_TRADE`, `TRADE_RESULT`, etc.)
- `trade_history`: normalized closed trades for History tab
- `runtime_control`: symbol/watchlist runtime updates
- `config_snapshots`: saved config snapshots

## Optional Environment Flags

- `FRONTEND_HOST` (default `127.0.0.1`)
- `FRONTEND_PORT` (default `8787`)
- `START_FRONTEND` (default `1`; set `0` to disable UI)
- `AUTO_INSTALL_DEPS` (default `1`; set `0` only if you want to skip pip installs)
- `MONGO_URI` (default `mongodb://127.0.0.1:27017`)
- `MONGO_DB` (default `crypto_trading_live`)
- `MONGO_REQUIRED` (default `1`; keep `1` to fail fast if MongoDB is unavailable)
- `OPTIMIZE_TIMEOUT_SEC` (default `45`; live trading starts after timeout if optimizer is still running)
- `RETUNE_FROM_EVENTS` (default `1`; set `0` to skip history-based threshold retune)
- `RETUNE_LOOKBACK_TRADES` (default `300`)
- `RETUNE_MIN_TRADES` (default `20`)

## Data Source Mode

`config.json` -> `data_source`:

- `force_mock: false` keeps live REST as primary
- `allow_mock_fallback: true` falls back to deterministic mock data if API access fails
- `mock_seed` controls repeatable mock runs

For strict real-market runs:

- set `force_mock: false`
- set `allow_mock_fallback: false`

`config.json` -> `execution`:

- `fee_bps_per_side`: exchange fee per side in bps
- `slippage_bps_per_side`: expected slippage per side in bps

`config.json` -> `live_loop`:

- live symbols/timeframes
- scan interval and per-trade max wait
- trade quality filters (`min_rr_floor`, `min_trend_strength`)
- candidate list controls (`max_parallel_candidates`, `possible_trades_limit`, `min_candidate_confidence`, `min_candidate_expectancy_r`)
- execution gates (`execute_min_confidence`, `execute_min_expectancy_r`, `execute_min_score`, `require_dual_timeframe_confirm`, `min_score_gap`)
- adaptive gate relaxation (`relax_after_filter_blocks` + `relax_*`) to prevent prolonged no-trade stalls
- intratrade risk manager (`enable_break_even`, `break_even_trigger_r`, `break_even_offset_r`, `max_adverse_r_cut`, `max_stagnation_bars`, `min_progress_r_for_stagnation`)
- loss guard (`loss_guard`) for symbol/global loss-streak pauses with automatic threshold tightening
- auto quality guard (`performance_guard`) to cooldown weak symbols and retune thresholds
- target/stop conditions (`target_trades`, `target_win_rate`, `max_cycles`)

Frontend API extras:

- `GET /api/symbols?q=<text>&limit=<n>`: searchable Binance USDT perpetual symbol catalog
- `POST /api/config/symbols` with `{"symbols":["BTCUSDT","ETHUSDT",...]}` for multi-coin runtime updates
- `GET /api/news` (or `?force=1`) for latest headline feed aggregation
- `GET /api/history?limit=<n>`: stored closed-trade history for the History tab
- `GET /api/storage`: MongoDB connection/storage status

## Important

- This is decision-support tooling, not guaranteed prediction.
- No strategy can guarantee every trade is a winner in live markets.
- It uses market-data-driven simulation and live paper-trade tracking; real execution outcomes can differ.
- Keep API usage within exchange rate limits.

## EC2 Production Deployment (One Script)

On your EC2 instance, inside this project folder:

```bash
cd /path/to/crypto
chmod +x deploy_ec2.sh
./deploy_ec2.sh
```

That one script will:

- install required system packages
- provision local MongoDB via Docker (or use external Mongo if configured)
- create/verify Python virtualenv and dependencies
- compile Python sources (`py_compile`)
- create `start_production.sh`
- register and start `systemd` service `crypto-trader`
- enable auto-start on reboot and restart-on-failure (24/7)

Useful commands:

```bash
sudo systemctl status crypto-trader
sudo journalctl -u crypto-trader -f
sudo systemctl restart crypto-trader
```
