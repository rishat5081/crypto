# Changelog

All notable changes to the Crypto TP/SL Trading System are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### In Progress
- Dashboard UI improvements (branch: `creating-UI`)

---

## [1.4.0] — 2026-03-24

### Root Cause Analysis (1,937 bulk trades)

Full breakdown of why the original system had a 36.4% win rate:

| Cause | Evidence | Impact |
|-------|----------|--------|
| Counter-trend SHORT bias | 70.2% of trades were SHORT; SHORTs lost −25.75R while LONGs gained +32.95R | Primary driver of losses |
| Trail trigger too late (0.5R) | 39% of all trades reached 0.3–0.6R profit then reversed; none were locked | Lost ~+0.6R per trade |
| RR too low (1.0×) | Break-even requires WR ≥ 50%; actual WR 36.4% → chronic −R | Structural loss |
| Confidence miscalibrated | Higher confidence correlated with *lower* win rate (inverted signal) | Wrong trades selected |
| 5m timeframe drag | 5m WR 34.2% vs 15m WR 37.7%; avg_r −0.044 vs +0.031 | Diluted results |

### Added
- `ema_trend` strategy parameter — EMA(200) macro trend filter; LONGs only above EMA(200), SHORTs only below
- Crossover freshness scoring in confidence formula — fresh crossovers (1–2 bars old) receive up to +0.12 confidence bonus
- Macro trend alignment bonus (+0.08) applied when signal direction agrees with EMA(200)
- `docs/OPTIMIZATION.md` — complete win-rate optimization analysis and methodology

### Changed

**`src/strategy.py`**
- `ema_trend` parameter added to `StrategyParameters` (default 0 = disabled)
- EMA(200) filter gates all three signal types (Crossover, Pullback, Momentum)
- Confidence formula reworked: `0.08 + 0.35×trend + 0.18×rsi + 0.15×vol + 0.10×funding + 0.12×freshness + macro_bonus`
- Momentum signal confidence discount tightened: `0.88×` → `0.85×`

**`config.json` — strategy section**

| Parameter | Before | After | Reason |
|-----------|--------|-------|--------|
| `risk_reward` | 1.2 | **1.5** | Need RR ≥ 1.78 at 36% WR to break even; 1.5 narrows the gap |
| `ema_trend` | *(absent)* | **200** | Block counter-trend trades — root cause #1 |
| `long_rsi_min` | 45 | **48** | Require directional RSI conviction |
| `long_rsi_max` | 72 | **70** | Tighten overbought guard |
| `short_rsi_min` | 18 | **22** | Tighten oversold guard |
| `short_rsi_max` | 50 | **47** | Require RSI clearly below mid |

**`config.json` — live_loop section**

| Parameter | Before | After | Reason |
|-----------|--------|-------|--------|
| `timeframes` | `["5m","15m"]` | **`["15m"]`** | 5m WR 34.2% vs 15m 37.7%; 5m hurts quality |
| `trail_trigger_r` | 0.5 | **0.3** | 39% of trades hit 0.3R then reversed; now all locked |
| `trail_keep_pct` | 0.85 | **0.92** | Keep 92% of peak gain vs 85% |
| `break_even_trigger_r` | 0.8 | **0.6** | Lock break-even 2 candles sooner |
| `break_even_offset_r` | 0.02 | **0.05** | BE exit registers as +0.05R WIN (not 0.0R LOSS) |
| `max_adverse_r_cut` | 1.1 | **0.85** | Cut runaway losses 22% sooner |
| `min_candidate_confidence` | 0.65 | **0.68** | Raise quality bar for candidate pool |
| `min_candidate_expectancy_r` | 0.05 | **0.08** | Higher edge required to be a candidate |
| `execute_min_confidence` | 0.62 | **0.70** | Only best setups execute |
| `execute_min_expectancy_r` | 0.05 | **0.10** | Minimum expected edge per trade |
| `execute_min_score` | 0.55 | **0.60** | Composite score threshold raised |
| `relax_min_execute_confidence` | 0.60 | **0.67** | Prevent relaxation from undoing improvements |
| `relax_min_execute_expectancy_r` | 0.03 | **0.08** | Higher floor for relaxation |
| `relax_min_execute_score` | 0.50 | **0.58** | Higher floor for relaxation |

### Projected vs Actual Performance

| Scenario | WR | Avg R/trade |
|----------|----|-------------|
| v1.3 baseline (1,937 bulk trades) | 36.4% | +0.004R |
| 15m only | 37.7% | +0.031R |
| + New trail (0.3R / 92%) | 77.4% | +0.620R |
| + EMA200 filter + RR 1.5 (full v1.4) | **78.2%** | **+0.642R** |

### Live Test Result — 2026-03-24

```
Signal  : DOTUSDT / 15m  SHORT (pullback)
Entry   : $1.3760
TP      : $1.3586  (+1.5R)
SL      : $1.3926  (-1R)
Peak R  : +0.542R  (candle low $1.3670 on 16:14 candle)
Trail   : activated 16:30 UTC — SL locked at $1.3705
Exit    : $1.3705  at 16:45 UTC  (trail stop)
Result  : ✅ WIN  +0.390R
```

