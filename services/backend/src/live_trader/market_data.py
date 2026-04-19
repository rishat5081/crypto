from __future__ import annotations

import json
from typing import Dict, List


class TraderMarketDataMixin:
    def _refresh_batch_market_data(self) -> None:
        try:
            self._premium_cache = self.client.fetch_all_premium_index()
        except Exception as exc:
            print(json.dumps({"type": "BATCH_PREMIUM_ERROR", "time": self._now_iso(), "error": str(exc)}))
        try:
            self._ticker_cache = self.client.fetch_all_ticker_prices()
        except Exception as exc:
            print(json.dumps({"type": "BATCH_TICKER_ERROR", "time": self._now_iso(), "error": str(exc)}))
        self._reconcile_symbol_universe()

    def _reconcile_symbol_universe(self) -> None:
        known_symbols = set(self._premium_cache) | set(self._ticker_cache)
        if not known_symbols:
            return
        removed: List[Dict[str, int]] = []
        open_trade_symbols = self._open_trade_symbols()
        for symbol in list(self.symbols):
            if symbol in known_symbols:
                self.invalid_symbol_failures[symbol] = 0
                continue
            self.invalid_symbol_failures[symbol] = int(self.invalid_symbol_failures.get(symbol, 0)) + 1
            if self.invalid_symbol_failures[symbol] < self.invalid_symbol_failure_threshold or symbol in open_trade_symbols:
                continue
            self.symbols.remove(symbol)
            self.symbol_confidence.pop(symbol, None)
            self.symbol_cooldowns.pop(symbol, None)
            self.symbol_consecutive_losses.pop(symbol, None)
            removed.append({"symbol": symbol, "failures": self.invalid_symbol_failures[symbol]})
        if removed:
            print(json.dumps({"type": "SYMBOLS_FILTERED", "time": self._now_iso(), "removed": removed, "remaining_symbols": len(self.symbols)}))

    def _get_klines_window(self) -> List[str]:
        active = self._active_symbols()
        if not active:
            return []
        window_size = min(self.klines_window_size, len(active))
        start = self._klines_window_offset % len(active)
        window = active[start:start + window_size]
        if len(window) < window_size:
            window += active[:window_size - len(window)]
        self._klines_window_offset = (start + window_size) % max(len(active), 1)
        return window

    def _market_snapshot(self, symbol: str) -> Dict:
        price = self._ticker_cache.get(symbol)
        if price is not None:
            return {"symbol": symbol, "price": price, "time": 0}
        tick = self.client._get_json("/fapi/v1/ticker/price", {"symbol": symbol})
        return {"symbol": symbol, "price": float(tick["price"]), "time": int(tick.get("time", 0))}

    def _close_orphaned_positions(self) -> None:
        if not self.executor.enabled:
            return
        try:
            account = self.executor.get_account()
            positions = account.get("positions", [])
            for position in positions:
                amt = float(position.get("positionAmt", 0))
                if amt == 0:
                    continue
                symbol = position["symbol"]
                side = "LONG" if amt > 0 else "SHORT"
                pnl = float(position.get("unrealizedProfit", 0))
                self._emit_event(
                    {
                        "type": "BINANCE_ORDER",
                        "time": self._now_iso(),
                        "action": "ORPHAN_DETECTED",
                        "symbol": symbol,
                        "side": side,
                        "pnl": pnl,
                        "auto_close_enabled": self.close_orphaned_positions_on_startup,
                    },
                    persist=True,
                )
                if self.close_orphaned_positions_on_startup:
                    close_result = self.executor.close_trade(symbol, side, "ORPHAN_CLEANUP")
                    close_payload = {
                        "type": "BINANCE_ORDER",
                        "time": self._now_iso(),
                        "action": "ORPHAN_CLOSE",
                        "symbol": symbol,
                        "side": side,
                        "result": close_result,
                    }
                    if close_result.get("unrealized_pnl") is not None:
                        close_payload["pnl"] = close_result.get("unrealized_pnl")
                    self._emit_event(close_payload, persist=True)
        except Exception as exc:
            self._emit_event(
                {"type": "BINANCE_ORDER", "time": self._now_iso(), "action": "ORPHAN_CHECK_FAILED", "error": str(exc)},
                persist=True,
            )
