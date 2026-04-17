from __future__ import annotations

import pytest

from run_today_replay import ReplayClient, _utc_window_bounds
from src.models import Candle, MarketContext


def test_replay_client_hides_future_candles_and_prices() -> None:
    candles = [
        Candle(
            open_time_ms=1_000,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=10.0,
            close_time_ms=2_000,
        ),
        Candle(
            open_time_ms=2_001,
            open=100.5,
            high=102.0,
            low=100.0,
            close=101.5,
            volume=12.0,
            close_time_ms=3_000,
        ),
    ]
    client = ReplayClient(
        candles_by_market={("BTCUSDT", "5m"): candles},
        market_by_symbol={"BTCUSDT": MarketContext(mark_price=999.0, funding_rate=0.0001, open_interest=12345.0)},
        latest_price_by_symbol={"BTCUSDT": 101.5},
    )

    client.set_time(2_000)

    visible = client.fetch_klines("BTCUSDT", "5m", limit=10)
    assert visible == candles[:1]
    assert client.fetch_all_ticker_prices()["BTCUSDT"] == 100.5

    market = client.fetch_market_context("BTCUSDT")
    assert market.mark_price == 100.5
    assert market.funding_rate == pytest.approx(0.0001)
    assert market.open_interest == pytest.approx(12345.0)


def test_utc_window_bounds_accepts_same_day_range() -> None:
    start_ms, end_ms = _utc_window_bounds("2026-04-17", "12:00", "14:00")
    assert end_ms > start_ms
    assert end_ms - start_ms == 7_260_000


def test_utc_window_bounds_rejects_reversed_range() -> None:
    with pytest.raises(ValueError):
        _utc_window_bounds("2026-04-17", "14:00", "12:00")