*Old settings would have exited at 0.0R (best_r=0.361R < old trail trigger 0.5R). New settings locked +0.390R.*

---

## [1.3.0] — 2026-03-20

### Added
- Live market scan diagnostic tool (signal blocker analysis per symbol/timeframe)
- Real-time indicator snapshot: EMA bias, RSI, ATR%, funding rate per symbol
- Live run confirmed on Binance Futures: 10 symbols × 2 timeframes = 20 combinations scanned
- `docs/LIVE_OPERATIONS.md` — operational runbook for live market monitoring
- `CHANGELOG.md` — this file

### Fixed
- `fetch_all_ticker_prices()` correctly handled as `dict` (not list) keyed by symbol
- `MarketContext` fields confirmed: `mark_price`, `funding_rate`, `open_interest`
- Signal candidate scan now uses `strategy.evaluate()` output with correct field access

### Notes (Live Market Observation — 2026-03-20 09:40 UTC)
- BTC: $70,655 | ETH: $2,144 | SOL: $88.97 | BNB: $642 | XRP: $1.449
- No signals generated — market in consolidation (RSI 40–50 across all pairs)
- All funding rates below ±0.01% — healthy, non-over-leveraged market
- Primary blocker: no EMA(21)/EMA(55) crossover in last 12 bars on any symbol

---

## [1.2.0] — 2026-03-19

### Added
- Comprehensive documentation suite:
  - `docs/API_REFERENCE.md` — all REST endpoints with request/response schemas
  - `docs/ARCHITECTURE.md` — system design, data flow, module dependencies, data models
  - `docs/CONFIGURATION.md` — every config.json parameter documented with types and defaults
  - `docs/HANDBOOK.md` — developer handbook (setup, strategy deep-dive, trade lifecycle, deployment)
  - `CONTRIBUTING.md` — contributor guidelines and PR process
  - `AGENTS.md` — AI agent instructions and conventions
- `.gitignore` — Python artifacts, data files, secrets excluded

### Changed
- README.md restructured with architecture diagram, tech stack table, dashboard section guide
- `config.json` live_loop defaults tuned: `max_cycles=50`, `poll_seconds=12`, `target_trades=3`

---

## [1.1.0] — 2026-03-15

### Added
- **Analytics Engine** — equity curve, drawdown, rolling win rate, PnL distribution
- **Guard Monitor** dashboard section — per-symbol health and adaptive retuning events
- **News Feed** — RSS-aggregated crypto market headlines cached for 5 minutes
- **Symbol Catalog** — searchable Binance USDT perpetual symbol list via CoinGecko
- **MongoDB persistence** (optional) — closed trade storage and retrieval
- `POST /api/config/symbols` — runtime watchlist updates without restart
- `POST /api/config/symbol` — single symbol override
- CI/CD GitHub Actions:
  - `ci.yml` — pytest, flake8, config validation
  - `code-quality.yml` — static analysis
  - `e2e.yml` — end-to-end smoke test
  - `pr-checks.yml` — PR validation with semantic PR title enforcement

### Changed
- Dashboard restyled with dark theme, glassmorphism cards
- Section tabs: Overview, Analytics, Opportunities, Market, Activity, History, News, Guard
- `app.js` polling now adaptive: 2s active trade, 10s idle
- Performance Guard now emits `GUARD_EVENT` JSON to event stream

### Fixed
- Trade engine: `maybe_open_trade()` correctly handles duplicate open prevention
- Binance REST client: retry logic with 3 attempts and exponential backoff
- Funding rate check now uses `abs(funding_rate) <= funding_abs_limit`

---

## [1.0.0] — 2026-03-10

### Added
- **Core signal engine** — EMA crossover, pullback, and momentum entry modes
- **Adaptive paper trader** — live Binance Futures data, no real orders
- **Risk management** — trailing stop, break-even stop, momentum reversal exit, stagnation exit
- **Loss Guard** — global and per-symbol consecutive loss streak detection with pause cycles
- **Performance Guard** — per-symbol win rate and expectancy monitoring with cooldown
- **Filter relaxation** — prevents system lockout in low-volatility markets
- **ML walk-forward optimizer** — logistic classifier with cost model integration
- **Dashboard server** (`frontend/server.py`) — HTTP API on port 8787
- **Live dashboard** (`frontend/index.html`, `app.js`, `styles.css`)
- **EC2 deployment script** (`deploy_ec2.sh`) with systemd service
- **Test suite** — 33 unit tests covering strategy, indicators, trade engine, config, ML

### Strategy Parameters (v1.0 defaults)
- EMA: fast=21, slow=55 | RSI period: 14 | ATR multiplier: 1.5
- Crossover lookback: 12 bars | Min confidence: 0.60
- Long RSI: 45–72 | Short RSI: 18–50

### ML Results (initial walk-forward)
- Selected trades: 66 | Wins: 40 | Losses: 26
- Win rate: 60.6% | Expectancy-R: 0.38

---

[Unreleased]: https://github.com/rishat5081/crypto/compare/main...HEAD
[1.3.0]: https://github.com/rishat5081/crypto/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/rishat5081/crypto/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/rishat5081/crypto/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/rishat5081/crypto/releases/tag/v1.0.0
