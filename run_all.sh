#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
CACHE_DIR="$ROOT_DIR/data/live"
VENV_DIR="$ROOT_DIR/.venv"
OS_NAME="$(uname -s)"
PYTHON_CMD=""

FRONTEND_DIR="$ROOT_DIR/frontend"
FRONTEND_STATIC_DIR="$FRONTEND_DIR"
FRONTEND_NPM_LOG="/tmp/crypto_frontend_npm.log"
EVENTS_FILE="$ROOT_DIR/data/live_events.jsonl"
HISTORY_EVENTS_FILE="$ROOT_DIR/data/live_events_history.jsonl"
RUNTIME_CONTROL_FILE="$ROOT_DIR/data/runtime_control.json"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-8787}"
START_FRONTEND="${START_FRONTEND:-1}"
MONGO_URI="${MONGO_URI:-mongodb://127.0.0.1:27017}"
MONGO_DB="${MONGO_DB:-crypto_trading_live}"
MONGO_REQUIRED="${MONGO_REQUIRED:-1}"
SKIP_OPTIMIZE="${SKIP_OPTIMIZE:-0}"
AUTO_INSTALL_DEPS="${AUTO_INSTALL_DEPS:-1}"
OPTIMIZE_MAX_CANDIDATES="${OPTIMIZE_MAX_CANDIDATES:-8}"
OPTIMIZE_TIMEOUT_SEC="${OPTIMIZE_TIMEOUT_SEC:-45}"
HEARTBEAT_SEC="${HEARTBEAT_SEC:-5}"
RETUNE_FROM_EVENTS="${RETUNE_FROM_EVENTS:-1}"
RETUNE_LOOKBACK_TRADES="${RETUNE_LOOKBACK_TRADES:-300}"
RETUNE_MIN_TRADES="${RETUNE_MIN_TRADES:-20}"
FRONTEND_PID=""

