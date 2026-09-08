"""The trader's chart pattern: impulse -> pullback -> divergent double bottom.

Described from an ARB/USDT 15m chart: a big run up, then a pullback, then a VMC
bullish divergence, then price retraces and forms a DOUBLE BOTTOM, and that
second bottom is the entry. Reported as high accuracy and high reward:risk.

The neat part is that the divergence and the double bottom are the SAME two
points: two price lows at roughly equal levels, with the oscillator making a
higher low between them. So the pattern is one object, not two conditions
stacked.

Structure detected, in order:

    1. IMPULSE   price rose >= imp_pct into a confirmed swing high
    2. PULLBACK  price then fell >= pb_min_pct off that high
    3. LOW 1     a confirmed pivot low
    4. LOW 2     a later confirmed pivot low within db_tol of LOW 1
    5. DIVERGENCE  WT2 at LOW 2 is higher than WT2 at LOW 1
    6. NECKLINE  the high between the two lows, used for the measured move

The signal is emitted on the bar that CONFIRMS low 2 (low2 + pivot_n bars), so
nothing here looks forward. Entry is the next bar's open, as everywhere else.
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

from strategies import atr                              # noqa: E402
from backend.indicators import common, wavetrend        # noqa: E402


def _pivots(series: pd.Series, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Fractal pivot low / pivot high masks with n bars either side."""
    v = series.to_numpy()
    size = len(v)
    lows = np.zeros(size, dtype=bool)
    highs = np.zeros(size, dtype=bool)
    for i in range(n, size - n):
        w = v[i - n:i + n + 1]
        if v[i] == w.min() and (w == v[i]).sum() == 1:
            lows[i] = True
        if v[i] == w.max() and (w == v[i]).sum() == 1:
            highs[i] = True
    return lows, highs


def impulse_double_bottom(
        df: pd.DataFrame, *, side: str = "long",
        # --- structure ---
        pivot_n: int = 3,
        imp_pct: float = 0.06,          # size of the run up, low -> high
        imp_lookback: int = 60,         # bars the run up may take
        pb_min_pct: float = 0.03,       # minimum pullback off the high
        pb_max_pct: float = 0.25,       # beyond this it is a reversal, not a pullback
        db_tol: float = 0.015,          # how equal the two lows must be
        db_min_bars: int = 4,           # separation between the two lows
        db_max_bars: int = 60,
        require_divergence: bool = True,
        require_higher_low: bool = False,   # stricter: low2 strictly above low1
        # --- risk ---
        atr_mult: float = 0.5, atr_len: int = 14,
        max_risk_pct: float = 0.10,
        gate: pd.Series | None = None,
        gate_allow: tuple[str, ...] = ("bull", "neutral"),
) -> pd.DataFrame:
    """Emit one signal per confirmed divergent double bottom.

    Returns the usual (direction, stop) frame, plus `neckline` so an exit plan
    can use the measured move if it wants to.
    """
    direction = 1 if side == "long" else -1
    if direction < 0:
        # mirror the whole structure: double TOP after an impulse down
        flipped = pd.DataFrame({"open": -df["open"], "high": -df["low"],
                                "low": -df["high"], "close": -df["close"],
                                "volume": df["volume"]}, index=df.index)
        out = impulse_double_bottom(
            flipped, side="long", pivot_n=pivot_n, imp_pct=imp_pct,
            imp_lookback=imp_lookback, pb_min_pct=pb_min_pct,
            pb_max_pct=pb_max_pct, db_tol=db_tol, db_min_bars=db_min_bars,
            db_max_bars=db_max_bars, require_divergence=require_divergence,
            require_higher_low=require_higher_low, atr_mult=atr_mult,
            atr_len=atr_len, max_risk_pct=max_risk_pct, gate=None)
        if out.empty:
            return out
        out["direction"] = -1
        out["stop"] = -out["stop"]
        if gate is not None:
            keep = [ts for ts in out.index
                    if gate.get(ts, "unknown") in gate_allow]
            out = out.loc[keep]
        return out

    wt1, wt2 = wavetrend.wavetrend(df)
    a = atr(df, atr_len).to_numpy()
    low_mask, high_mask = _pivots(df["low"], pivot_n)
    _, close_high_mask = _pivots(df["high"], pivot_n)

    lows_idx = np.flatnonzero(low_mask)
    highs_idx = np.flatnonzero(close_high_mask)
    low_v = df["low"].to_numpy()
    high_v = df["high"].to_numpy()
    close_v = df["close"].to_numpy()
    wt2_v = wt2.to_numpy()
    n = len(df)

    rows = []
    for pos2 in range(1, len(lows_idx)):
        i2 = lows_idx[pos2]
        i_conf = i2 + pivot_n                     # bar that confirms low 2
        if i_conf >= n or not np.isfinite(a[i_conf]):
            continue

        # --- find a matching earlier low: the other half of the double bottom
        for pos1 in range(pos2 - 1, -1, -1):
            i1 = lows_idx[pos1]
            gap = i2 - i1
            if gap > db_max_bars:
                break
            if gap < db_min_bars:
                continue
            l1, l2 = low_v[i1], low_v[i2]
            if l1 <= 0 or abs(l2 - l1) / l1 > db_tol:
                continue
            if require_higher_low and l2 < l1:
                continue

            # --- the divergence: oscillator higher low across the two bottoms
            if require_divergence and not (wt2_v[i2] > wt2_v[i1]):
                continue

            # --- neckline: the highest point between the two lows
            neck = high_v[i1:i2 + 1].max()
            if neck <= max(l1, l2):
                continue

            # --- the impulse that came BEFORE low 1, and the pullback into it
            start = max(0, i1 - imp_lookback)
            if start >= i1:
                continue
            swing_high = high_v[start:i1].max()
            swing_low = low_v[start:i1].min()
            if swing_low <= 0 or swing_high <= 0:
                continue
            if (swing_high - swing_low) / swing_low < imp_pct:
                continue                          # the run up was not big enough
            pullback = (swing_high - l1) / swing_high
            if not (pb_min_pct <= pullback <= pb_max_pct):
                continue

            ts = df.index[i_conf]
            if gate is not None and gate.get(ts, "unknown") not in gate_allow:
                break
            stop = min(l1, l2) - atr_mult * a[i_conf]
            ref = close_v[i_conf]
            if stop <= 0 or ref <= 0 or (ref - stop) / ref > max_risk_pct:
                break
            rows.append({"ts": ts, "direction": 1, "stop": float(stop),
                         "neckline": float(neck)})
            break                                  # one signal per low 2

    if not rows:
        return pd.DataFrame(columns=["direction", "stop", "neckline"])
    out = pd.DataFrame(rows).set_index("ts")
    return out[~out.index.duplicated(keep="first")].sort_index()
