#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
#  start.sh  —  One-command live market signal launcher
#  Usage:  ./start.sh
#          ./start.sh --no-browser      (skip auto-open dashboard)
#          ./start.sh --skip-optimize   (faster startup)
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
OPEN_BROWSER=1
SKIP_OPT=0

for arg in "$@"; do
  case "$arg" in
    --no-browser)    OPEN_BROWSER=0 ;;
    --skip-optimize) SKIP_OPT=1 ;;
  esac
done

# ── Colour helpers ────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
RED='\033[0;31m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { printf "${CYAN}[start]${RESET} %s\n" "$1"; }
ok()   { printf "${GREEN}[  OK ]${RESET} %s\n" "$1"; }
warn() { printf "${YELLOW}[ WARN]${RESET} %s\n" "$1"; }
err()  { printf "${RED}[ERROR]${RESET} %s\n" "$1"; }
sep()  { printf "${BOLD}%s${RESET}\n" "──────────────────────────────────────────────────────"; }

# ── Banner ────────────────────────────────────────────────────────────
clear
printf "${BOLD}${CYAN}"
cat << 'BANNER'
  ╔══════════════════════════════════════════════════════╗
  ║       CRYPTO TP/SL  —  LIVE SIGNAL SYSTEM           ║
  ║       Binance Futures  |  Paper Trading Only         ║
  ╚══════════════════════════════════════════════════════╝
BANNER
printf "${RESET}\n"

# ── Config ────────────────────────────────────────────────────────────
export MONGO_REQUIRED=0          # skip MongoDB — not required
export START_FRONTEND=1          # enable dashboard
export FRONTEND_HOST=127.0.0.1
export FRONTEND_PORT=8787
export AUTO_INSTALL_DEPS=1
export SKIP_OPTIMIZE=$SKIP_OPT
export RETUNE_FROM_EVENTS=1
export OPTIMIZE_TIMEOUT_SEC=45
export HEARTBEAT_SEC=5

DASHBOARD_URL="http://$FRONTEND_HOST:$FRONTEND_PORT"
EVENTS_FILE="$ROOT_DIR/data/live_events.jsonl"
HISTORY_FILE="$ROOT_DIR/data/live_events_history.jsonl"
FRONTEND_LOG="/tmp/crypto_frontend.log"
TRADER_LOG="/tmp/crypto_trader.log"

# ── Pre-flight checks ─────────────────────────────────────────────────
sep
log "Pre-flight checks..."

if ! command -v python3 >/dev/null 2>&1; then
  err "Python 3 not found. Install Python 3.11+ and retry."
  exit 1
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python $PY_VER found"

if [ ! -f "$ROOT_DIR/config.json" ]; then
  err "config.json not found in $ROOT_DIR"
  exit 1
fi
ok "config.json found"

python3 -c "import json; json.load(open('$ROOT_DIR/config.json'))" 2>/dev/null \
  && ok "config.json valid" || { err "config.json is invalid JSON"; exit 1; }

# ── Virtual environment ───────────────────────────────────────────────
sep
log "Setting up Python environment..."

VENV="$ROOT_DIR/.venv"
if [ ! -d "$VENV" ]; then
  log "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
ok "Virtual environment active"

log "Installing/verifying dependencies..."
pip install --quiet --upgrade pip setuptools wheel
pip install --quiet -r "$ROOT_DIR/requirements.txt"
ok "Dependencies ready"

# ── Kill stale processes ──────────────────────────────────────────────
sep
log "Stopping any stale processes..."

pkill -f "run_live_adaptive.py"  2>/dev/null || true
pkill -f "frontend/server.py"    2>/dev/null || true

if command -v lsof >/dev/null 2>&1; then
  STALE=$(lsof -ti tcp:$FRONTEND_PORT 2>/dev/null || true)
  [ -n "$STALE" ] && kill $STALE 2>/dev/null || true
fi
sleep 1
ok "Clean slate"

