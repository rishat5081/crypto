# AGENTS.md - AI Agent Handbook

> This file provides structured context for AI coding agents working on this project.
> It covers architecture, data flow, invariants, and how to safely make changes.

## Agent Quick Start

1. Read `CLAUDE.md` first for project overview
2. Read this file for deep technical context
3. Run `pytest tests/ -v` before and after any change
4. Never commit secrets, API keys, or large data files
5. Output format is JSON Lines — every bot output line must be valid JSON

## System Architecture

### Data Flow

```
Binance Futures API
    │
    ├─ /fapi/v1/klines          → List[Candle]
    ├─ /fapi/v1/premiumIndex    → MarketContext (mark_price, funding_rate, open_interest)
    └─ /fapi/v1/ticker/price    → float (latest price)
    │
    ▼
BinanceFuturesRestClient (src/binance_futures_rest.py)
    │  - Retries across 3 base URLs
    │  - Falls back to curl subprocess
    │  - Optional mock data fallback
    │
    ▼
StrategyEngine.evaluate() (src/strategy.py)
    │  - Computes EMA(21), EMA(55), RSI(14), ATR(14)
    │  - Detects: crossover / pullback / momentum
    │  - Calculates confidence from weighted components
    │  - Returns Signal with entry, TP, SL
    │
    ▼
LiveAdaptivePaperTrader (src/live_adaptive_trader.py)
    │  - Ranks candidates by score
    │  - Applies execution filters
    │  - Opens best trade via TradeEngine
    │  - Monitors via _wait_for_close()
    │  - Records result, applies feedback
    │
    ▼
JSON Lines stdout → data/live_events.jsonl
    │
    ▼
Dashboard Server (frontend/server.py)
    │  - Reads JSONL, caches state
    │  - Serves REST API
    │  - Optional MongoDB persistence
    │
    ▼
Browser Dashboard (frontend/index.html + app.js)
    - Polls /api/state every 2 seconds
    - Polls /api/analytics every 10 seconds
    - Chart.js for equity, win rate, PnL distribution, drawdown
```

### Class Hierarchy

```
Models (src/models.py) — All frozen dataclasses except OpenTrade
├── Candle          (open_time_ms, open, high, low, close, volume, close_time_ms)
├── MarketContext   (mark_price, funding_rate, open_interest)
├── Signal          (symbol, timeframe, side, entry, take_profit, stop_loss, confidence, reason, signal_time_ms)
├── ClosedTrade     (symbol, timeframe, side, entry, take_profit, stop_loss, exit_price, result, opened_at_ms, closed_at_ms, pnl_r, pnl_usd, reason)
└── OpenTrade       (mutable — stop_loss can be updated by trailing/break-even)
    └── update_with_candle(candle, risk_usd) → Optional[ClosedTrade]

StrategyEngine (src/strategy.py)
├── from_dict(payload) → StrategyEngine     # Factory
├── evaluate(symbol, tf, candles, market) → Optional[Signal]
└── adaptive_tune_after_trade(result)

TradeEngine (src/trade_engine.py)
├── maybe_open_trade(signal) → bool
└── on_candle(candle) → Optional[ClosedTrade]

LiveAdaptivePaperTrader (src/live_adaptive_trader.py)
├── run() → Dict                            # Main entry
├── _signal_candidates() → List[CandidateSignal]
├── _wait_for_close(signal) → ClosedTrade
├── _apply_feedback(trade)
├── _apply_loss_guard(trade, cycle)
├── _apply_performance_guard(cycle)
└── _maybe_relax_execution_filters(cycle, count)
```

## Invariants (Do NOT Break These)

1. **`ClosedTrade.result` must reflect actual PnL**: If `pnl_r > 0`, result MUST be "WIN". This is enforced in `models.py:OpenTrade.update_with_candle()`.

2. **Conservative fill order**: When both TP and SL are touched in the same candle, SL takes priority (assume worst case). This is in `models.py` lines 78-101.

3. **One active trade at a time**: `TradeEngine.maybe_open_trade()` returns False if a trade is already open. The live loop processes one trade per cycle.

4. **All bot output must be valid JSON Lines**: Every `print()` in `live_adaptive_trader.py` uses `json.dumps()`. Dashboard server parses these lines.

5. **Execution filters must have relaxation floors**: If tightening makes filters unreachable, `_maybe_relax_execution_filters()` gradually lowers them back. Without this, the bot enters permanent "no trade" mode.

6. **Feedback steps must be small**: Loss tightening uses tiny increments (e.g., +0.0015 confidence) to prevent filter lockout. Never increase these significantly.

7. **`original_stop_loss` must be preserved**: `OpenTrade.__post_init__` saves the original SL. PnL calculation uses `original_stop_loss` for the risk denominator, even after trailing/break-even modify `stop_loss`.

