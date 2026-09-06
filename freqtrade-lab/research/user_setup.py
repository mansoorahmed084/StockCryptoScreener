"""The trader's own observed setup, made testable.

Described as: on 4h, when the oscillator has RESET and crosses up from below,
with RSI also under 30 and turning up, while the OVERALL TREND IS UP, you get a
good long. A divergence present at the same time makes it stronger. Expect at
least a 2-3% move. Mirror it for shorts.

Broken into four independent, separately switchable conditions so the sweep can
measure what each one actually contributes rather than testing the bundle as an
article of faith:

    1. trend      higher-timeframe direction agrees with the trade
    2. reset      stochastic is in the oversold zone (the "reset")
    3. cross      stochastic %K crosses up through %D out of that zone
    4. rsi        RSI below its threshold, and turning up

Plus an optional 5th: a confirmed VMC divergence within the last N bars, which
the trader flagged as a strength booster rather than a requirement.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strategies import atr, _vmc_panes                # noqa: E402
from hf_strategies import _emit                       # noqa: E402
from backend.indicators import common                 # noqa: E402


def stochastic(df: pd.DataFrame, k_len: int = 14, k_smooth: int = 3,
               d_smooth: int = 3) -> tuple[pd.Series, pd.Series]:
    """Classic slow stochastic: %K smoothed, %D = SMA of %K."""
    low = df["low"].rolling(k_len, min_periods=k_len).min()
    high = df["high"].rolling(k_len, min_periods=k_len).max()
    rng = (high - low).replace(0, np.nan)
    raw_k = 100 * (df["close"] - low) / rng
    k = common.sma(raw_k, k_smooth)
    d = common.sma(k, d_smooth)
    return k, d


def _divergence_recent(df: pd.DataFrame, side: str, within: int,
                       pivot_lookback: int = 3) -> pd.Series:
    """True on bars where a confirmed VMC divergence landed in the last `within`.

    Confirmation lag is respected: a pivot at bar p is only knowable at p+lookback.
    """
    res, _, _ = _vmc_panes(df, pivot_lookback)
    want = "bull_div" if side == "long" else "bear_div"
    flag = np.zeros(len(df), dtype=bool)
    n = len(df)
    for m in res.markers:
        if m.kind != want:
            continue
        p_conf = df.index.get_loc(m.ts) + pivot_lookback
        if p_conf < n:
            flag[p_conf:min(p_conf + within, n)] = True
    return pd.Series(flag, index=df.index)


def stoch_rsi_reset(df: pd.DataFrame, *, side: str = "long",
                    # --- condition switches ---
                    # use_trend applies a SAME-timeframe EMA filter. Default off:
                    # on 4h, "close > EMA200" and "RSI < 30" are near-contradictory
                    # (measured n=1 over 6 years). "Overall trend is up" means the
                    # HIGHER timeframe, which is supplied through `gate` instead.
                    use_trend: bool = False, use_reset: bool = True,
                    use_cross: bool = True, use_rsi: bool = True,
                    require_div: bool = False,
                    # --- thresholds ---
                    trend_len: int = 200,
                    stoch_k: int = 14, stoch_smooth: int = 3, stoch_d: int = 3,
                    stoch_reset: float = 20.0,
                    rsi_len: int = 14, rsi_extreme: float = 30.0,
                    rsi_turning: bool = True,
                    div_within: int = 6, pivot_lookback: int = 3,
                    # --- risk ---
                    atr_mult: float = 1.0, atr_len: int = 14,
                    max_risk_pct: float = 0.10,
                    gate: pd.Series | None = None,
                    gate_allow: tuple[str, ...] = ("bull", "neutral")
                    ) -> pd.DataFrame:
    """The trader's setup. Every condition can be switched off to measure it."""
    direction = 1 if side == "long" else -1
    k, d = stochastic(df, stoch_k, stoch_smooth, stoch_d)
    r = common.rsi(df["close"], rsi_len)
    ema_trend = common.ema(df["close"], trend_len)
    a = atr(df, atr_len)

    trig = pd.Series(True, index=df.index)

    if direction > 0:
        if use_trend:
            trig &= df["close"] > ema_trend
        if use_reset:
            # the "reset": stochastic was down in the oversold zone recently
            trig &= (k.shift(1) <= stoch_reset) | (d.shift(1) <= stoch_reset)
        if use_cross:
            trig &= (k.shift(1) <= d.shift(1)) & (k > d)
        if use_rsi:
            trig &= r <= rsi_extreme
            if rsi_turning:
                trig &= r > r.shift(1)          # "and then it tries to go up"
        stop = df["low"].rolling(3, min_periods=1).min() - atr_mult * a
    else:
        if use_trend:
            trig &= df["close"] < ema_trend
        if use_reset:
            trig &= ((k.shift(1) >= 100 - stoch_reset)
                     | (d.shift(1) >= 100 - stoch_reset))
        if use_cross:
            trig &= (k.shift(1) >= d.shift(1)) & (k < d)
        if use_rsi:
            trig &= r >= 100 - rsi_extreme
            if rsi_turning:
                trig &= r < r.shift(1)
        stop = df["high"].rolling(3, min_periods=1).max() + atr_mult * a

    if require_div:
        trig &= _divergence_recent(df, side, div_within, pivot_lookback)

    return _emit(df, trig, direction, stop, gate, gate_allow, max_risk_pct)
