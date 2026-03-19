# Crypto Trading System - Complete Technical Documentation

## 1) Purpose Of This Application

This application is a **data-driven, no-order-placement crypto futures decision-support platform**.

It is designed to:
- Pull real-time public market data from Binance Futures.
- Generate directional trade ideas (`LONG` / `SHORT`) with:
  - entry
  - take-profit (TP)
  - stop-loss (SL)
  - confidence and reason text
- Simulate trade lifecycle in paper mode (no exchange order execution).
- Continuously adapt thresholds based on live outcomes.
- Expose a web dashboard for monitoring:
  - possible trades
  - active/open trade
  - last closed trade result
  - history
  - market snapshots
  - runtime logs
  - news feed
- Persist runtime events and trade history in MongoDB.

This system is **not an execution bot** and does **not place live orders**.

---

## 2) High-Level Architecture

### 2.1 Core runtime layers
1. **Data acquisition layer**
   - `src/binance_futures_rest.py`
   - `fetch_live_cache.sh`
2. **Signal layer**
   - `src/strategy.py`
3. **Trade simulation layer**
   - `src/trade_engine.py`
   - `src/models.py`
4. **Live adaptive orchestration layer**
   - `src/live_adaptive_trader.py`
   - `run_live_adaptive.py`
5. **Optimization / backtest / retune layer**
   - `src/ml_pipeline.py`
   - `run_ml_walkforward.py`
   - `run_bulk_optimize.py`
   - `run_retune_thresholds.py`
6. **Frontend + API layer**
   - `frontend/server.py`
   - `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`
7. **Operational wrappers**
   - `run_all.sh` (local all-in-one launcher)
   - `deploy_ec2.sh` (production deploy + systemd setup)

### 2.2 Data flow summary
1. App pulls market data.
2. Strategy computes setup and confidence.
3. Live loop ranks candidates, applies quality gates.
4. Top signal is opened as paper trade.
5. Trade is closed by TP/SL, timeout, adverse cut, or stagnation rule.
6. Result is logged and used to adapt filters.
7. Events are written to JSONL + MongoDB.
8. Frontend reads state/history and renders dashboard.

---

## 3) Repository Structure And Why Each File Exists

## 3.1 Top-level scripts

- `config.json`
  - Central runtime control plane.
  - Keeps account, strategy, execution cost model, scanner behavior, live loop thresholds.

- `run_all.sh`
  - One-command startup for local/dev-like environments.
  - Installs runtime dependencies if needed, starts frontend, fetches cache, optimizes strategy, retunes thresholds, then runs live adaptive trader.

- `deploy_ec2.sh`
  - One-command production bootstrap for EC2.
  - Installs OS packages, provisions MongoDB (local Docker mode), compiles code, creates `systemd` unit, enables 24/7 service.

- `fetch_live_cache.sh`
  - Pulls latest premium/open-interest/klines JSON snapshots for configured symbols/timeframes.
  - Supports host fallback across `fapi.binance.com`, `fapi1`, `fapi2`.

- `run_live_adaptive.py`
  - Thin entrypoint to start `LiveAdaptivePaperTrader` with loaded config.

- `run_scanner.py`
  - Simple scanner mode (single pass or loop) for emitting signals and closures.

- `run_ml_walkforward.py`
  - ML walk-forward optimization and report generation.
  - Can apply best strategy back to config.

- `run_bulk_optimize.py`
  - Brute-force style multi-market strategy sweep.
  - Useful for initial candidate filtering.

- `run_retune_thresholds.py`
  - Post-run threshold retune based on historical `TRADE_RESULT` events.

- `run_validate_10.py`
  - Runs fixed-sequence validation over 10 closed paper trades.

- `requirements.txt`
  - External Python dependency constraints (`pymongo`).

## 3.2 Core source modules (`src/`)

- `models.py`
  - Defines strict data contracts for candles, market context, signals, open trades, and closed trades.
  - Contains candle-level close logic for open trade state transitions.

- `binance_futures_rest.py`
  - Fetches exchange data via public REST.
  - Implements retries and host fallback.
  - Implements curl fallback when Python DNS path fails.
  - Supports deterministic mock mode/fallback.

- `indicators.py`
  - Technical indicators: EMA, RSI, ATR.
  - Deterministic and minimal implementation for strategy reproducibility.

- `strategy.py`
  - Signal decision engine.
  - Converts candle series + market context into trade setup and confidence.
  - Includes post-trade adaptive parameter nudging.

