#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
#  start.sh  —  One-command launcher for the full crypto signal system
#  Usage:  ./start.sh
#          ./start.sh --no-browser        (skip auto-open dashboard)
#          ./start.sh --skip-optimize     (faster startup, no ML step)
#          ./start.sh --no-frontend       (headless, trader only)
#          ./start.sh --restart           (alias: same behavior — always kills stale)
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/services/backend"

# ── Defaults ─────────────────────────────────────────────────────────
OPEN_BROWSER=1
SKIP_OPTIMIZE=0
START_FRONTEND=1

FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-8787}"
MONGO_URI="${MONGO_URI:-mongodb://127.0.0.1:27017}"
MONGO_DB="${MONGO_DB:-crypto_trading_live}"
MONGO_REQUIRED="${MONGO_REQUIRED:-0}"
AUTO_INSTALL_DEPS="${AUTO_INSTALL_DEPS:-1}"
OPTIMIZE_MAX_CANDIDATES="${OPTIMIZE_MAX_CANDIDATES:-6}"
OPTIMIZE_TIMEOUT_SEC="${OPTIMIZE_TIMEOUT_SEC:-45}"
HEARTBEAT_SEC="${HEARTBEAT_SEC:-5}"
RETUNE_FROM_EVENTS="${RETUNE_FROM_EVENTS:-0}"
RETUNE_LOOKBACK_TRADES="${RETUNE_LOOKBACK_TRADES:-300}"
RETUNE_MIN_TRADES="${RETUNE_MIN_TRADES:-20}"

# ── Parse args ───────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --no-browser)      OPEN_BROWSER=0 ;;
    --skip-optimize)   SKIP_OPTIMIZE=1 ;;
    --no-frontend)     START_FRONTEND=0 ;;
    --restart)         ;; # always kills stale, this is a no-op alias
  esac
done

# ── Load .env (Binance API keys etc) ─────────────────────────────────
if [ -f "$BACKEND_DIR/.env" ]; then
  set -a
  source "$BACKEND_DIR/.env"
  set +a
fi

# ── Paths ────────────────────────────────────────────────────────────
VENV_DIR="$ROOT_DIR/.venv"
CACHE_DIR="${CRYPTO_RUNTIME_DIR:-/tmp/crypto-runtime}/live"
FRONTEND_DIR="$ROOT_DIR/services/frontend"
FRONTEND_STATIC_DIR="$FRONTEND_DIR"
EVENTS_FILE="${CRYPTO_RUNTIME_DIR:-/tmp/crypto-runtime}/live_events.jsonl"
RUNTIME_CONTROL="${CRYPTO_RUNTIME_DIR:-/tmp/crypto-runtime}/runtime_control.json"
DASHBOARD_URL="http://$FRONTEND_HOST:$FRONTEND_PORT"
FRONTEND_PID=""
PYTHON_CMD=""

# ── Colour helpers ───────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
RED='\033[0;31m'; BLUE='\033[0;34m'; GREY='\033[0;90m'
BOLD='\033[1m'; RESET='\033[0m'

log()  { printf "${CYAN}[start]${RESET} %s\n" "$1"; }
ok()   { printf "${GREEN}[  OK ]${RESET} %s\n" "$1"; }
warn() { printf "${YELLOW}[ WARN]${RESET} %s\n" "$1"; }
err()  { printf "${RED}[ERROR]${RESET} %s\n" "$1"; }
sep()  { printf "${BOLD}%s${RESET}\n" "──────────────────────────────────────────────────────"; }

have_cmd() { command -v "$1" >/dev/null 2>&1; }

emit_event() {
  [ "$START_FRONTEND" != "1" ] && return
  local now; now="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf '{"type":"RUN_STAGE","time":"%s","stage":"%s","message":"%s"}\n' "$now" "$1" "$2" >> "$EVENTS_FILE"
}

