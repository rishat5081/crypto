# Crypto Services Workspace

Service-oriented crypto trading workspace with a Python backend, a React/Vite frontend, MongoDB-backed dashboard history, and temporary runtime files under `/tmp/crypto-runtime`.

## Structure

```text
.
├── start.sh
├── package.json
├── pnpm-workspace.yaml
├── AGENTS.md
├── services/
│   ├── backend/
│   │   ├── .env
│   │   ├── config.json
│   │   ├── requirements.txt
│   │   ├── run_live_adaptive.py
│   │   ├── run_ml_walkforward.py
│   │   ├── run_retune_thresholds.py
│   │   ├── src/
│   │   └── tests/
│   └── frontend/
│       ├── package.json
│       ├── server.py
│       ├── index.html
│       ├── src/
│       └── dist/
└── .github/workflows/
```

## Runtime Model

- Root entrypoint: `./start.sh`
- Backend config: `services/backend/config.json`
- Backend secrets: `services/backend/.env`
- Temporary runtime files: `/tmp/crypto-runtime`
- Persistent trade history and dashboard analytics: MongoDB
- No repo-local `data/` storage is used for runtime state anymore

## Quick Start

### Full Stack

```bash
pnpm install
./start.sh --skip-optimize
```

Useful flags:

```bash
./start.sh --skip-optimize
./start.sh --no-frontend
./start.sh --no-browser
./start.sh --restart
```

### Backend Only

```bash
cd services/backend
python3 -m venv ../../.venv
source ../../.venv/bin/activate
pip install -r requirements.txt
pytest tests/ -v
python run_live_adaptive.py --config config.json
```

### Frontend Only

```bash
pnpm install
pnpm frontend:dev
pnpm frontend:build
```

## Commands

### Root

```bash
pnpm install
pnpm lint
pnpm frontend:dev
pnpm frontend:build
./start.sh
```

### Backend Validation

```bash
cd services/backend
pytest tests/ -v
python -c "import json; json.load(open('config.json'))"
python -m py_compile run_live_adaptive.py src/strategy.py src/live_adaptive_trader.py
```

## Backend Overview

Core backend modules:

- `services/backend/src/strategy.py`
- `services/backend/src/live_adaptive_trader.py`
- `services/backend/src/trade_engine.py`
- `services/backend/src/models.py`
- `services/backend/src/binance_futures_rest.py`
- `services/backend/src/binance_executor.py`
- `services/backend/src/ml_pipeline.py`
- `services/backend/src/config.py`

Primary backend scripts:

- `services/backend/run_live_adaptive.py`
- `services/backend/run_ml_walkforward.py`
- `services/backend/run_retune_thresholds.py`

## Frontend Overview

Frontend code lives in `services/frontend`:

- React/Vite app in `services/frontend/src`
- Python dashboard server in `services/frontend/server.py`
- Static entry in `services/frontend/index.html`

The frontend reads live runtime events from `/tmp/crypto-runtime/live_events.jsonl` and persistent trade history from MongoDB.

## Environment

Environment variables are loaded from `services/backend/.env`.

Common variables:

- `FRONTEND_HOST`
- `FRONTEND_PORT`
- `MONGO_URI`
- `MONGO_DB`
- `MONGO_REQUIRED`
- `CRYPTO_RUNTIME_DIR`
- `BINANCE_API_KEY`
- `BINANCE_SECRET_KEY`

## Testing

Main test suite:

```bash
cd services/backend
pytest tests/ -v
```

Focused examples:

```bash
cd services/backend
pytest tests/test_strategy.py -v
pytest tests/test_live_adaptive_trader.py -v
pytest tests/test_frontend_server.py -v
```

## GitHub Workflows

The workflows in `.github/workflows/` assume:

- repository root as checkout root
- backend jobs run from `services/backend`
- frontend jobs use root `pnpm`
- runtime artifacts are collected from `/tmp/crypto-runtime`

## Notes

- Use `AGENTS.md` as the project-specific AI handbook.
- Do not store runtime files in the repo.
- Do not commit `.env`, runtime caches, or generated frontend artifacts unless explicitly intended.