log() {
  printf '[run_all] %s\n' "$1"
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

emit_event() {
  if [ "$START_FRONTEND" != "1" ]; then
    return
  fi

  local stage="$1"
  local message="$2"
  local now
  now="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf '{"type":"RUN_STAGE","time":"%s","stage":"%s","message":"%s"}\n' "$now" "$stage" "$message" >> "$EVENTS_FILE"
  printf '{"type":"RUN_STAGE","time":"%s","stage":"%s","message":"%s"}\n' "$now" "$stage" "$message" >> "$HISTORY_EVENTS_FILE"
}

run_with_sudo_if_available() {
  if have_cmd sudo; then
    sudo "$@"
  else
    "$@"
  fi
}

kill_by_pattern() {
  local pattern="$1"
  local label="$2"
  local pids=""

  pids="$(pgrep -f "$pattern" || true)"
  if [ -z "$pids" ]; then
    return
  fi

  log "Stopping existing $label process(es): $pids"
  kill $pids >/dev/null 2>&1 || true
  sleep 1

  pids="$(pgrep -f "$pattern" || true)"
  if [ -n "$pids" ]; then
    log "Force stopping remaining $label process(es): $pids"
    kill -9 $pids >/dev/null 2>&1 || true
  fi
}

kill_by_port() {
  local port="$1"
  if ! have_cmd lsof; then
    return
  fi

  local pids=""
  pids="$(lsof -ti tcp:"$port" || true)"
  if [ -z "$pids" ]; then
    return
  fi

  log "Stopping process(es) on port $port: $pids"
  kill $pids >/dev/null 2>&1 || true
  sleep 1

  pids="$(lsof -ti tcp:"$port" || true)"
  if [ -n "$pids" ]; then
    log "Force stopping remaining process(es) on port $port: $pids"
    kill -9 $pids >/dev/null 2>&1 || true
  fi
}

stop_existing_processes() {
  log "Stopping stale processes from previous runs"
  kill_by_pattern "$ROOT_DIR/run_live_adaptive.py" "live trader"
  kill_by_pattern "$ROOT_DIR/run_ml_walkforward.py" "optimizer"
  kill_by_pattern "$FRONTEND_DIR/server.py" "frontend server"

  if [ "$START_FRONTEND" = "1" ]; then
    kill_by_port "$FRONTEND_PORT"
  fi
}

install_python_macos() {
  if ! have_cmd brew; then
    log "Homebrew is required to install Python on macOS. Install Homebrew first: https://brew.sh"
    exit 1
  fi
  log "Installing Python on macOS via Homebrew"
  brew install python || true
}

install_python_linux() {
  log "Installing Python on Linux"
  if have_cmd apt-get; then
    run_with_sudo_if_available apt-get update
    run_with_sudo_if_available apt-get install -y python3 python3-venv python3-pip
    return
  fi
  if have_cmd dnf; then
    run_with_sudo_if_available dnf install -y python3 python3-pip
    return
  fi
  if have_cmd yum; then
    run_with_sudo_if_available yum install -y python3 python3-pip
    return
  fi
  if have_cmd pacman; then
    run_with_sudo_if_available pacman -Sy --noconfirm python python-pip
    return
  fi
  if have_cmd zypper; then
    run_with_sudo_if_available zypper --non-interactive install python3 python3-pip
    return
  fi

  log "Unsupported Linux package manager. Install Python 3.10+ manually and re-run."
  exit 1
}

install_python_windows_like() {
  log "Installing Python on Windows-compatible environment"
  if have_cmd winget; then
    winget install -e --id Python.Python.3.11
    return
  fi
  if have_cmd choco; then
    choco install -y python
    return
  fi

  log "Could not auto-install Python (winget/choco not found). Install Python 3.10+ manually and re-run."
  exit 1
}

ensure_python() {
  if have_cmd python3; then
    PYTHON_CMD="$(command -v python3)"
    return
  fi

  case "$OS_NAME" in
    Darwin)
      install_python_macos
      ;;
    Linux)
      install_python_linux
      ;;
    CYGWIN*|MINGW*|MSYS*)
      install_python_windows_like
      ;;
    *)
      log "Unsupported OS: $OS_NAME. Install Python 3.10+ manually and re-run."
      exit 1
      ;;
  esac

  if ! have_cmd python3; then
    log "Python install did not provide python3 in PATH. Restart terminal and run again."
    exit 1
  fi

  PYTHON_CMD="$(command -v python3)"
}

ensure_venv_and_deps() {
  if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtual environment at $VENV_DIR"
    "$PYTHON_CMD" -m venv "$VENV_DIR"
  fi

  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  PYTHON_CMD="$(command -v python)"

  if [ "$AUTO_INSTALL_DEPS" = "1" ]; then
    log "Upgrading pip/setuptools/wheel"
    python -m pip install --upgrade pip setuptools wheel

    if [ -f "$ROOT_DIR/requirements.txt" ] && grep -Eqv '^\s*($|#)' "$ROOT_DIR/requirements.txt"; then
      log "Installing Python packages from requirements.txt"
      pip install -r "$ROOT_DIR/requirements.txt"
    else
      log "No external Python packages required"
    fi
  else
    log "Skipping pip/package install (AUTO_INSTALL_DEPS=0) for fast startup"
  fi
}

build_frontend() {
  if [ "$START_FRONTEND" != "1" ]; then
    return
  fi

  if [ ! -f "$FRONTEND_DIR/package.json" ]; then
    FRONTEND_STATIC_DIR="$FRONTEND_DIR"
    return
  fi

  if ! have_cmd npm; then
    log "npm is required to build the frontend but was not found in PATH"
    exit 1
  fi

  : > "$FRONTEND_NPM_LOG"
  log "Installing frontend dependencies"
  (
    cd "$FRONTEND_DIR"
    npm install
  ) >>"$FRONTEND_NPM_LOG" 2>&1

  log "Building frontend assets"
  (
    cd "$FRONTEND_DIR"
    npm run build
  ) >>"$FRONTEND_NPM_LOG" 2>&1

  if [ ! -f "$FRONTEND_DIR/dist/index.html" ]; then
    log "Frontend build did not produce dist/index.html. Check $FRONTEND_NPM_LOG"
    exit 1
  fi

  FRONTEND_STATIC_DIR="$FRONTEND_DIR/dist"
}