# ── Banner ───────────────────────────────────────────────────────────
clear
printf "${BOLD}${CYAN}"
cat << 'BANNER'
  ╔══════════════════════════════════════════════════════╗
  ║       CRYPTO TP/SL  —  LIVE SIGNAL SYSTEM           ║
  ║       Binance Futures  |  Paper Trading Only         ║
  ╚══════════════════════════════════════════════════════╝
BANNER
printf "${RESET}\n"

# ── Kill stale processes ─────────────────────────────────────────────
sep
log "Stopping stale processes..."

kill_pattern() {
  local pids
  pids="$(pgrep -f "$1" 2>/dev/null || true)"
  [ -z "$pids" ] && return
  log "  Killing $2: $pids"
  kill $pids 2>/dev/null || true
  sleep 1
  pids="$(pgrep -f "$1" 2>/dev/null || true)"
  [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
}

kill_pattern "$BACKEND_DIR/run_live_adaptive.py" "live trader"
kill_pattern "$BACKEND_DIR/run_ml_walkforward.py" "optimizer"
kill_pattern "$FRONTEND_DIR/server.py"         "frontend server"

if have_cmd lsof; then
  STALE="$(lsof -ti tcp:$FRONTEND_PORT 2>/dev/null || true)"
  [ -n "$STALE" ] && { log "  Killing port $FRONTEND_PORT: $STALE"; kill $STALE 2>/dev/null || true; }
fi
sleep 1
ok "Clean slate"

# ── Pre-flight: Python ───────────────────────────────────────────────
sep
log "Pre-flight checks..."

if have_cmd python3; then
  PYTHON_CMD="$(command -v python3)"
else
  err "Python 3 not found. Install Python 3.11+ and retry."
  exit 1
fi
PY_VER=$("$PYTHON_CMD" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python $PY_VER"

if [ ! -f "$BACKEND_DIR/config.json" ]; then
  err "config.json not found in $BACKEND_DIR"
  exit 1
fi
"$PYTHON_CMD" -c "import json; json.load(open('$BACKEND_DIR/config.json'))" 2>/dev/null \
  && ok "config.json valid" \
  || { err "config.json is invalid JSON"; exit 1; }

# ── Virtual environment & deps ───────────────────────────────────────
sep
log "Setting up Python environment..."

if [ ! -d "$VENV_DIR" ]; then
  log "Creating virtual environment..."
  "$PYTHON_CMD" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
PYTHON_CMD="$(command -v python)"
ok "Virtual environment active"

if [ "$AUTO_INSTALL_DEPS" = "1" ]; then
  log "Installing/verifying dependencies..."
  pip install --quiet --upgrade pip setuptools wheel
  pip install --quiet -r "$BACKEND_DIR/requirements.txt"
  ok "Dependencies ready"
fi

# ── Build frontend (if package.json exists) ──────────────────────────
if [ "$START_FRONTEND" = "1" ] && [ -f "$FRONTEND_DIR/package.json" ]; then
  sep
  log "Building frontend..."
  if have_cmd pnpm; then
    (cd "$ROOT_DIR" && pnpm install --no-frozen-lockfile && pnpm frontend:build) \
      > /tmp/crypto_frontend_npm.log 2>&1
  elif have_cmd npm; then
    (cd "$FRONTEND_DIR" && npm install --silent && npm run build --silent) \
      > /tmp/crypto_frontend_npm.log 2>&1
  else
    err "pnpm or npm is required to build frontend but neither was found."
    exit 1
  fi
  if [ -f "$FRONTEND_DIR/dist/index.html" ]; then
    FRONTEND_STATIC_DIR="$FRONTEND_DIR/dist"
    ok "Frontend build ready (dist/)"
  else
    warn "Build didn't produce dist/index.html, using source files"
  fi
fi

# ── Prepare data dir ────────────────────────────────────────────────
mkdir -p "$(dirname "$EVENTS_FILE")" "$CACHE_DIR"
: > "$EVENTS_FILE"
rm -f "$RUNTIME_CONTROL"

# ── Start dashboard server ───────────────────────────────────────────
if [ "$START_FRONTEND" = "1" ]; then
  sep
  log "Starting dashboard server..."

  if [ -f "$FRONTEND_DIR/dist/index.html" ]; then
    FRONTEND_STATIC_DIR="$FRONTEND_DIR/dist"
  else
    FRONTEND_STATIC_DIR="$FRONTEND_DIR"
  fi

  "$PYTHON_CMD" "$FRONTEND_DIR/server.py" \
    --host "$FRONTEND_HOST" \
    --port "$FRONTEND_PORT" \
    --events-file       "$EVENTS_FILE" \
    --config-file       "$BACKEND_DIR/config.json" \
    --runtime-control-file "$RUNTIME_CONTROL" \
    --mongo-uri         "$MONGO_URI" \
    --mongo-db          "$MONGO_DB" \
    --mongo-required    "$MONGO_REQUIRED" \
    --static-dir        "$FRONTEND_STATIC_DIR" \
    > /tmp/crypto_frontend.log 2>&1 &
  FRONTEND_PID=$!
  sleep 2

  if kill -0 "$FRONTEND_PID" 2>/dev/null; then
    ok "Dashboard running  →  $DASHBOARD_URL  (pid $FRONTEND_PID)"
  else
    warn "Dashboard failed to start. Check /tmp/crypto_frontend.log"
    FRONTEND_PID=""
  fi

  # Auto-open browser
  if [ "$OPEN_BROWSER" = "1" ]; then
    sleep 1
    if have_cmd xdg-open; then
      xdg-open "$DASHBOARD_URL" 2>/dev/null || true
    elif have_cmd open; then
      open "$DASHBOARD_URL" 2>/dev/null || true
    fi
  fi
fi

emit_event "BOOTSTRAP" "Environment ready"

# ── Fetch live market cache (skipped — trader fetches on demand) ──────
sep
log "Skipping bulk cache fetch (trader fetches live data per cycle)"
ok "Cache step skipped"

# ── ML walk-forward optimization ─────────────────────────────────────
sep
if [ "$SKIP_OPTIMIZE" = "1" ]; then
  log "Skipping ML optimization (--skip-optimize)"
  emit_event "SKIP_OPTIMIZATION" "Skipped"
else
  log "Running ML walk-forward optimization (max ${OPTIMIZE_TIMEOUT_SEC}s)..."
  emit_event "OPTIMIZING" "Running ML walk-forward optimization"

  OPT_LOG="/tmp/crypto_optimizer.log"
  : > "$OPT_LOG"

  set +e
  OPT_TIMED_OUT=0
  python "$BACKEND_DIR/run_ml_walkforward.py" \
    --config "$BACKEND_DIR/config.json" \
    --cache-dir "$CACHE_DIR" \
    --timeframes 5m,15m \
    --target-trades 100 \
    --target-wins 60 \
    --max-candidates "$OPTIMIZE_MAX_CANDIDATES" \
    --max-candles 500 \
    --apply-best \
    > "$OPT_LOG" 2>&1 &
  OPT_PID=$!

  START_TS=$(date +%s)
  while kill -0 "$OPT_PID" 2>/dev/null; do
    ELAPSED=$(( $(date +%s) - START_TS ))
    log "  Optimizing... ${ELAPSED}s"
    emit_event "OPTIMIZING" "In progress (${ELAPSED}s)"
    if [ "$ELAPSED" -ge "$OPTIMIZE_TIMEOUT_SEC" ]; then
      OPT_TIMED_OUT=1
      kill "$OPT_PID" 2>/dev/null || true
      sleep 1
      kill -0 "$OPT_PID" 2>/dev/null && kill -9 "$OPT_PID" 2>/dev/null || true
      wait "$OPT_PID" 2>/dev/null || true
      warn "Optimization timed out after ${OPTIMIZE_TIMEOUT_SEC}s"
      emit_event "OPTIMIZATION_TIMEOUT" "Timed out after ${OPTIMIZE_TIMEOUT_SEC}s"
      break
    fi
    sleep "$HEARTBEAT_SEC"
  done
  wait "$OPT_PID" 2>/dev/null
  OPT_STATUS=$?
  set -e

  if [ -s "$OPT_LOG" ]; then
    cat "$OPT_LOG" >> "$EVENTS_FILE" 2>/dev/null || true
  fi
  if [ "${OPT_TIMED_OUT:-0}" -eq 1 ]; then
    warn "Optimization step timed out, continuing without updated walk-forward parameters"
  elif [ "${OPT_STATUS:-0}" -eq 0 ]; then
    ok "Optimization step done"
    emit_event "OPTIMIZATION_DONE" "Complete"
  else
    warn "Optimization failed (exit $OPT_STATUS), continuing with current strategy parameters"
    emit_event "OPTIMIZATION_FAILED" "Exit $OPT_STATUS, continuing"
  fi
fi

# ── Threshold retune from history ────────────────────────────────────
sep
if [ "$RETUNE_FROM_EVENTS" = "1" ]; then
  log "Retuning thresholds from trade history..."
  emit_event "RETUNING_THRESHOLDS" "Retuning from live history"

  RETUNE_LOG="/tmp/crypto_retune.log"
  : > "$RETUNE_LOG"
  set +e
  python "$BACKEND_DIR/run_retune_thresholds.py" \
    --config "$BACKEND_DIR/config.json" \
    --events-file "$EVENTS_FILE" \
    --lookback-trades "$RETUNE_LOOKBACK_TRADES" \
    --min-trades "$RETUNE_MIN_TRADES" \
    --apply > "$RETUNE_LOG" 2>&1
  RETUNE_STATUS=$?
  set -e

  if [ -s "$RETUNE_LOG" ]; then
    cat "$RETUNE_LOG" >> "$EVENTS_FILE" 2>/dev/null || true
  fi

  if [ "$RETUNE_STATUS" -eq 0 ]; then
    ok "Threshold retune done"
    emit_event "RETUNE_DONE" "Complete"
  else
    warn "Retune failed (exit $RETUNE_STATUS), continuing with current config"
    emit_event "RETUNE_FAILED" "Failed, continuing"
  fi
else
  log "Skipping threshold retune"
fi

# ── Ready banner ─────────────────────────────────────────────────────
sep
printf "${BOLD}${GREEN}"
printf "  LIVE SIGNAL MONITOR — streaming now\n"
[ "$START_FRONTEND" = "1" ] && printf "  Dashboard : $DASHBOARD_URL\n"
printf "  Press Ctrl+C to stop\n"
printf "${RESET}"
sep
printf "\n"

# ── Cleanup on exit ──────────────────────────────────────────────────
cleanup() {
  printf "\n"
  sep
  log "Shutting down..."
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  pkill -f "$BACKEND_DIR/run_live_adaptive.py" 2>/dev/null || true
  ok "Stopped. Bye!"
}
trap cleanup EXIT INT TERM

# ── Start trader — stream with coloured output ───────────────────────
emit_event "LIVE_TRADING" "Live adaptive paper-trading started"

python -u "$BACKEND_DIR/run_live_adaptive.py" --config "$BACKEND_DIR/config.json" --continuous \
| tee -a "$EVENTS_FILE" \
| python3 -u -c "
import sys, json

RESET  = '\033[0m';   BOLD   = '\033[1m'
GREEN  = '\033[0;32m'; RED    = '\033[0;31m'
YELLOW = '\033[1;33m'; CYAN   = '\033[0;36m'
BLUE   = '\033[0;34m'; GREY   = '\033[0;90m'

for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    try:
        obj = json.loads(raw)
    except Exception:
        print(GREY + raw + RESET, flush=True)
        continue

    t  = obj.get('type', '')
    ts = obj.get('time', '')[:19].replace('T', ' ')

    if t == 'LIVE_MARKET':
        snaps = obj.get('snapshots', [])
        prices = '  '.join(f\"{s['symbol']}: \${s['price']:,.2f}\" for s in snaps[:5])
        print(f'{GREY}[{ts}] PRICES  {prices}{RESET}', flush=True)

    elif t == 'POSSIBLE_TRADES':
        n     = obj.get('total_possible_trades', 0)
        cycle = obj.get('cycle', '?')
        bar   = chr(9608) * min(n, 20)
        colour = GREEN if n > 0 else YELLOW
        print(f'{colour}[{ts}] CYCLE {cycle:>3}  candidates={n}  {bar}{RESET}', flush=True)
        for trade in obj.get('trades', []):
            ic = chr(0x1F7E2) if trade['side'] == 'LONG' else chr(0x1F534)
            print(f\"  {ic} {trade['symbol']:<10} {trade['timeframe']:<5} \"
                  f\"{trade['side']:<5}  entry={trade['entry']:.4f}  \"
                  f\"conf={trade['confidence']:.3f}  score={trade['score']:.3f}  \"
                  f\"exp-R={trade['expectancy_r']:.3f}\", flush=True)

    elif t == 'TRADE_OPEN':
        trade = obj.get('trade', obj)
        ic = chr(0x1F7E2) if trade.get('side') == 'LONG' else chr(0x1F534)
        print(f'\n{BOLD}{GREEN}[{ts}] ▶ TRADE OPEN{RESET}', flush=True)
        print(f\"  {ic} {trade.get('symbol')} / {trade.get('timeframe')}  {trade.get('side')}\", flush=True)
        print(f\"     Entry  : \${trade.get('entry', 0):,.4f}\", flush=True)
        print(f\"     TP     : \${trade.get('take_profit', 0):,.4f}\", flush=True)
        print(f\"     SL     : \${trade.get('stop_loss', 0):,.4f}\", flush=True)
        print(f\"     Conf   : {trade.get('confidence', 0):.3f}\n\", flush=True)

    elif t == 'TRADE_RESULT':
        trade  = obj.get('trade', {})
        res    = trade.get('result', '?')
        pnl    = trade.get('pnl_r', 0)
        ic     = chr(0x2705) + ' WIN ' if res == 'WIN' else chr(0x274C) + ' LOSS'
        colour = GREEN if res == 'WIN' else RED
        print(f'\n{BOLD}{colour}[{ts}] ■ TRADE CLOSED  {ic}  PnL: {pnl:+.3f}R{RESET}', flush=True)
        print(f\"  {trade.get('symbol')} / {trade.get('timeframe')}  \"
              f\"exit=\${trade.get('exit_price', 0):,.4f}  {trade.get('reason','')[:40]}\n\", flush=True)
        s = obj.get('summary', {})
        print(f\"  Session: {s.get('trades',0)} trades  \"
              f\"WR={s.get('win_rate',0)*100:.1f}%  \"
              f\"Exp-R={s.get('expectancy_r',0):.4f}\n\", flush=True)

    elif t == 'NO_SIGNAL':
        reason = obj.get('reason', '')
        print(f'{GREY}[{ts}] NO SIGNAL  {reason[:60]}{RESET}', flush=True)

    elif t == 'EXECUTION_FILTER_RELAX':
        print(f'{YELLOW}[{ts}] FILTER RELAX  {str(obj)[:80]}{RESET}', flush=True)

    elif t in ('LOSS_GUARD', 'PERFORMANCE_GUARD'):
        print(f'{RED}[{ts}] {t}  {str(obj)[:80]}{RESET}', flush=True)

    elif t == 'RUN_STAGE':
        print(f'{BLUE}[{ts}] {obj.get(\"stage\",\"\")}  {obj.get(\"message\",\"\")}{RESET}', flush=True)

    else:
        print(f'{GREY}[{ts}] {t}{RESET}', flush=True)
"
