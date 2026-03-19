# Architecture Reference

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Browser Dashboard                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │ Overview  │ │Analytics │ │  Market  │ │  History   │  │
│  │  Cards    │ │ Charts   │ │  Prices  │ │  Table     │  │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘  │
│  Chart.js ─── app.js ─── Polling every 2-10s             │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP
┌───────────────────────▼─────────────────────────────────┐
│              Dashboard Server (server.py:8787)            │
│                                                           │
│  ┌─────────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ LiveStateCache   │  │AnalyticsEngine│  │ NewsFetcher│  │
│  │ reads JSONL      │  │equity, DD,   │  │ RSS feeds  │  │
│  │ caches state     │  │PnL, streaks  │  │ cached 5m  │  │
│  └─────────────────┘  └──────────────┘  └────────────┘  │
│  ┌─────────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ TradeHistoryCache│  │SymbolCatalog │  │ MongoStore │  │
│  │ from history.jsonl│  │CoinGecko API│  │ optional   │  │
│  └─────────────────┘  └──────────────┘  └────────────┘  │
└───────────────────────┬─────────────────────────────────┘
                        │ reads
┌───────────────────────▼─────────────────────────────────┐
│              data/live_events.jsonl                       │
│              data/live_events_history.jsonl               │
└───────────────────────▲─────────────────────────────────┘
                        │ writes (JSON Lines stdout)
┌───────────────────────┴─────────────────────────────────┐
│           LiveAdaptivePaperTrader.run()                   │
│                                                           │
│  ┌───────────────────────────────────────────────────┐   │
│  │ Signal Generation                                  │   │
│  │  StrategyEngine.evaluate()                         │   │
│  │  ├─ EMA crossover detection                        │   │
│  │  ├─ Pullback entry (price near fast EMA)           │   │
│  │  └─ Momentum entry (strong trend continuation)     │   │
│  └───────────────────────────────────────────────────┘   │
│  ┌───────────────────────────────────────────────────┐   │
│  │ Execution Pipeline                                 │   │
│  │  _signal_candidates() → filter → rank → select     │   │
│  │  Filters: confidence, expectancy, score, win prob   │   │
│  └───────────────────────────────────────────────────┘   │
│  ┌───────────────────────────────────────────────────┐   │
│  │ Trade Monitor (_wait_for_close)                    │   │
│  │  ├─ TP/SL check via TradeEngine.on_candle()       │   │
│  │  ├─ Trailing stop (0.5R trigger, 85% keep)        │   │
│  │  ├─ Break-even stop (0.8R trigger)                │   │
│  │  ├─ Momentum reversal exit (3 bars, -0.4R)        │   │
│  │  ├─ Stagnation exit (6 bars, <0.1R)               │   │
│  │  ├─ Candle timeout (12 candles)                    │   │
│  │  └─ Network error protection (5 failures)          │   │
│  └───────────────────────────────────────────────────┘   │
│  ┌───────────────────────────────────────────────────┐   │
│  │ Feedback & Guards                                  │   │
│  │  _apply_feedback() → adjust thresholds             │   │
│  │  _apply_loss_guard() → pause after loss streaks    │   │
│  │  _apply_performance_guard() → cool down symbols    │   │
│  │  _maybe_relax_execution_filters() → prevent lockout│   │
│  └───────────────────────────────────────────────────┘   │
└───────────────────────┬─────────────────────────────────┘
                        │ REST API (public, no auth)
┌───────────────────────▼─────────────────────────────────┐
│              Binance Futures API                          │
│  fapi.binance.com / fapi1.binance.com / fapi2.binance.com│
│                                                           │
│  /fapi/v1/klines          → OHLCV candles                │
│  /fapi/v1/premiumIndex    → Funding rate, mark price     │
│  /fapi/v2/ticker/price    → Latest prices                │
└─────────────────────────────────────────────────────────┘
```

## Module Dependencies

```
models.py           ← No dependencies (pure data classes)
indicators.py       ← models.py (Candle type)
strategy.py         ← indicators.py, models.py
trade_engine.py     ← models.py
mock_data.py        ← models.py
binance_futures_rest.py ← models.py, mock_data.py
ml_pipeline.py      ← models.py, indicators.py
live_adaptive_trader.py ← ALL above modules
```

## Data Models

```
Candle (frozen)
├── open_time_ms: int      # Candle open timestamp (ms)
├── open: float
├── high: float
├── low: float
├── close: float
├── volume: float
└── close_time_ms: int     # Candle close timestamp (ms)

Signal (frozen)
├── symbol: str            # e.g., "BTCUSDT"
├── timeframe: str         # e.g., "15m"
├── side: str              # "LONG" or "SHORT"
├── entry: float
├── take_profit: float
├── stop_loss: float
├── confidence: float      # 0.0 to 0.99
├── reason: str            # Human-readable signal description
└── signal_time_ms: int

OpenTrade (mutable)
├── [same fields as Signal minus reason/confidence]
├── original_stop_loss: float   # Preserved for PnL calculation
└── update_with_candle() → Optional[ClosedTrade]

ClosedTrade (frozen)
├── [same fields as OpenTrade]
├── exit_price: float
├── result: str            # "WIN" or "LOSS"
├── pnl_r: float           # PnL in R-multiples
├── pnl_usd: float
└── reason: str            # Exit reason prefix + signal reason
```

## Configuration Schema

See `config.json` for current values. Key sections:

- `account` - Balance and risk sizing
- `execution` - Fee and slippage model
- `strategy` - Indicator periods, ATR multiplier, RSI ranges
- `live_loop` - Symbols, timeframes, execution filters, risk management, guards
- `data_source` - Mock/live data toggle
- `ml` / `audit` - Historical optimization results
