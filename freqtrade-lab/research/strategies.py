"""Signal generators for the ETH 1h/4h research sweep.

Every generator returns a DataFrame indexed by the SIGNAL bar (the last closed
bar whose information the trade may use), with columns:
    direction  +1 long / -1 short
    stop       absolute stop price

The harness enters at the next bar's open, so nothing here may look forward.
Divergence pivots are only emitted PIVOT_RIGHT bars after the pivot itself,
which is what makes them knowable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.config import load_config                      # noqa: E402
from backend.indicators.vumanchu import VuManChuCipherB     # noqa: E402
from backend.indicators import common, wavetrend            # noqa: E402
from backend.screener import rs                             # noqa: E402

PIVOT_RIGHT = 3
_CFG = load_config()


# ------------------------------------------------------------------ helpers
def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    prev_c = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev_c).abs(),
                    (df["low"] - prev_c).abs()], axis=1).max(axis=1)
    return tr.rolling(length, min_periods=length).mean()


def regime(df: pd.DataFrame, timeframe: str) -> pd.Series:
    """The repo's noise-filtered bull/bear/neutral state, per bar close."""
    params = _CFG.classifier_params(timeframe)
    hist = rs.classify_history(df["close"], params, drop_forming=False)
    return hist["direction"].reindex(df.index, method="ffill").fillna("unknown")


def higher_tf_regime(df_base: pd.DataFrame, df_high: pd.DataFrame,
                     timeframe: str, bar: pd.Timedelta) -> pd.Series:
    """Map a higher timeframe's state onto base bars, honouring knowability:
    a bar labelled T is only known at T + bar."""
    state = regime(df_high, timeframe)
    known = pd.Series(state.to_numpy(), index=state.index + bar)
    return known.reindex(df_base.index, method="ffill").fillna("unknown")