- `trade_engine.py`
  - Maintains one active trade, transitions to closed trades when conditions hit.

- `scanner.py`
  - Non-adaptive scan loop using `StrategyEngine + TradeEngine` map per symbol/timeframe.

- `live_adaptive_trader.py`
  - Main runtime brain.
  - Candidate scoring, probability estimation, filtering, execution, risk management, cooldowns, performance guards, threshold relaxation/tightening.

- `bulk_backtester.py`
  - Multi-symbol/timeframe backtest runner over candidate parameter grid.

- `ml_pipeline.py`
  - Feature engineering + logistic classifier + walk-forward validation.
  - Selects thresholds and strategy candidates by expectancy-focused criteria.

- `cache_loader.py`
  - Converts cached JSON files into typed market datasets.

- `validator.py`
  - Ten-trade validator for deterministic smoke checks.

- `alerts.py`
  - Sound notification helper.

- `config.py`
  - Config loader.

## 3.3 Frontend modules

- `frontend/server.py`
  - Serves static dashboard and API endpoints.
  - Maintains state cache from events.
  - Persists events/trades/runtime control/config snapshots to MongoDB.
  - Provides endpoints for:
    - state
    - history
    - health
    - storage
    - symbol catalog
    - runtime symbol updates
    - news

- `frontend/index.html`
  - Dashboard layout.

- `frontend/app.js`
  - Polling and rendering logic.

- `frontend/styles.css`
  - UI styling.

## 3.4 Tests

- `tests/test_trade_engine.py`
  - Validates TP/SL close behavior.
- `tests/test_indicators.py`
  - Validates indicator output constraints.
- `tests/test_ml_pipeline.py`
  - Validates classifier learning and cost-model positivity.

---

## 4) Why The Key Runtime Logic Is Written The Way It Is

## 4.1 Strategy logic (`src/strategy.py`)

### Why EMA trend filter exists
- `ema_fast > ema_slow` for long, inverse for short.
- Purpose: avoid counter-trend setups.

### Why RSI bands exist
- Long/short RSI bands avoid entries in poor momentum zones.
- Purpose: reduce random trend-chasing.

### Why ATR% min/max exists
- Too-low ATR => no movement; too-high ATR => unstable volatility.
- Purpose: filter out unusable market regimes.

### Why funding-rate bound exists
- Funding extremes can distort directional edge.
- Purpose: avoid biased or crowded side risk.

### Why confidence formula is blended
Confidence combines:
- trend score
- RSI score
- volatility score
- funding score

Purpose:
- convert multiple setup quality dimensions into a single gateable score.

---

## 4.2 Live adaptive logic (`src/live_adaptive_trader.py`)

### Why candidate stages are separated
1. Build candidate list (`_signal_candidates`)
2. Publish all possible trades for dashboard transparency
3. Apply execution-only stricter filters

Purpose:
- show opportunities broadly while executing only higher quality setups.

### Why expectancy and win-probability are both used
- expectancy helps profitability targeting.
- win-probability helps hit-rate targeting.

Purpose:
- avoid high-hit but negative-expectancy profiles.

### Why there are multiple guards
- `loss_guard`: immediate response to loss streaks.
- `performance_guard`: rolling performance control per symbol + globally.
- `execution_filter_relax`: prevents deadlock when no trades are taken.

Purpose:
- maintain uptime and adapt behavior without manual babysitting.

### Why timeout exit exists
- Some trades will not hit TP/SL in acceptable time.
- Purpose: capital/risk recycling and bounded holding time.

### Why break-even and adverse/stagnation exits exist
- Break-even lock: protects partial favorable movement.
- Adverse cut: force close when movement is heavily against trade.
- Stagnation exit: stop wasting cycle time in dead trades.

Purpose:
- reduce tail risk and improve trade throughput.

---

## 4.3 ML walk-forward logic (`src/ml_pipeline.py`)

### Why walk-forward instead of single split
- Prevents one-window overfitting.
- Simulates train-then-future-test rolling behavior.

### Why calibration threshold search exists
- Model output probabilities need threshold selection.
- Threshold chosen with expectancy-positive preference first.

### Why sequential non-overlap trade selection exists
- `_select_sequential_trades` blocks overlapping open windows.
- Purpose: mimic one-trade-at-a-time execution constraints.

### Why cost model is embedded
- Includes fee + slippage in `trade_cost_r`.
- Purpose: avoid inflated paper performance.

---

## 5) Line-By-Line Walkthrough For Core Operational Scripts

