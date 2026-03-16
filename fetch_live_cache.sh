#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/config.json"

OUT_DIR="${1:-/Users/user/Desktop/Work/crypto/data/live}"
# Read symbols from config.json if not provided as argument
if [ -n "${2:-}" ]; then
  SYMBOLS="$2"
else
  SYMBOLS="$(python3 -c "
import json, pathlib
cfg = json.loads(pathlib.Path('${CONFIG_FILE}').read_text())
syms = cfg.get('live_loop', {}).get('symbols', cfg.get('pairs', []))
print(','.join(syms))
")"
fi
TIMEFRAMES="${3:-5m,15m}"
LIMIT="${4:-1500}"
MAX_PARALLEL="${5:-8}"

mkdir -p "$OUT_DIR"
IFS=',' read -r -a SYM_ARR <<< "$SYMBOLS"
IFS=',' read -r -a TF_ARR <<< "$TIMEFRAMES"

BINANCE_HOSTS=("fapi.binance.com" "fapi1.binance.com" "fapi2.binance.com")

echo "[fetch_live_cache] Output dir: $OUT_DIR"
echo "[fetch_live_cache] Symbols: ${#SYM_ARR[@]} | Timeframes: ${#TF_ARR[@]} | Limit: $LIMIT | Workers: $MAX_PARALLEL"

SUCCESS_COUNT=0
FAILED_COUNT=0

curl_binance() {
  local path_query="$1"
  local out_file="$2"
  local ok=0

  for host in "${BINANCE_HOSTS[@]}"; do
    if curl -sS --retry 3 --retry-delay 1 --max-time 30 \
      "https://${host}${path_query}" \
      -o "${out_file}.tmp"; then
      mv "${out_file}.tmp" "$out_file"
      ok=1
      break
    fi
  done

  if [ "$ok" -ne 1 ]; then
    rm -f "${out_file}.tmp"
    echo "[fetch_live_cache] Failed: ${path_query}" >&2
    return 1
  fi
}

# Fetch batch premium index (all symbols in one call)
echo "[fetch_live_cache] Fetching batch premiumIndex..."
curl_binance "/fapi/v1/premiumIndex" "$OUT_DIR/_batch_premium.json" || true

# Worker function for parallel fetches
fetch_symbol() {
  local symbol="$1"
  symbol="${symbol// /}"
  [ -z "$symbol" ] && return 1

  local symbol_ok=1
  for tf in "${TF_ARR[@]}"; do
    tf="${tf// /}"
    [ -z "$tf" ] && continue

    if ! curl_binance \
      "/fapi/v1/klines?symbol=${symbol}&interval=${tf}&limit=${LIMIT}" \
      "$OUT_DIR/${symbol}_${tf}_klines.json"; then
      echo "[fetch_live_cache] WARN: $symbol $tf failed" >&2
      symbol_ok=0
      break
    fi
  done

  return $((1 - symbol_ok))
}

# Run fetches in parallel with limited concurrency
RUNNING=0
PIDS=()
SYM_FOR_PID=()

for symbol in "${SYM_ARR[@]}"; do
  symbol="${symbol// /}"
  [ -z "$symbol" ] && continue

  fetch_symbol "$symbol" &
  PIDS+=($!)
  SYM_FOR_PID+=("$symbol")
  RUNNING=$((RUNNING + 1))

  if [ "$RUNNING" -ge "$MAX_PARALLEL" ]; then
    # Wait for the oldest job
    wait "${PIDS[0]}" && SUCCESS_COUNT=$((SUCCESS_COUNT + 1)) || FAILED_COUNT=$((FAILED_COUNT + 1))
    PIDS=("${PIDS[@]:1}")
    SYM_FOR_PID=("${SYM_FOR_PID[@]:1}")
    RUNNING=$((RUNNING - 1))
  fi
done

# Wait for remaining jobs
for pid in "${PIDS[@]}"; do
  wait "$pid" && SUCCESS_COUNT=$((SUCCESS_COUNT + 1)) || FAILED_COUNT=$((FAILED_COUNT + 1))
done

echo "[fetch_live_cache] Live cache written to: $OUT_DIR"
echo "[fetch_live_cache] Summary: success=$SUCCESS_COUNT failed=$FAILED_COUNT"

if [ "$SUCCESS_COUNT" -eq 0 ]; then
  echo "[fetch_live_cache] ERROR: no symbols fetched successfully" >&2
  exit 1
fi