start_frontend() {
  if [ "$START_FRONTEND" != "1" ]; then
    log "Frontend startup disabled (START_FRONTEND=$START_FRONTEND)"
    return
  fi

  if [ ! -f "$FRONTEND_DIR/server.py" ]; then
    log "Frontend server not found at $FRONTEND_DIR/server.py"
    return
  fi

  if [ -f "$FRONTEND_DIR/dist/index.html" ]; then
    FRONTEND_STATIC_DIR="$FRONTEND_DIR/dist"
  else
    FRONTEND_STATIC_DIR="$FRONTEND_DIR"
  fi

  mkdir -p "$(dirname "$EVENTS_FILE")"
  touch "$HISTORY_EVENTS_FILE"
  if [ -s "$EVENTS_FILE" ]; then
    cat "$EVENTS_FILE" >> "$HISTORY_EVENTS_FILE"
  fi
  : > "$EVENTS_FILE"
  rm -f "$RUNTIME_CONTROL_FILE"

  log "Starting TP/SL UI at http://$FRONTEND_HOST:$FRONTEND_PORT"
  "$PYTHON_CMD" "$FRONTEND_DIR/server.py" \
    --host "$FRONTEND_HOST" \
    --port "$FRONTEND_PORT" \
    --events-file "$EVENTS_FILE" \
    --history-events-file "$HISTORY_EVENTS_FILE" \
    --config-file "$ROOT_DIR/config.json" \
    --runtime-control-file "$RUNTIME_CONTROL_FILE" \
    --mongo-uri "$MONGO_URI" \
    --mongo-db "$MONGO_DB" \
    --mongo-required "$MONGO_REQUIRED" \
    --static-dir "$FRONTEND_STATIC_DIR" \
    >/tmp/crypto_frontend.log 2>&1 &

  FRONTEND_PID=$!
  sleep 1

  if ! kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
    log "Frontend failed to start. Check /tmp/crypto_frontend.log"
    FRONTEND_PID=""
  fi
}

run_optimizer_with_progress() {
  local cmd=(
    python "$ROOT_DIR/run_ml_walkforward.py"
    --config "$ROOT_DIR/config.json"
    --cache-dir "$CACHE_DIR"
    --timeframes 1m,5m,15m
    --target-trades 200
    --target-wins 150
    --max-candidates "$OPTIMIZE_MAX_CANDIDATES"
    --max-candles 700
    --apply-best
  )
  local opt_log="/tmp/crypto_optimizer.log"

  : > "$opt_log"
  log "Running ML walk-forward optimization (max_candidates=$OPTIMIZE_MAX_CANDIDATES)"
  emit_event "OPTIMIZING" "Running ML walk-forward optimization"

  set +e
  "${cmd[@]}" >"$opt_log" 2>&1 &
  local opt_pid=$!
  local start_ts elapsed
  start_ts="$(date +%s)"

  while kill -0 "$opt_pid" >/dev/null 2>&1; do
    elapsed=$(( $(date +%s) - start_ts ))
    log "Optimization in progress (${elapsed}s elapsed)..."
    emit_event "OPTIMIZING" "Optimization in progress (${elapsed}s elapsed)"

    if [ "$OPTIMIZE_TIMEOUT_SEC" -gt 0 ] && [ "$elapsed" -ge "$OPTIMIZE_TIMEOUT_SEC" ]; then
      log "Optimization timeout reached (${OPTIMIZE_TIMEOUT_SEC}s). Continuing with live trading."
      emit_event "OPTIMIZATION_TIMEOUT" "Timeout reached after ${OPTIMIZE_TIMEOUT_SEC}s, continuing"
      kill "$opt_pid" >/dev/null 2>&1 || true
      sleep 1
      if kill -0 "$opt_pid" >/dev/null 2>&1; then
        kill -9 "$opt_pid" >/dev/null 2>&1 || true
      fi
      wait "$opt_pid" >/dev/null 2>&1 || true
      set -e
      return 0
    fi

    sleep "$HEARTBEAT_SEC"
  done

  wait "$opt_pid"
  local status=$?
  set -e

  if [ -s "$opt_log" ]; then
    cat "$opt_log"
    if [ "$START_FRONTEND" = "1" ]; then
      cat "$opt_log" >> "$EVENTS_FILE"
      cat "$opt_log" >> "$HISTORY_EVENTS_FILE"
    fi
  fi

  if [ "$status" -ne 0 ]; then
    log "Optimization failed (exit=$status). Continuing with live trading."
    emit_event "OPTIMIZATION_FAILED" "Optimizer exited with code $status, continuing"
    return 0
  fi

  emit_event "OPTIMIZATION_DONE" "Optimization complete"
}