This section documents **every logical block** in core deployment/runtime scripts.

## 5.1 `deploy_ec2.sh` block-level documentation

1. `set -euo pipefail`
- Required for production safety.
- Fails fast on errors, unset vars, pipe failures.

2. Global env defaults (`SERVICE_NAME`, `RUN_USER`, `FRONTEND_*`, `MONGO_*`)
- Required to make script configurable without file edits.
- Enables same script across multiple EC2 instances/environments.

3. Helper functions: `log`, `have_cmd`, `as_root`
- Required for readable output and privilege-safe command execution.

4. `detect_pkg_mgr`
- Required to support Ubuntu/Debian (`apt`) and RHEL-like (`dnf`/`yum`) AMIs.

5. `install_base_packages`
- Installs runtime dependencies needed for deployment and operations.
- Includes `jq/lsof/curl` for diagnostics and existing scripts.

6. `install_docker_if_needed` + `ensure_local_mongo`
- Required when `MONGO_MODE=local`.
- Creates persistent MongoDB container (`crypto-mongo`) with restart policy.
- Uses `/var/lib/crypto-mongo` volume for persistence across restarts.

7. `ensure_python_env`
- Creates virtualenv and installs dependencies.
- Compiles all Python modules to catch syntax regressions before service boot.
- Validates shell scripts with `bash -n`.

8. `write_runtime_wrapper`
- Generates `start_production.sh` to export production env and call `run_all.sh`.
- Separates service unit from app-specific env logic.

9. `write_systemd_unit`
- Creates `/etc/systemd/system/crypto-trader.service`.
- `Restart=always` keeps app alive 24/7.
- `WantedBy=multi-user.target` enables startup on reboot.

10. `show_status`
- Prints immediate health and log pointers to confirm deployment success.

11. `main`
- Enforces order: package install -> Mongo -> python env -> wrapper -> service.
- Purpose: deterministic deploy path.

## 5.2 `run_all.sh` block-level documentation

1. Initialization and env defaults
- Centralizes run-time behavior toggles (`SKIP_OPTIMIZE`, `RETUNE_FROM_EVENTS`, `MONGO_*`).

2. Process cleanup (`stop_existing_processes`)
- Prevents stale orphan workers and port collisions.

3. Python bootstrapping (`ensure_python`, `ensure_venv_and_deps`)
- Allows first-run on clean machines and repeatable dependencies.

4. Frontend startup (`start_frontend`)
- Clears/rotates event files and starts dashboard API/static server.

5. Market cache refresh (`fetch_live_cache.sh`)
- Seeds optimizer with latest market snapshots.

6. Optimizer phase (`run_optimizer_with_progress`)
- Runs walk-forward optimization with progress heartbeat events.
- Enforces timeout so system does not stall before going live.

7. Threshold retune phase (`run_threshold_retune`)
- Uses historical trade outcomes to tune `live_loop` filters.

8. Live loop phase
- Runs `run_live_adaptive.py` and tees event stream to current + history files.

---

## 6) API And Runtime Event Contracts

## 6.1 Key live event types

- `LIVE_MARKET`
- `POSSIBLE_TRADES`
- `OPEN_TRADE`
- `TRADE_RESULT`
- `NO_SIGNAL`
- `LOSS_GUARD_SYMBOL_PAUSE`
- `LOSS_GUARD_GLOBAL_PAUSE`
- `GUARD_RETUNE`
- `EXECUTION_FILTER_RELAX`
- `RUNTIME_SYMBOLS_UPDATED`

Purpose:
- Human-readable + machine-parseable operational telemetry.

## 6.2 Frontend API endpoints (`frontend/server.py`)

- `GET /api/state` -> current live state snapshot
- `GET /api/history?limit=N` -> closed trade history
- `GET /api/health` -> service health
- `GET /api/storage` -> Mongo status
- `GET /api/options` -> selected/runtime symbol options
- `GET /api/symbols?q=...&limit=...` -> symbol catalog search
- `GET /api/news` -> aggregated market/news feed
- `POST /api/config/symbol` -> set single runtime symbol
- `POST /api/config/symbols` -> set runtime watchlist

---

## 7) Results Tracking And Interpretation

## 7.1 What metrics mean

- `win_rate`: proportion of winning closed trades.
- `expectancy_r`: average R-multiple per trade.
- `expectancy_usd_per_trade`: `expectancy_r * risk_usd_per_trade`.

Interpretation rule:
- High win-rate alone is insufficient.
- Positive expectancy is mandatory for long-run viability.