# ── Prepare data dir ─────────────────────────────────────────────────
mkdir -p "$ROOT_DIR/data"
touch "$HISTORY_FILE"
# Roll current events into history
if [ -s "$EVENTS_FILE" ]; then
  cat "$EVENTS_FILE" >> "$HISTORY_FILE"
fi
: > "$EVENTS_FILE"
rm -f "$ROOT_DIR/data/runtime_control.json"

# ── Start dashboard ───────────────────────────────────────────────────
sep
log "Starting dashboard server..."

python "$ROOT_DIR/frontend/server.py" \
  --host "$FRONTEND_HOST" \
  --port "$FRONTEND_PORT" \
  --events-file      "$EVENTS_FILE" \
  --history-events-file "$HISTORY_FILE" \
  --config-file      "$ROOT_DIR/config.json" \
  --runtime-control-file "$ROOT_DIR/data/runtime_control.json" \
  --mongo-required   0 \
  --static-dir       "$ROOT_DIR/frontend" \
  > "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

sleep 2
if kill -0 "$FRONTEND_PID" 2>/dev/null; then
  ok "Dashboard running  →  $DASHBOARD_URL  (pid $FRONTEND_PID)"
else
  warn "Dashboard failed to start. Continuing without UI."
  warn "Check: $FRONTEND_LOG"
  FRONTEND_PID=""
fi

# Auto-open browser
if [ "$OPEN_BROWSER" = "1" ]; then
  sleep 1
  if command -v open >/dev/null 2>&1; then          # macOS
    open "$DASHBOARD_URL" 2>/dev/null || true
  elif command -v xdg-open >/dev/null 2>/dev/null; then  # Linux
    xdg-open "$DASHBOARD_URL" 2>/dev/null || true
  fi
fi

# ── Optional: ML optimizer ────────────────────────────────────────────
sep
if [ "$SKIP_OPTIMIZE" = "1" ]; then
  log "Skipping ML optimization (--skip-optimize)"
else
  log "Running ML walk-forward optimizer (${OPTIMIZE_TIMEOUT_SEC}s max)..."

  python "$ROOT_DIR/run_ml_walkforward.py" \
    --config "$ROOT_DIR/config.json" \
    --cache-dir "$ROOT_DIR/data/live" \
    --timeframes 5m,15m \
    --target-trades 100 \
    --target-wins 60 \
    --max-candidates 6 \
    --max-candles 500 \
    --apply-best \
    >> "$EVENTS_FILE" 2>&1 &
  OPT_PID=$!

  elapsed=0
  while kill -0 "$OPT_PID" 2>/dev/null; do
    sleep 5; elapsed=$((elapsed+5))
    log "  Optimizing... ${elapsed}s"
    [ "$elapsed" -ge "$OPTIMIZE_TIMEOUT_SEC" ] && { kill "$OPT_PID" 2>/dev/null || true; break; }
  done
  wait "$OPT_PID" 2>/dev/null || true
  ok "Optimization done (or timed out)"
fi

# ── Signal stream display ─────────────────────────────────────────────
sep
printf "${BOLD}${GREEN}"
printf "  LIVE SIGNAL MONITOR — streaming now\n"
printf "  Dashboard : $DASHBOARD_URL\n"
printf "  Press Ctrl+C to stop\n"
printf "${RESET}"
sep
printf "\n"

# ── Cleanup on exit ───────────────────────────────────────────────────
cleanup() {
  printf "\n"
  sep
  log "Shutting down..."
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  pkill -f "run_live_adaptive.py" 2>/dev/null || true
  ok "Stopped. Bye!"
}
trap cleanup EXIT INT TERM

# ── Start trader — stream signals to terminal ─────────────────────────
python -u "$ROOT_DIR/run_live_adaptive.py" --config "$ROOT_DIR/config.json" \
| tee -a "$EVENTS_FILE" "$HISTORY_FILE" \
| python3 -u - << 'FILTER'
import sys, json

RESET  = "\033[0m";   BOLD   = "\033[1m"
GREEN  = "\033[0;32m"; RED    = "\033[0;31m"
YELLOW = "\033[1;33m"; CYAN   = "\033[0;36m"
BLUE   = "\033[0;34m"; GREY   = "\033[0;90m"

