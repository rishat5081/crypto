import json
from unittest.mock import patch

from src.live_trader import CandidateSignal, LiveAdaptivePaperTrader
from src.models import Signal


class _DisabledExecutor:
    enabled = False


class _EnabledExecutor:
    enabled = True

    def __init__(self, account: dict | None = None, close_result: dict | None = None):
        self._account = account or {"positions": []}
        self._close_result = close_result or {"status": "closed", "executed": True}

    def get_account(self) -> dict:
        return self._account

    def close_trade(self, symbol: str, side: str, reason: str = "") -> dict:
        return dict(self._close_result)


def _config() -> dict:
    return {
        "account": {"starting_balance_usd": 10.0, "risk_per_trade_pct": 0.02},
        "execution": {"fee_bps_per_side": 2, "slippage_bps_per_side": 1},
        "strategy": {
            "ema_fast": 8,
            "ema_slow": 34,
            "rsi_period": 14,
            "atr_period": 14,
            "atr_multiplier": 1.2,
            "risk_reward": 1.0,
            "min_atr_pct": 0.0015,
            "max_atr_pct": 0.01,
            "funding_abs_limit": 0.001,
            "min_confidence": 0.65,
            "long_rsi_min": 45,
            "long_rsi_max": 70,
            "short_rsi_min": 20,
            "short_rsi_max": 50,
        },
        "live_loop": {
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "timeframes": ["5m"],
            "lookback_candles": 260,
            "poll_seconds": 0,
            "execute_min_confidence": 0.75,
            "execute_min_expectancy_r": 0.2,
            "execute_min_score": 0.75,
            "execute_min_win_probability": 0.5,
            "min_candidate_confidence": 0.73,
            "min_candidate_expectancy_r": 0.18,
            "require_dual_timeframe_confirm": False,
            "max_cycles": 1,
            "target_trades": 999,
            "min_trades_for_success": 999,
        },
        "scanner": {"enable_sound": False},
    }


def _trader(cfg: dict | None = None) -> LiveAdaptivePaperTrader:
    with patch("src.live_trader.bootstrap.BinanceExecutor.from_env", return_value=_DisabledExecutor()):
        return LiveAdaptivePaperTrader(cfg or _config())


def _candidate(symbol: str, confidence: float, expectancy_r: float, score: float, reason: str = "LONG pullback | test", side: str = "LONG", timeframe: str = "5m") -> CandidateSignal:
    signal = Signal(symbol=symbol, timeframe=timeframe, side=side, entry=100.0, take_profit=101.0, stop_loss=99.0, confidence=confidence, reason=reason, signal_time_ms=1)
    return CandidateSignal(signal=signal, trend_strength=0.01, cost_r=0.01, rr=1.0, expectancy_r=expectancy_r, symbol_quality=1.0, score=score)


def _json_lines(calls):
    return [json.loads(call.args[0]) for call in calls if call.args and isinstance(call.args[0], str) and call.args[0].startswith("{")]
