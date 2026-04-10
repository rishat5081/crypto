#!/usr/bin/env python3
"""Discover top USDT perpetual futures pairs by 24h volume on Binance.

Updates config.json with the discovered symbols so the live trader
and cache scripts automatically pick them up.

Usage:
    python3 discover_symbols.py              # update config.json with top 100
    python3 discover_symbols.py --top 50     # top 50 instead
    python3 discover_symbols.py --dry-run    # print symbols without writing
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

FAPI_BASE = "https://fapi.binance.com"
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def _read_json(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers={"User-Agent": "crypto-discover/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def discover_symbols(top_n: int = 100) -> list[str]:
    """Return top N USDT perpetual symbols sorted by 24h quote volume."""
    # 1. Get 24h volume for ranking (API weight: 40)
    volume_by_symbol: dict[str, float] = {}
    tickers = _read_json(f"{FAPI_BASE}/fapi/v1/ticker/24hr")
    for row in tickers:
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol.endswith("USDT"):
            continue
        try:
            qv = float(row.get("quoteVolume", 0.0))
        except (TypeError, ValueError):
            qv = 0.0
        volume_by_symbol[symbol] = max(volume_by_symbol.get(symbol, 0.0), qv)

    # 2. Filter to active PERPETUAL contracts (API weight: 1)
    exchange_info = _read_json(f"{FAPI_BASE}/fapi/v1/exchangeInfo")
    valid_symbols: list[str] = []
    for row in exchange_info.get("symbols", []):
        symbol = str(row.get("symbol", "")).strip().upper()
        if (
            symbol.endswith("USDT")
            and row.get("contractType") == "PERPETUAL"
            and row.get("status") == "TRADING"
        ):
            valid_symbols.append(symbol)

    # 3. Sort by volume descending, take top N
    ranked = sorted(
        set(valid_symbols),
        key=lambda s: (-volume_by_symbol.get(s, 0.0), s),
    )
    return ranked[:top_n]


def main():
    parser = argparse.ArgumentParser(description="Discover top USDT perpetual pairs")
    parser.add_argument("--top", type=int, default=100, help="Number of top pairs (default: 100)")
    parser.add_argument("--dry-run", action="store_true", help="Print symbols without updating config")
    parser.add_argument("--config", type=str, default=str(CONFIG_PATH), help="Path to config.json")
    args = parser.parse_args()

    print(f"Discovering top {args.top} USDT perpetual futures pairs...")
    symbols = discover_symbols(top_n=args.top)
    print(f"Found {len(symbols)} symbols:")
    for i, s in enumerate(symbols, 1):
        print(f"  {i:3d}. {s}")

    if args.dry_run:
        print("\n[dry-run] No config file changes made.")
        return

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["pairs"] = symbols
    config.setdefault("live_loop", {})["symbols"] = symbols
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"\nUpdated {config_path} with {len(symbols)} symbols.")


if __name__ == "__main__":
    main()