## Confidence Formula

```python
confidence = 0.10                          # Baseline
           + (0.40 * trend_score)          # EMA separation / 0.002, clamped [0,1]
           + (0.20 * rsi_score)            # Distance from RSI sweet spot
           + (0.18 * vol_score)            # ATR position in allowed range
           + (0.12 * funding_score)        # Low funding = high score

# Then multiplied by signal type discount:
# Crossover: 1.0x | Pullback: 0.92x | Momentum: 0.88x
```

## Score Formula

```python
score = ((confidence * 0.65)
       + (trend_strength * 100.0 * 0.25)
       + ((rr - cost_r) * 0.10))
       * symbol_quality
```

## Win Probability Estimation

```python
setup_quality = (conf_component * 0.40) + (exp_component * 0.25)
              + (trend_component * 0.15) + (quality_component * 0.12) + (rr_component * 0.08)

blended = (setup_quality * 0.60) + (actual_symbol_win_rate * 0.40)
calibrated = (blended * 0.92) + 0.02
```

## Exit Types (in priority order within _wait_for_close)

| Exit | Trigger | Typical PnL |
|------|---------|-------------|
| TP Hit | Price reaches take_profit | +1.2R (full RR) |
| SL Hit | Price reaches stop_loss | -1.0R |
| Trailing Stop | SL moved into profit, then hit | +0.4 to +1.0R |
| Adverse Cut | Worst intra-candle price exceeds max_adverse_r_cut (1.1R) | -1.1R |
| Momentum Reversal | 3+ consecutive adverse bars AND now_r < -0.4R | -0.2 to -0.5R |
| Stagnation | 6+ bars with best_r < 0.1R | ~0R |
| Candle Timeout | 12 candles elapsed | varies |
| Network Error | 5 consecutive API failures | varies |
| Time Timeout | Hard safety cap (180 min) | varies |

## Frontend Dashboard Sections

| Section ID | Tab Name | Data Source |
|-----------|----------|-------------|
| `sect-overview` | Overview | `/api/state` |
| `sect-analytics` | Analytics | `/api/analytics` |
| `sect-opportunities` | Opportunities | `/api/state` (possible_trades) |
| `sect-market` | Market | `/api/state` (snapshots) |
| `sect-activity` | Activity | `/api/state` (logs) |
| `sect-history` | History | `/api/history` |
| News sidebar | Market News | `/api/news` |
| Guard sidebar | Guard Monitor | `/api/state` (guard events) |

## JSON Event Types (stdout output)

| Type | When | Key Fields |
|------|------|-----------|
| `LIVE_MARKET` | Every cycle | `snapshots[]` with symbol, price |
| `POSSIBLE_TRADES` | Every cycle | `trades[]`, `probability_categories` |
| `OPEN_TRADE` | Trade opened | symbol, side, entry, tp, sl, confidence, score |
| `TRADE_RESULT` | Trade closed | `trade{}` (ClosedTrade), `summary{}` |
| `NO_SIGNAL` | No trade taken | `reason` (NO_CANDIDATES, EXECUTION_FILTER_BLOCK, etc.) |
| `RISK_MANAGER_UPDATE` | SL modified | `action` (TRAILING_STOP_*, STOP_TO_BREAKEVEN, MOMENTUM_REVERSAL_EXIT) |
| `LOSS_GUARD_SYMBOL_PAUSE` | Symbol paused | symbol, cooldown_cycles |
| `LOSS_GUARD_GLOBAL_PAUSE` | Global pause | global_pause_cycles_left |
| `GUARD_RETUNE` | Thresholds adjusted | direction (TIGHTEN/RELAX), previous, updated |
| `EXECUTION_FILTER_RELAX` | Filters relaxed | before, after values |
| `TRADE_MONITOR_FETCH_ERROR` | API failure during trade | symbol, error, consecutive_errors |

## Testing Checklist

Before any PR:
```bash
pytest tests/ -v                    # All 33 tests must pass
python -c "import json; json.load(open('config.json'))"  # Config valid
python -c "from src.strategy import StrategyEngine; from src.trade_engine import TradeEngine"  # Imports OK
```

## File Modification Guide

| If you're changing... | Also update... |
|----------------------|---------------|
| Signal generation logic | `tests/test_strategy.py`, CLAUDE.md signal types |
| Trade exit logic | `tests/test_trade_engine.py` if TP/SL logic changes |
| Config parameters | `tests/test_config.py` if new required keys |
| API endpoints | `frontend/app.js` polling functions |
| Dashboard HTML structure | `frontend/styles.css` + `frontend/app.js` |
| Models (dataclass fields) | All files that import from models.py |