def atr_percentile(df: pd.DataFrame, length: int = 14,
                   lookback: int = 500) -> pd.Series:
    """Where current ATR sits in its own recent distribution, 0..1."""
    a = atr(df, length) / df["close"]
    return a.rolling(lookback, min_periods=lookback // 4).rank(pct=True)


_VMC_CACHE: dict = {}


def _vmc_panes(df: pd.DataFrame, pivot_lookback: int = 3):
    """Cached: the pivot scan is the slow part and a sweep reuses it hundreds
    of times across parameter combinations."""
    key = (id(df), len(df), pivot_lookback)
    if key not in _VMC_CACHE:
        res = VuManChuCipherB(pivot_lookback=pivot_lookback).compute(df)
        _VMC_CACHE[key] = (res, res.panes.get("wt2"), res.panes.get("wt1"))
    return _VMC_CACHE[key]


# ------------------------------------------------------- divergence signals
def vmc_divergence(df: pd.DataFrame, *, side: str = "long",
                   wt2_extreme: float = -45.0, atr_mult: float = 0.5,
                   atr_len: int = 14, max_risk_pct: float = 0.10,
                   gate: pd.Series | None = None,
                   gate_allow: tuple[str, ...] = ("bull", "neutral"),
                   vol_min: float | None = None,
                   vol_series: pd.Series | None = None,
                   pivot_lookback: int = 3) -> pd.DataFrame:
    """VMC regular divergence, confirmed 3 bars later.

    long  -> bullish divergence, WT2 <= wt2_extreme at the pivot (capitulation)
    short -> bearish divergence, WT2 >= wt2_extreme at the pivot (blow-off)
    """
    res, wt2, _ = _vmc_panes(df, pivot_lookback)
    if wt2 is None:
        return pd.DataFrame(columns=["direction", "stop"])

    want = "bull_div" if side == "long" else "bear_div"
    direction = 1 if side == "long" else -1
    a = atr(df, atr_len).to_numpy()
    n = len(df)
    rows = []

    for m in res.markers:
        if m.kind != want:
            continue
        p = df.index.get_loc(m.ts)
        p_conf = p + pivot_lookback
        if p_conf >= n:
            continue
        wt_at_pivot = float(wt2.iloc[p])
        if direction > 0 and wt_at_pivot > wt2_extreme:
            continue
        if direction < 0 and wt_at_pivot < wt2_extreme:
            continue
        a_conf = a[p_conf]
        if not np.isfinite(a_conf):
            continue

        ts = df.index[p_conf]
        if gate is not None and gate.get(ts, "unknown") not in gate_allow:
            continue
        if vol_min is not None and vol_series is not None:
            v = vol_series.get(ts, np.nan)
            if not np.isfinite(v) or v < vol_min:
                continue

        if direction > 0:
            stop = float(df["low"].iloc[p]) - atr_mult * a_conf
        else:
            stop = float(df["high"].iloc[p]) + atr_mult * a_conf
        ref = float(df["close"].iloc[p_conf])
        if stop <= 0 or ref <= 0:
            continue
        if abs(ref - stop) / ref > max_risk_pct:
            continue
        rows.append({"ts": ts, "direction": direction, "stop": stop})

    if not rows:
        return pd.DataFrame(columns=["direction", "stop"])
    out = pd.DataFrame(rows).set_index("ts")
    return out[~out.index.duplicated(keep="first")].sort_index()


# ------------------------------------------------------------ simple baselines
def wt_cross(df: pd.DataFrame, *, side: str = "long", wt2_extreme: float = -53.0,
             atr_mult: float = 1.5, atr_len: int = 14,
             max_risk_pct: float = 0.10,
             gate: pd.Series | None = None,
             gate_allow: tuple[str, ...] = ("bull", "neutral")) -> pd.DataFrame:
    """WaveTrend cross in the extreme zone. The repo already found this to be an
    anti-edge on 1h alts; kept as a control so the sweep has a known-bad arm."""
    wt1, wt2 = wavetrend.wavetrend(df)
    a = atr(df, atr_len)
    if side == "long":
        trig = (wt1.shift(1) <= wt2.shift(1)) & (wt1 > wt2) & (wt2 <= wt2_extreme)
        direction = 1
    else:
        trig = (wt1.shift(1) >= wt2.shift(1)) & (wt1 < wt2) & (wt2 >= wt2_extreme)
        direction = -1

    rows = []
    for ts in df.index[trig.fillna(False)]:
        a_v = a.get(ts, np.nan)
        if not np.isfinite(a_v):
            continue
        if gate is not None and gate.get(ts, "unknown") not in gate_allow:
            continue
        close = float(df.loc[ts, "close"])
        stop = close - direction * atr_mult * a_v
        if stop <= 0 or abs(close - stop) / close > max_risk_pct:
            continue
        rows.append({"ts": ts, "direction": direction, "stop": stop})

    if not rows:
        return pd.DataFrame(columns=["direction", "stop"])
    return pd.DataFrame(rows).set_index("ts").sort_index()


def bb_reversion(df: pd.DataFrame, *, side: str = "long", window: int = 20,
                 stds: float = 2.0, rsi_len: int = 14,
                 rsi_extreme: float = 30.0, atr_mult: float = 1.0,
                 atr_len: int = 14, max_risk_pct: float = 0.10,
                 gate: pd.Series | None = None,
                 gate_allow: tuple[str, ...] = ("bull", "neutral")) -> pd.DataFrame:
    """Close back inside a Bollinger band after piercing it, with RSI agreeing."""
    mid = common.sma(df["close"], window)
    sd = df["close"].rolling(window, min_periods=window).std(ddof=0)
    lower, upper = mid - stds * sd, mid + stds * sd
    r = common.rsi(df["close"], rsi_len)
    a = atr(df, atr_len)

    if side == "long":
        trig = (df["low"] < lower) & (df["close"] > lower) & (r <= rsi_extreme)
        direction = 1
    else:
        trig = (df["high"] > upper) & (df["close"] < upper) & (r >= 100 - rsi_extreme)
        direction = -1

    rows = []
    for ts in df.index[trig.fillna(False)]:
        a_v = a.get(ts, np.nan)
        if not np.isfinite(a_v):
            continue
        if gate is not None and gate.get(ts, "unknown") not in gate_allow:
            continue
        close = float(df.loc[ts, "close"])
        if direction > 0:
            stop = float(df.loc[ts, "low"]) - atr_mult * a_v
        else:
            stop = float(df.loc[ts, "high"]) + atr_mult * a_v
        if stop <= 0 or abs(close - stop) / close > max_risk_pct:
            continue
        rows.append({"ts": ts, "direction": direction, "stop": stop})

    if not rows:
        return pd.DataFrame(columns=["direction", "stop"])
    return pd.DataFrame(rows).set_index("ts").sort_index()
