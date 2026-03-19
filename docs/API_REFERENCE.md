# API Reference

Dashboard server runs on `http://127.0.0.1:8787` by default.

## Endpoints

### GET `/api/state`

Returns the current live trading state.

**Response:**
```json
{
  "signal": {
    "pair": "ETHUSDT",
    "side": "SHORT",
    "entry": 2157.27,
    "take_profit": 2139.33,
    "stop_loss": 2172.22,
    "confidence": 0.765,
    "timeframe": "15m",
    "signal_state": "OPEN",
    "signal_time": "2026-03-19T10:00:00Z",
    "rr": 1.2,
    "win_prob": 0.61,
    "score": 0.75,
    "ev_r": 0.46
  },
  "last_trade": {
    "symbol": "ETHUSDT",
    "side": "SHORT",
    "result": "WIN",
    "exit_price": 2139.33,
    "pnl_r": 1.2,
    "pnl_usd": 0.24,
    "closed_at": "2026-03-19T11:30:00Z"
  },
  "performance": {
    "status": "running",
    "trades": 3,
    "wins": 3,
    "losses": 0,
    "win_rate": 1.0,
    "expectancy_r": 1.04,
    "profit_factor": null,
    "active_symbols_count": 10,
    "blocked_symbols_count": 0
  },
  "possible_trades": [...],
  "probability_categories": {...},
  "snapshots": [...],
  "coin_activity": [...],
  "system_logs": [...],
  "guard_event": null
}
```

### GET `/api/analytics`

Returns computed analytics from trade history.

**Response:**
```json
{
  "total_trades": 45,
  "wins": 28,
  "losses": 17,
  "win_rate": 0.622,
  "profit_factor": 1.85,
  "expectancy_r": 0.32,
  "total_pnl_usd": 14.40,
  "max_drawdown_pct": 8.5,
  "best_streak": 5,
  "worst_streak": 3,
  "equity_curve": [0, 1.2, 0.92, 2.12, ...],
  "rolling_win_rate": [0.5, 0.6, 0.55, ...],
  "pnl_distribution": {"buckets": [...], "counts": [...]},
  "drawdown_curve": [0, 0, -0.28, 0, ...],
  "symbol_breakdown": {
    "ETHUSDT": {"trades": 12, "wins": 8, "pnl_r": 4.5},
    "BTCUSDT": {"trades": 8, "wins": 5, "pnl_r": 2.1}
  }
}
```

### GET `/api/history`

Returns closed trade history.

**Query params:** `?limit=200`

**Response:**
```json
{
  "trades": [
    {
      "closed_at": "2026-03-19T11:30:00Z",
      "symbol": "ETHUSDT",
      "timeframe": "15m",
      "side": "SHORT",
      "entry": 2157.27,
      "exit_price": 2139.33,
      "take_profit": 2139.33,
      "stop_loss": 2172.22,
      "result": "WIN",
      "pnl_r": 1.2,
      "pnl_usd": 0.24
    }
  ],
  "count": 45,
  "meta": "Showing 45 trades"
}
```

### GET `/api/news`

Returns aggregated crypto news headlines.

**Query params:** `?force=1` (bypass 5-min cache)

**Response:**
```json
{
  "updated": "2026-03-19T12:00:00Z",
  "items": [
    {
      "title": "Bitcoin Breaks $70K",
      "link": "https://...",
      "source": "CoinTelegraph",
      "published": "2026-03-19T11:45:00Z"
    }
  ]
}
```

### GET `/api/symbols`

Searches available Binance USDT perpetual symbols.

**Query params:** `?q=BTC&limit=10`

**Response:**
```json
{
  "symbols": ["BTCUSDT", "BTCDOMUSDT"],
  "count": 2
}
```

### GET `/api/storage`

Returns MongoDB connection status.

### GET `/api/health`

Health check endpoint.

### POST `/api/config/symbols`

Updates the runtime watchlist.

**Request body:**
```json
{
  "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
}
```

### POST `/api/config/symbol`

Sets a single active trading symbol.

**Request body:**
```json
{
  "symbol": "BTCUSDT"
}
```
