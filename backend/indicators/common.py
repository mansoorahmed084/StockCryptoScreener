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
