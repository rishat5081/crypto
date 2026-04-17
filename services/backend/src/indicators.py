from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from .models import Candle


def _as_list(values: Iterable[float]) -> List[float]:
    return list(values)


def ema(values: Iterable[float], period: int) -> float:
    series = _as_list(values)
    if len(series) < period:
        raise ValueError("Not enough values for EMA")

    k = 2 / (period + 1)
    current = sum(series[:period]) / period
    for v in series[period:]:
        current = (v * k) + (current * (1 - k))
    return current


def ema_series(values: Iterable[float], period: int) -> List[float]:
    """Return full EMA series (one value per input value after warm-up)."""
    series = _as_list(values)
    if len(series) < period:
        raise ValueError("Not enough values for EMA series")

    k = 2 / (period + 1)
    current = sum(series[:period]) / period
    result = [current]
    for v in series[period:]:
        current = (v * k) + (current * (1 - k))
        result.append(current)
    return result


def rsi(values: Iterable[float], period: int) -> float:
    series = _as_list(values)
    if len(series) <= period:
        raise ValueError("Not enough values for RSI")

    gains = []
    losses = []
    for i in range(1, len(series)):
        diff = series[i] - series[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(abs(min(diff, 0.0)))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(candles: List[Candle], period: int) -> float:
    if len(candles) <= period:
        raise ValueError("Not enough candles for ATR")

    true_ranges: List[float] = []
    for i in range(1, len(candles)):
        curr = candles[i]
        prev = candles[i - 1]
        tr = max(
            curr.high - curr.low,
            abs(curr.high - prev.close),
            abs(curr.low - prev.close),
        )
        true_ranges.append(tr)

    atr_value = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr_value = ((atr_value * (period - 1)) + tr) / period

    return atr_value


def adx(candles: List[Candle], period: int = 14) -> float:
    """Average Directional Index — measures trend strength (0-100)."""
    val, _, _ = adx_components(candles, period)
    return val


def adx_components(candles: List[Candle], period: int = 14) -> tuple:
    """Return (adx, plus_di, minus_di).

    Requires at least ``2 * period + 1`` candles for proper warm-up.
    """
    min_len = 2 * period + 1
    if len(candles) < min_len:
        raise ValueError(f"Need at least {min_len} candles for ADX({period})")

    plus_dm_list: List[float] = []
    minus_dm_list: List[float] = []
    tr_list: List[float] = []

    for i in range(1, len(candles)):
        curr, prev = candles[i], candles[i - 1]
        up_move = curr.high - prev.high
        down_move = prev.low - curr.low
        plus_dm_list.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm_list.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        tr = max(curr.high - curr.low, abs(curr.high - prev.close), abs(curr.low - prev.close))
        tr_list.append(tr)

    # Wilder smoothing helper
    def _smooth(values: List[float], p: int) -> List[float]:
        s = sum(values[:p])
        result = [s]
        for v in values[p:]:
            s = s - s / p + v
            result.append(s)
        return result

    smooth_tr = _smooth(tr_list, period)
    smooth_plus = _smooth(plus_dm_list, period)
    smooth_minus = _smooth(minus_dm_list, period)

    dx_list: List[float] = []
    last_plus_di = 0.0
    last_minus_di = 0.0
    for i in range(len(smooth_tr)):
        tr_s = smooth_tr[i]
        if tr_s == 0:
            dx_list.append(0.0)
            continue
        pdi = 100.0 * smooth_plus[i] / tr_s
        mdi = 100.0 * smooth_minus[i] / tr_s
        last_plus_di = pdi
        last_minus_di = mdi
        di_sum = pdi + mdi
        dx_list.append(abs(pdi - mdi) / di_sum * 100.0 if di_sum > 0 else 0.0)

    if len(dx_list) < period:
        return (0.0, last_plus_di, last_minus_di)

    adx_val = sum(dx_list[:period]) / period
    for dx in dx_list[period:]:
        adx_val = (adx_val * (period - 1) + dx) / period

    return (adx_val, last_plus_di, last_minus_di)


def bollinger_bands(values: Iterable[float], period: int = 20, num_std: float = 2.0) -> tuple:
    """Return (upper, middle, lower) Bollinger Bands for the last bar."""
    series = _as_list(values)
    if len(series) < period:
        raise ValueError(f"Need at least {period} values for Bollinger Bands")
    window = series[-period:]
    middle = sum(window) / period
    variance = sum((v - middle) ** 2 for v in window) / period
    std = variance ** 0.5
    return (middle + num_std * std, middle, middle - num_std * std)


def bb_width(values: Iterable[float], period: int = 20, num_std: float = 2.0) -> float:
    """Normalized Bollinger Band width: (upper - lower) / middle."""
    upper, middle, lower = bollinger_bands(values, period, num_std)
    if middle == 0:
        return 0.0
    return (upper - lower) / middle


def supertrend(candles: List[Candle], period: int = 10, multiplier: float = 3.0) -> tuple:
    """Return (supertrend_value, direction) for the last bar.

    direction is ``"UP"`` (bullish — price above ST) or ``"DOWN"`` (bearish).
    """
    series = supertrend_series(candles, period, multiplier)
    return series[-1]


def supertrend_series(candles: List[Candle], period: int = 10, multiplier: float = 3.0) -> List[tuple]:
    """Full SuperTrend series: list of (value, direction) tuples."""
    if len(candles) <= period:
        raise ValueError(f"Need more than {period} candles for SuperTrend")

    # Compute ATR series using Wilder smoothing
    tr_list: List[float] = []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        tr_list.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))

    atr_series: List[float] = []
    atr_val = sum(tr_list[:period]) / period
    atr_series.append(atr_val)
    for tr in tr_list[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period
        atr_series.append(atr_val)

    # atr_series[0] corresponds to candles[period]
    result: List[tuple] = []
    prev_upper = 0.0
    prev_lower = 0.0
    prev_st = 0.0
    prev_dir = "UP"

    for j in range(len(atr_series)):
        ci = period + j  # candle index
        c = candles[ci]
        hl2 = (c.high + c.low) / 2.0
        a = atr_series[j]

        basic_upper = hl2 + multiplier * a
        basic_lower = hl2 - multiplier * a

        # Final bands carry forward if they haven't been breached
        upper = min(basic_upper, prev_upper) if (basic_upper < prev_upper or candles[ci - 1].close > prev_upper) else basic_upper
        lower = max(basic_lower, prev_lower) if (basic_lower > prev_lower or candles[ci - 1].close < prev_lower) else basic_lower

        # Fix: proper band carry-forward logic
        if prev_upper != 0:
            upper = basic_upper if candles[ci - 1].close > prev_upper else min(basic_upper, prev_upper)
        else:
            upper = basic_upper
        if prev_lower != 0:
            lower = basic_lower if candles[ci - 1].close < prev_lower else max(basic_lower, prev_lower)
        else:
            lower = basic_lower

        # Direction logic
        if j == 0:
            direction = "UP" if c.close > upper else "DOWN"
            st_val = lower if direction == "UP" else upper
        else:
            if prev_dir == "UP":
                direction = "DOWN" if c.close < lower else "UP"
            else:
                direction = "UP" if c.close > upper else "DOWN"
            st_val = lower if direction == "UP" else upper

        result.append((st_val, direction))
        prev_upper = upper
        prev_lower = lower
        prev_st = st_val
        prev_dir = direction

    return result


def macd(
    values: Iterable[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> Tuple[float, float, float]:
    """Return (macd_line, signal_line, histogram)."""
    series = _as_list(values)
    if len(series) < slow + signal:
        raise ValueError(f"Need at least {slow + signal} values for MACD")
    fast_ema = ema_series(series, fast)
    slow_ema = ema_series(series, slow)
    offset = slow - fast
    macd_line_series: List[float] = []
    for i in range(len(slow_ema)):
        macd_line_series.append(fast_ema[i + offset] - slow_ema[i])
    if len(macd_line_series) < signal:
        raise ValueError("Not enough data for MACD signal line")
    signal_ema = ema_series(macd_line_series, signal)
    m = macd_line_series[-1]
    s = signal_ema[-1]
    return (m, s, m - s)


def macd_histogram_series(
    values: Iterable[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> List[float]:
    """Return recent MACD histogram values (last 5 bars)."""
    series = _as_list(values)
    if len(series) < slow + signal:
        raise ValueError(f"Need at least {slow + signal} values for MACD")
    fast_ema = ema_series(series, fast)
    slow_ema = ema_series(series, slow)
    offset = slow - fast
    macd_line_series: List[float] = []
    for i in range(len(slow_ema)):
        macd_line_series.append(fast_ema[i + offset] - slow_ema[i])
    signal_ema = ema_series(macd_line_series, signal)
    offset2 = len(macd_line_series) - len(signal_ema)
    hist: List[float] = []
    for i in range(len(signal_ema)):
        hist.append(macd_line_series[i + offset2] - signal_ema[i])
    return hist[-5:] if len(hist) >= 5 else hist


def keltner_channels(
    candles: List[Candle], ema_period: int = 20, atr_period: int = 10, multiplier: float = 1.5
) -> Tuple[float, float, float]:
    """Return (upper, middle, lower) Keltner Channel values."""
    close_prices = [c.close for c in candles]
    if len(close_prices) < ema_period:
        raise ValueError(f"Need at least {ema_period} candles for Keltner Channels")
    middle = ema(close_prices, ema_period)
    atr_val = atr(candles, atr_period)
    return (middle + multiplier * atr_val, middle, middle - multiplier * atr_val)


def is_squeeze(
    candles: List[Candle],
    bb_period: int = 20,
    bb_std: float = 2.0,
    kc_period: int = 20,
    kc_atr_period: int = 10,
    kc_mult: float = 1.5,
) -> bool:
    """True when Bollinger Bands fit inside Keltner Channels (volatility squeeze)."""
    close_prices = [c.close for c in candles]
    if len(close_prices) < max(bb_period, kc_period) or len(candles) <= kc_atr_period:
        return False
    bb_upper, _, bb_lower = bollinger_bands(close_prices, bb_period, bb_std)
    kc_upper, _, kc_lower = keltner_channels(candles, kc_period, kc_atr_period, kc_mult)
    return bb_lower > kc_lower and bb_upper < kc_upper


def swing_highs_lows(
    candles: List[Candle], lookback: int = 5
) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """Detect swing highs and lows. Returns (highs, lows) as (index, price) lists."""
    highs: List[Tuple[int, float]] = []
    lows: List[Tuple[int, float]] = []
    for i in range(lookback, len(candles) - lookback):
        is_high = all(candles[i].high >= candles[i + d].high for d in range(-lookback, lookback + 1) if d != 0)
        is_low = all(candles[i].low <= candles[i + d].low for d in range(-lookback, lookback + 1) if d != 0)
        if is_high:
            highs.append((i, candles[i].high))
        if is_low:
            lows.append((i, candles[i].low))
    return (highs, lows)


def rsi_divergence(
    candles: List[Candle], rsi_period: int = 14, swing_lookback: int = 5
) -> Optional[str]:
    """Detect RSI divergence. Returns 'BULLISH_DIVERGENCE', 'BEARISH_DIVERGENCE', or None."""
    if len(candles) < rsi_period + swing_lookback * 2 + 10:
        return None
    close_prices = [c.close for c in candles]
    rsi_vals: List[float] = []
    for i in range(rsi_period + 1, len(close_prices) + 1):
        rsi_vals.append(rsi(close_prices[:i], rsi_period))

    _, price_lows = swing_highs_lows(candles, swing_lookback)
    price_highs, _ = swing_highs_lows(candles, swing_lookback)

    # Bullish: price makes lower low but RSI makes higher low
    if len(price_lows) >= 2:
        prev_low_idx, prev_low_price = price_lows[-2]
        curr_low_idx, curr_low_price = price_lows[-1]
        rsi_offset = len(candles) - len(rsi_vals)
        prev_rsi_idx = prev_low_idx - rsi_offset
        curr_rsi_idx = curr_low_idx - rsi_offset
        if 0 <= prev_rsi_idx < len(rsi_vals) and 0 <= curr_rsi_idx < len(rsi_vals):
            if curr_low_price < prev_low_price and rsi_vals[curr_rsi_idx] > rsi_vals[prev_rsi_idx]:
                return "BULLISH_DIVERGENCE"

    # Bearish: price makes higher high but RSI makes lower high
    if len(price_highs) >= 2:
        prev_high_idx, prev_high_price = price_highs[-2]
        curr_high_idx, curr_high_price = price_highs[-1]
        rsi_offset = len(candles) - len(rsi_vals)
        prev_rsi_idx = prev_high_idx - rsi_offset
        curr_rsi_idx = curr_high_idx - rsi_offset
        if 0 <= prev_rsi_idx < len(rsi_vals) and 0 <= curr_rsi_idx < len(rsi_vals):
            if curr_high_price > prev_high_price and rsi_vals[curr_rsi_idx] < rsi_vals[prev_rsi_idx]:
                return "BEARISH_DIVERGENCE"

    return None


def support_resistance_zones(
    candles: List[Candle], lookback: int = 5, merge_pct: float = 0.003
) -> List[Tuple[float, int]]:
    """Detect support/resistance zones by clustering swing points.

    Returns list of ``(level, touch_count)`` sorted by touch_count descending.
    ``merge_pct`` controls how close two swing points must be to merge into one
    zone (as a fraction of price, e.g. 0.003 = 0.3%).
    """
    if len(candles) < lookback * 2 + 1:
        return []

    highs, lows = swing_highs_lows(candles, lookback)
    levels: List[float] = [price for _, price in highs] + [price for _, price in lows]
    if not levels:
        return []

    levels.sort()

    # Cluster nearby levels into zones
    zones: List[Tuple[float, int]] = []
    i = 0
    while i < len(levels):
        cluster = [levels[i]]
        j = i + 1
        while j < len(levels) and (levels[j] - cluster[0]) / max(cluster[0], 1e-9) <= merge_pct:
            cluster.append(levels[j])
            j += 1
        zone_level = sum(cluster) / len(cluster)
        # Count how many candles touched this zone
        touch_count = len(cluster)
        for c in candles:
            if abs(c.low - zone_level) / max(zone_level, 1e-9) <= merge_pct:
                touch_count += 1
            elif abs(c.high - zone_level) / max(zone_level, 1e-9) <= merge_pct:
                touch_count += 1
        zones.append((zone_level, touch_count))
        i = j

    zones.sort(key=lambda z: -z[1])
    return zones


def volume_profile(
    candles: List[Candle], num_bins: int = 20
) -> List[Tuple[float, float]]:
    """Simple volume profile: sum volume in price bins.

    Returns ``(price_level, total_volume)`` sorted by volume descending.
    High-volume nodes indicate institutional interest / likely S/R.
    """
    if not candles or num_bins < 1:
        return []

    low = min(c.low for c in candles)
    high = max(c.high for c in candles)
    price_range = high - low
    if price_range <= 0:
        mid = (high + low) / 2
        total_vol = sum(c.volume for c in candles)
        return [(mid, total_vol)]

    bin_size = price_range / num_bins
    bins: List[float] = [0.0] * num_bins

    for c in candles:
        candle_low = c.low
        candle_high = c.high
        candle_range = candle_high - candle_low
        if candle_range <= 0:
            idx = min(int((c.close - low) / bin_size), num_bins - 1)
            bins[idx] += c.volume
            continue
        for b in range(num_bins):
            bin_low = low + b * bin_size
            bin_high = bin_low + bin_size
            overlap = max(0, min(candle_high, bin_high) - max(candle_low, bin_low))
            if overlap > 0:
                bins[b] += c.volume * (overlap / candle_range)

    result: List[Tuple[float, float]] = []
    for b in range(num_bins):
        price_level = low + (b + 0.5) * bin_size
        result.append((price_level, bins[b]))

    result.sort(key=lambda x: -x[1])
    return result


def multi_tf_trend(
    htf_candles: List[Candle],
    ltf_candles: List[Candle],
    ema_period: int = 50,
) -> dict:
    """Determine higher-timeframe directional bias and lower-timeframe alignment.

    Returns ``{"bias": "BULL"/"BEAR"/"NEUTRAL", "htf_trend": float, "ltf_aligned": bool}``.
    """
    result: dict = {"bias": "NEUTRAL", "htf_trend": 0.0, "ltf_aligned": False}

    if not htf_candles or len(htf_candles) < ema_period:
        return result

    htf_closes = [c.close for c in htf_candles]
    htf_ema = ema(htf_closes, ema_period)
    htf_price = htf_candles[-1].close
    htf_trend = (htf_price - htf_ema) / htf_ema if htf_ema else 0.0
    result["htf_trend"] = htf_trend

    if htf_trend > 0.002:
        result["bias"] = "BULL"
    elif htf_trend < -0.002:
        result["bias"] = "BEAR"

    if ltf_candles and len(ltf_candles) >= ema_period:
        ltf_closes = [c.close for c in ltf_candles]
        ltf_ema = ema(ltf_closes, ema_period)
        ltf_price = ltf_candles[-1].close
        ltf_trend = (ltf_price - ltf_ema) / ltf_ema if ltf_ema else 0.0
        if (result["bias"] == "BULL" and ltf_trend > 0) or (result["bias"] == "BEAR" and ltf_trend < 0):
            result["ltf_aligned"] = True

    return result
