"""Shared indicator primitives (pure pandas/numpy)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length, min_periods=1).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def hlc3(df: pd.DataFrame) -> pd.Series:
    return (df["high"] + df["low"] + df["close"]) / 3.0


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1 / length, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / length, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def vumanchu_moneyflow(df: pd.DataFrame, period: int = 60,
                       multiplier: float = 150.0) -> pd.Series:
    """VuManChu's RSI+MFI area: sma(((close-open)/(high-low))*mult, period)."""
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    raw = ((df["close"] - df["open"]) / rng) * multiplier
    return sma(raw.fillna(0.0), period)


def pivot_lows(series: pd.Series, left: int = 3, right: int = 3) -> pd.Series:
    """Boolean mask of fractal pivot lows (strict local minima)."""
    vals = series.to_numpy()
    n = len(vals)
    out = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        window = vals[i - left:i + right + 1]
        if vals[i] == window.min() and (window == vals[i]).sum() == 1:
            out[i] = True
    return pd.Series(out, index=series.index)


def pivot_highs(series: pd.Series, left: int = 3, right: int = 3) -> pd.Series:
    """Boolean mask of fractal pivot highs (strict local maxima)."""
    vals = series.to_numpy()
    n = len(vals)
    out = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        window = vals[i - left:i + right + 1]
        if vals[i] == window.max() and (window == vals[i]).sum() == 1:
            out[i] = True
    return pd.Series(out, index=series.index)


# --- primitives added for the sentiment composite and the wave/flow matrix ----
def rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder's moving average (the smoothing inside RSI and ATR)."""
    return series.ewm(alpha=1 / length, adjust=False).mean()


def stdev(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length).std(ddof=0)


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return rma(true_range(df), length)


def stochastic(src: pd.Series, high: pd.Series, low: pd.Series, length: int) -> pd.Series:
    """Where ``src`` sits in the high–low range of the last ``length`` bars, 0–100."""
    top = high.rolling(length).max()
    bottom = low.rolling(length).min()
    span = (top - bottom)
    out = 100 * (src - bottom) / span.replace(0, np.nan)
    return out.where(span.isna() | (span != 0), 50.0)


def cci(series: pd.Series, length: int = 20) -> pd.Series:
    mean = series.rolling(length).mean()
    dev = series.rolling(length).apply(lambda w: np.abs(w - w.mean()).mean(), raw=True)
    return (series - mean) / (0.015 * dev.replace(0, np.nan))


def supertrend(df: pd.DataFrame, length: int = 10, mult: float = 3.0) -> pd.Series:
    """The Supertrend line: an ATR band that trails price and flips side when
    the close goes through it."""
    mid = ((df["high"] + df["low"]) / 2).to_numpy()
    rng = (atr(df, length) * mult).to_numpy()
    close = df["close"].to_numpy()
    n = len(close)
    line = np.full(n, np.nan)
    upper = lower = np.nan
    bull = True
    for i in range(n):
        up, lo = mid[i] + rng[i], mid[i] - rng[i]
        if np.isnan(up):
            continue
        if np.isnan(upper):
            upper, lower = up, lo
        else:
            upper = up if (up < upper or close[i - 1] > upper) else upper
            lower = lo if (lo > lower or close[i - 1] < lower) else lower
            if bull and close[i] < lower:
                bull = False
            elif not bull and close[i] > upper:
                bull = True
        line[i] = lower if bull else upper
    return pd.Series(line, index=df.index)


def time_correlation(series: pd.Series, length: int) -> pd.Series:
    """Rolling correlation of a series with bar number: +1 a clean rise, -1 a
    clean fall, 0 no direction."""
    bar = pd.Series(np.arange(len(series), dtype=float), index=series.index)
    return series.rolling(length).corr(bar)


def session_vwap_bands(df: pd.DataFrame, mult: float = 2.0
                       ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """VWAP restarting each UTC day, with volume-weighted deviation bands."""
    tp = hlc3(df)
    vol = df["volume"]
    day = df.index.floor("D")
    v = vol.groupby(day).cumsum().replace(0, np.nan)
    vwap = (tp * vol).groupby(day).cumsum() / v
    var = ((tp * tp * vol).groupby(day).cumsum() / v - vwap ** 2).clip(lower=0)
    band = np.sqrt(var) * mult
    return vwap, vwap + band, vwap - band


def zone_scale(values: pd.Series, breaks, levels=(0, 25, 50, 75, 100)) -> pd.Series:
    """Piecewise-linear map of an oscillator onto 0–100: each of its own zones
    (oversold, lower half, upper half, overbought) becomes a quarter of the scale."""
    out = np.interp(values.to_numpy(dtype=float), breaks, levels)
    return pd.Series(out, index=values.index).where(values.notna())


def pivot_divergences(price_low: pd.Series, price_high: pd.Series, osc: pd.Series,
                      lookback: int, mid: float = 0.0, max_gap: int = 60
                      ) -> tuple[list[int], list[int]]:
    """Regular divergences between consecutive oscillator pivots.

    Returns (bullish, bearish) as bar positions of the second pivot. A pivot is
    only known ``lookback`` bars after it prints, so a divergence at position
    ``b`` is confirmed at ``b + lookback``.
    """
    lows = np.where(pivot_lows(osc, lookback, lookback).to_numpy())[0]
    highs = np.where(pivot_highs(osc, lookback, lookback).to_numpy())[0]
    o, lo, hi = osc.to_numpy(), price_low.to_numpy(), price_high.to_numpy()
    bull = [int(b) for a, b in zip(lows, lows[1:])
            if b - a <= max_gap and lo[b] < lo[a] and o[b] > o[a] and o[b] < mid]
    bear = [int(b) for a, b in zip(highs, highs[1:])
            if b - a <= max_gap and hi[b] > hi[a] and o[b] < o[a] and o[b] > mid]
    return bull, bear
