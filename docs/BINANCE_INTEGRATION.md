# Binance Futures API Integration

## Overview

This system integrates with Binance Futures (USDT-M) to place real orders on a **demo or live** account. When the signal engine selects a trade for execution, the system automatically opens a position on Binance and closes it when exit conditions are met.

## Architecture

```
Signal Engine ─────────────────────────────────────────────────────
  │
  ├─ _signal_candidates()         Generate signals across all symbols
  ├─ Execution filters            Confidence, score, expectancy gates
  │
  ├─ OPEN_TRADE event             Signal selected for execution
  │   └─ BinanceExecutor.open_trade()    ← MARKET order placed
  │       └─ LIMIT TP order placed       ← Take-profit limit order
  │
  ├─ _wait_for_close()            Monitor candles for TP/SL/exit
  │   ├─ Trailing stop
  │   ├─ Break-even stop
  │   ├─ Adverse cut
  │   ├─ Stagnation exit
  │   └─ Timeout exit
  │
  └─ TRADE_RESULT event           Trade closed
      └─ BinanceExecutor.close_trade()   ← MARKET close + cancel orders
```

## Setup

### 1. Get API Keys

**Demo Account (Recommended for testing):**
1. Go to `demo.binance.com`
2. Log in with your Binance account
3. Navigate to API Management
4. Create API key — you get fake USDT to trade with

**Live Account:**
1. Go to `binance.com` → Account → API Management
2. Create API with Futures permission
3. Enable IP whitelist for security
4. Do NOT enable withdrawal permission

### 2. Configure Environment

Create a `.env` file in the project root:

```bash
BINANCE_API_KEY=your_api_key_here
BINANCE_SECRET_KEY=your_secret_key_here
BINANCE_DEMO=1
```

| Variable | Description |
|----------|-------------|
| `BINANCE_API_KEY` | Your Binance API key |
| `BINANCE_SECRET_KEY` | Your Binance secret key |
| `BINANCE_DEMO` | `1` for testnet/demo, `0` for live production |

The `.env` file is gitignored and never committed.

### 3. Install Dependencies

```bash
pip install requests python-dotenv
```

Or simply run `./start.sh` which installs everything automatically.

### 4. Launch

```bash
./start.sh
```

The system will:
1. Load `.env` and export Binance keys
2. Initialize the `BinanceExecutor` with live account balance
3. Start scanning for signals
4. Place orders automatically when signals pass execution filters

## How It Works

### Order Execution Flow

1. **Signal detected** — Strategy engine finds a qualifying trade
2. **Filters passed** — Confidence, score, expectancy, win probability all meet thresholds
3. **Position opened** — `MARKET` order sent to Binance
4. **TP limit placed** — `LIMIT` order at take-profit price (GTC, reduce-only)
5. **Engine monitors** — Candle-by-candle TP/SL/trailing/exit checks
6. **Position closed** — All open orders cancelled, `MARKET` close order sent

### Position Sizing

```
risk_per_trade = account_balance * risk_per_trade_pct (default 2%)
quantity = risk_per_trade / abs(entry - stop_loss)
```

Constraints applied:
- Minimum notional value (varies per symbol, e.g. $100 for BTC, $5 for SOL)
- Maximum position capped at 20% of account balance
- Quantity rounded to symbol's step size and precision

### Supported Order Types

| Order | Type | When |
|-------|------|------|
| Entry | MARKET | Signal executes |
| Take Profit | LIMIT (GTC, reduce-only) | Placed alongside entry |
| Stop Loss | Engine-managed | Monitored via candle data |
| Close | MARKET (reduce-only) | Any exit condition triggers |

Note: The Binance testnet does not support `STOP_MARKET` or `TAKE_PROFIT_MARKET` order types. Stop-loss is managed by the engine's candle-based monitoring system, which checks TP/SL on each new candle.

## Files

| File | Purpose |
|------|---------|
| `src/binance_executor.py` | Binance API client — order placement, position management |
| `src/live_adaptive_trader.py` | Integration hooks — opens/closes via executor |
| `.env` | API credentials (gitignored) |
| `start.sh` | Loads `.env`, launches full system |

## API Endpoints Used

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/fapi/v2/account` | Account balance and positions |
| GET | `/fapi/v2/positionRisk` | Check open positions |
| GET | `/fapi/v1/exchangeInfo` | Symbol precision, min notional |
| GET | `/fapi/v1/ticker/price` | Current market price |
| POST | `/fapi/v1/order` | Place MARKET/LIMIT orders |
| DELETE | `/fapi/v1/allOpenOrders` | Cancel all open orders for symbol |

## Dashboard Integration

### Trades Page
- **Green banner**: "Placed on Binance — Qty: X | Entry: Y | Notional: $Z" when trade is live on Binance
- **Yellow banner**: "Paper trade only — not placed on Binance" when executor is disabled
- **Live price** shown for active trades

### History Page
- **Binance column**: Shows "Yes" (green) or "No" (grey) for each trade
- Indicates whether the trade was executed on Binance or paper-only

## Safety Guards

1. **Duplicate protection** — Won't open a second position on the same symbol
2. **Reduce-only closes** — Close orders use `reduceOnly=true` to prevent accidental new positions
3. **Order cancellation** — All open orders cancelled before closing position
4. **Max position cap** — 20% of account balance per trade
5. **Graceful degradation** — If Binance API fails, the engine continues paper trading
6. **No withdrawal permission** — API keys should never have withdrawal enabled

## Switching from Demo to Live

1. Get live API keys from `binance.com`
2. Update `.env`:
   ```
   BINANCE_API_KEY=live_key
   BINANCE_SECRET_KEY=live_secret
   BINANCE_DEMO=0
   ```
3. Restart `./start.sh`

**WARNING**: Setting `BINANCE_DEMO=0` uses real money. Ensure your strategy is thoroughly tested on demo first.

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| No orders placed | `python-dotenv`/`requests` not in venv | Run `pip install python-dotenv requests` |
| "executor disabled" | Missing API keys in `.env` | Check `.env` exists and has correct keys |
| "Order's notional must be no smaller than X" | Position too small | Executor auto-adjusts; check account balance |
| Trades show but no Binance column | Old events before integration | Only new trades will show Binance status |
| TP limit fails | Testnet price mismatch | Expected on testnet; entry still executes via MARKET |