run_threshold_retune() {
  if [ "$RETUNE_FROM_EVENTS" != "1" ]; then
    log "Skipping threshold retune (RETUNE_FROM_EVENTS=$RETUNE_FROM_EVENTS)"
    emit_event "SKIP_RETUNE" "Skipping threshold retune"
    return
  fi

  local retune_log="/tmp/crypto_retune.log"
  : > "$retune_log"
  log "Retuning thresholds from recent live multi-coin trade history"
  emit_event "RETUNING_THRESHOLDS" "Retuning thresholds from live event history"

  set +e
  python "$ROOT_DIR/run_retune_thresholds.py" \
    --config "$ROOT_DIR/config.json" \
    --events-file "$HISTORY_EVENTS_FILE" \
    --lookback-trades "$RETUNE_LOOKBACK_TRADES" \
    --min-trades "$RETUNE_MIN_TRADES" \
    --apply >"$retune_log" 2>&1
  local status=$?
  set -e

  if [ -s "$retune_log" ]; then
    cat "$retune_log"
    if [ "$START_FRONTEND" = "1" ]; then
      cat "$retune_log" >> "$EVENTS_FILE"
      cat "$retune_log" >> "$HISTORY_EVENTS_FILE"
    fi
  fi

  if [ "$status" -ne 0 ]; then
    log "Threshold retune failed (exit=$status). Continuing with existing config."
    emit_event "RETUNE_FAILED" "Threshold retune failed, continuing with current config"
    return
  fi

  emit_event "RETUNE_DONE" "Threshold retune complete"
}

cleanup() {
  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
    log "Stopping TP/SL UI server"
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
}

main() {
  trap cleanup EXIT

  stop_existing_processes
  ensure_python
  ensure_venv_and_deps
  build_frontend
  start_frontend
  emit_event "BOOTSTRAP" "Preparing environment"
  emit_event "BOOTSTRAP_DONE" "Environment ready"

  log "Fetching latest live market cache"
  emit_event "FETCHING_MARKET_DATA" "Fetching latest live market cache"
  if ! "$ROOT_DIR/fetch_live_cache.sh" "$CACHE_DIR"; then
    log "Live cache fetch failed; continuing with existing cache files."
    emit_event "FETCH_MARKET_DATA_FAILED" "Fetch failed, continuing with existing cache"
  fi

  if [ "$SKIP_OPTIMIZE" = "1" ]; then
    log "Skipping optimization (SKIP_OPTIMIZE=1)"
    emit_event "SKIP_OPTIMIZATION" "Skipping ML walk-forward optimization"
  else
    run_optimizer_with_progress
  fi

  run_threshold_retune

  log "Starting live adaptive paper-trading loop"
  emit_event "LIVE_TRADING" "Live adaptive paper-trading started"
  python -u "$ROOT_DIR/run_live_adaptive.py" --config "$ROOT_DIR/config.json" --continuous | tee -a "$EVENTS_FILE" "$HISTORY_EVENTS_FILE"
}

main "$@"