## 7.2 Why results can vary over time

- Regime shifts (trend/range/volatility)
- Symbol-specific behavior changes
- Timeout exits dominating outcomes
- Fees/slippage and microstructure drift

---

## 8) How To Deploy And Run 24/7

## 8.1 One-command EC2 deployment

```bash
cd /path/to/crypto
chmod +x deploy_ec2.sh
./deploy_ec2.sh
```

## 8.2 Service operations

```bash
sudo systemctl status crypto-trader
sudo journalctl -u crypto-trader -f
sudo systemctl restart crypto-trader
sudo systemctl stop crypto-trader
```

## 8.3 External Mongo deployment mode

```bash
MONGO_MODE=external MONGO_URI='mongodb://<host>:27017' MONGO_DB='crypto_trading_live' ./deploy_ec2.sh
```

---

## 9) Maintenance Runbook

## 9.1 Daily checks

1. Service alive: `systemctl status`
2. Log health: `journalctl -u crypto-trader -n 200`
3. Frontend health endpoint: `curl http://127.0.0.1:8787/api/health`
4. Mongo status: `curl http://127.0.0.1:8787/api/storage`

## 9.2 Weekly checks

1. Review rolling expectancy and per-symbol health.
2. Inspect frequent `NO_SIGNAL` reasons.
3. Validate cooldown/guard behavior is not permanently blocking symbols.
4. Re-run offline optimization and compare candidate drift.

## 9.3 Safe update procedure

1. Pull latest code.
2. Run compile and tests:

```bash
python3 -m py_compile $(find . -type f -name '*.py' -not -path './.venv/*')
python3 -m unittest discover -s tests -p 'test_*.py'
```

3. Restart service:

```bash
sudo systemctl restart crypto-trader
```

4. Confirm logs and API health.

---

## 10) Troubleshooting

## 10.1 No live data

Possible causes:
- DNS/network egress blocked
- Binance hosts temporarily unavailable
- firewall/security-group restrictions

Actions:
1. `curl https://fapi.binance.com/fapi/v1/ping`
2. Check EC2 outbound rules
3. Validate host DNS resolution

## 10.2 UI shows no trades

Possible causes:
- execution thresholds too strict
- `min_score_gap` rejecting close-ranked candidates
- global/symbol cooldown active

Actions:
1. Inspect `NO_SIGNAL` event reasons.
2. Inspect `summary.execute_min_*` and `global_pause_cycles_left`.
3. Retune thresholds or lower strictness cautiously.

## 10.3 Mongo issues

Possible causes:
- container down
- wrong URI
- permission/network issue

Actions:
1. `docker ps` / `docker logs crypto-mongo`
2. validate `MONGO_URI`
3. check `/api/storage`

---

## 11) Security And Operational Hardening Notes

1. Restrict EC2 security groups:
- expose dashboard port only to trusted IP/CIDR.

2. Run behind reverse proxy (recommended):
- Nginx with TLS and basic auth/JWT.

3. Secrets management:
- if future private APIs are introduced, use SSM Parameter Store / Secrets Manager.

4. Backups:
- backup Mongo volume (`/var/lib/crypto-mongo`) regularly.

5. Resource governance:
- monitor CPU/memory and log growth.
- rotate `/var/log/crypto-trader.log` with logrotate.

---

## 12) What This System Is Not

- Not a guaranteed-profit engine.
- Not a broker/exchange execution layer.
- Not a replacement for risk management discipline.

---

## 13) Current Known Trade-Offs

1. Timeout-based closing can increase small WIN/LOSS noise.
2. One-trade-at-a-time execution may skip parallel opportunities.
3. Probability estimate is calibrated heuristic, not full probabilistic model calibration.
4. Strategy remains indicator-based; regime models are lightweight.

---

## 14) Practical Improvement Roadmap

1. Add true hold-to-next-candle-close policy by timeframe unit.
2. Add per-symbol/per-timeframe model calibration persistence.
3. Add objective function combining downside deviation + expectancy.
4. Add structured experiment tracker for config/result lineage.
5. Add alerting integration (Telegram/Slack/webhooks).

---

## 15) Documentation Scope Note

This document explains:
- purpose
- architecture
- every major file/module and why it exists
- all core runtime/deployment blocks and their intent
- operations and maintenance end-to-end

If you want literal **line-by-line commentary for every single line in every file**, generate it in a separate `LINE_BY_LINE_REFERENCE.md` because it will be very large and harder to maintain than this primary operational handbook.