for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    try:
        obj = json.loads(raw)
    except Exception:
        print(GREY + raw + RESET, flush=True)
        continue

    t = obj.get("type", "")
    ts = obj.get("time", "")[:19].replace("T", " ")

    if t == "LIVE_MARKET":
        snaps = obj.get("snapshots", [])
        prices = "  ".join(f"{s['symbol']}: ${s['price']:,.2f}" for s in snaps[:5])
        print(f"{GREY}[{ts}] PRICES  {prices}{RESET}", flush=True)

    elif t == "POSSIBLE_TRADES":
        n = obj.get("total_possible_trades", 0)
        cycle = obj.get("cycle", "?")
        bar = "█" * min(n, 20)
        colour = GREEN if n > 0 else YELLOW
        print(f"{colour}[{ts}] CYCLE {cycle:>3}  candidates={n}  {bar}{RESET}", flush=True)
        for trade in obj.get("trades", []):
            ic = "🟢" if trade["side"] == "LONG" else "🔴"
            print(f"  {ic} {trade['symbol']:<10} {trade['timeframe']:<5} "
                  f"{trade['side']:<5}  entry={trade['entry']:.4f}  "
                  f"conf={trade['confidence']:.3f}  score={trade['score']:.3f}  "
                  f"exp-R={trade['expectancy_r']:.3f}", flush=True)

    elif t == "TRADE_OPEN":
        trade = obj.get("trade", obj)
        ic = "🟢" if trade.get("side") == "LONG" else "🔴"
        print(f"\n{BOLD}{GREEN}[{ts}] ▶ TRADE OPEN{RESET}", flush=True)
        print(f"  {ic} {trade.get('symbol')} / {trade.get('timeframe')}  {trade.get('side')}", flush=True)
        print(f"     Entry  : ${trade.get('entry', 0):,.4f}", flush=True)
        print(f"     TP     : ${trade.get('take_profit', 0):,.4f}", flush=True)
        print(f"     SL     : ${trade.get('stop_loss', 0):,.4f}", flush=True)
        print(f"     Conf   : {trade.get('confidence', 0):.3f}\n", flush=True)

    elif t == "TRADE_RESULT":
        trade = obj.get("trade", {})
        res   = trade.get("result", "?")
        pnl   = trade.get("pnl_r", 0)
        ic    = "✅ WIN " if res == "WIN" else "❌ LOSS"
        colour = GREEN if res == "WIN" else RED
        print(f"\n{BOLD}{colour}[{ts}] ■ TRADE CLOSED  {ic}  PnL: {pnl:+.3f}R{RESET}", flush=True)
        print(f"  {trade.get('symbol')} / {trade.get('timeframe')}  "
              f"exit=${trade.get('exit_price', 0):,.4f}  {trade.get('reason','')[:40]}\n", flush=True)
        s = obj.get("summary", {})
        print(f"  Session: {s.get('trades',0)} trades  "
              f"WR={s.get('win_rate',0)*100:.1f}%  "
              f"Exp-R={s.get('expectancy_r',0):.4f}\n", flush=True)

    elif t == "NO_SIGNAL":
        reason = obj.get("reason", "")
        print(f"{GREY}[{ts}] NO SIGNAL  {reason[:60]}{RESET}", flush=True)

    elif t == "EXECUTION_FILTER_RELAX":
        print(f"{YELLOW}[{ts}] FILTER RELAX  {str(obj)[:80]}{RESET}", flush=True)

    elif t in ("LOSS_GUARD", "PERFORMANCE_GUARD"):
        print(f"{RED}[{ts}] {t}  {str(obj)[:80]}{RESET}", flush=True)

    elif t == "RUN_STAGE":
        print(f"{BLUE}[{ts}] {obj.get('stage','')}  {obj.get('message','')}{RESET}", flush=True)

    else:
        print(f"{GREY}[{ts}] {t}{RESET}", flush=True)
FILTER
