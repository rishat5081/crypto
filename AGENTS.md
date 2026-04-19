# AGENTS.md - AI Agent Handbook

> Current repo layout is service-oriented.
> Backend lives in `services/backend`.
> Frontend lives in `services/frontend`.

## Agent Quick Start

1. Read this file first.
2. Use the repo root `start.sh` as the main entrypoint.
3. Backend config is `services/backend/config.json`.
4. Run focused tests from `services/backend`.
5. Never commit secrets, API keys, `.env`, runtime files, or local caches.

## Current Structure

```text
/
├── start.sh
├── package.json
├── pnpm-workspace.yaml
├── services/
│   ├── backend/
│   │   ├── .env
│   │   ├── config.json
│   │   ├── requirements.txt
│   │   ├── pyproject.toml
│   │   ├── start.sh
│   │   ├── run_live_adaptive.py
│   │   ├── src/
│   │   └── tests/
│   └── frontend/
│       ├── package.json
│       ├── vite.config.js
│       ├── server.py
│       ├── index.html
│       └── src/
└── .github/workflows/
```

## Runtime Paths

- Root launcher: `start.sh`
- Backend launcher: `services/backend/start.sh`
- Backend config: `services/backend/config.json`
- Runtime event/control files: `/tmp/crypto-runtime`
- Persistent trade history: MongoDB

## Data Flow

```text
Binance Futures API
    ↓
services/backend/src/binance/futures_rest.py
    ↓
services/backend/src/strategies/structure/engine.py
    ↓
services/backend/src/live_trader/core.py
    ↓
/tmp/crypto-runtime/live_events.jsonl
    ↓
services/frontend/server.py
    ↓
services/frontend/index.html + services/frontend/src/*
```

## Core Backend Modules

- `services/backend/src/models/`
- `services/backend/src/indicators.py`
- `services/backend/src/strategies/structure/`
- `services/backend/src/trade_engine.py`
- `services/backend/src/live_trader/`
- `services/backend/src/binance/`
- `services/backend/src/ml/`
- `services/backend/src/config/`

## Invariants

1. `ClosedTrade.result` must reflect real PnL direction.
2. When TP and SL hit in the same candle, SL wins.
3. Only one open trade at a time unless code explicitly changes that invariant.
4. JSON event output must stay valid line-by-line JSON.
5. Execution filters must not become impossible to satisfy without a relaxation path.
6. `original_stop_loss` must remain intact for risk accounting.

## Frontend/Backend Boundary

- Frontend persistence and analytics should rely on MongoDB.
- Temporary runtime event stream is allowed in `/tmp/crypto-runtime`.
- Do not reintroduce persistent JSONL history inside the repo.
- Backend should not assume frontend files are inside `services/backend`.

## File Modification Guide

| If you're changing... | Also update... |
|---|---|
| Backend strategy logic | `services/backend/tests/test_strategy.py` |
| Trade lifecycle / exits | `services/backend/tests/test_trade_engine.py`, `services/backend/tests/test_live_adaptive_trader.py` |
| Backend config shape | `services/backend/tests/test_config.py` |
| Frontend server endpoints | `services/backend/tests/test_frontend_server.py` |
| Frontend UI | `services/frontend/src/*`, `services/frontend/index.html` if needed |
| Root/startup flow | `start.sh`, `services/backend/start.sh`, workflows |

## Standard Commands

### Backend

```bash
cd services/backend
pytest tests/ -v
python -c "import json; json.load(open('config.json'))"
python run_live_adaptive.py --config config.json
```

### Frontend

```bash
pnpm install
pnpm frontend:build
pnpm frontend:dev
```

### Full stack

```bash
./start.sh
```

## Notes For Agents

- Prefer editing the moved service paths, not the deleted legacy paths.
- Treat `services/backend/.env` as secret.
- Ignore `services/frontend/node_modules` and compiled caches.
- If updating workflows, keep root as the GitHub Actions checkout root, but use `services/backend` or `services/frontend` as working directories as appropriate.
