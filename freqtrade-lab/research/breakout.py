"""Divergence, then a STRUCTURE BREAK as the trigger.

Five 15m charts supplied by the trader (STX, S, SEI, DOT, TAO) all share the
same shape, and it is not the shape this project has been testing:

    1. price falls / ranges into a low
    2. a VMC bullish divergence prints at that low
    3. price then BREAKS a trendline or the swing high that capped the pullback
    4. the impulsive move happens after the break

Everything tested so far entered at step 2, the moment the divergence confirmed.
The charts enter at step 3. That is a real difference and it is knowable -- the
break is an event in the past when you act on it, not a peek at the future.

The trendline on a chart is drawn by eye, so it is approximated here two ways:

    "swing"  break above the highest high since the divergence pivot
    "slope"  break above a falling line fitted through the highs since the
             pivot, which is closer to what a hand-drawn descending trendline
             does: it lets you in earlier as the line falls toward price

Both are pure functions of bars at or before the trigger.
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
from backend.indicators.vumanchu import VuManChuCipherB  # noqa: E402
from backend.indicators import common                    # noqa: E402

PIVOT = 3

# A full grid re-derives the same divergence markers thousands of times. The
# pivot scan is the expensive part and depends only on (frame, pivot_lookback),
# so cache it. Keyed by id+len, which is safe because frames are loaded once and
# reused by reference from harness.load's caller.
_VMC: dict = {}


def _vmc(df: pd.DataFrame, pivot_lookback: int):
    key = (id(df), len(df), pivot_lookback)
    if key not in _VMC:
        res = VuManChuCipherB(pivot_lookback=pivot_lookback).compute(df)
        bulls = [(df.index.get_loc(m.ts), m.ts) for m in res.markers
                 if m.kind == "bull_div"]
        _VMC[key] = (bulls, res.panes.get("wt2"))
    return _VMC[key]


_MFI: dict = {}


def _mfi(df: pd.DataFrame):
    key = (id(df), len(df))
    if key not in _MFI:
        _MFI[key] = common.vumanchu_moneyflow(df).to_numpy()
    return _MFI[key]


_ATR: dict = {}


def _atr_c(df: pd.DataFrame, length: int):
    key = (id(df), len(df), length)
    if key not in _ATR:
        _ATR[key] = atr(df, length).to_numpy()
    return _ATR[key]


def divergence_breakout(
        df: pd.DataFrame, *, side: str = "long",
        # --- the divergence ---
        wt2_max: float = -40.0,
        pivot_lookback: int = PIVOT,
        # --- the trigger ---
        trigger: str = "swing",       # "swing" | "slope" | "none"
        wait_bars: int = 24,          # how long the break may take
        min_wait: int = 1,            # bars that must pass before a break counts
        # --- filters ---
        mfi_min: float | None = None,   # VMC money-flow area, 0.0 = green only
        require_hold: bool = True,      # void it if the pivot low is broken first
        # --- market breadth: how oversold the WHOLE universe is at the trigger,
        # as a percentile of its own history. Tests whether a cluster of
        # simultaneous signals is a washout to buy or a knife to avoid.
        breadth: pd.Series | None = None,
        breadth_min: float | None = None,
        breadth_max: float | None = None,
        # --- risk ---
        atr_mult: float = 1.0, atr_len: int = 14,
        max_risk_pct: float = 0.12,
        gate: pd.Series | None = None,
        gate_allow: tuple[str, ...] = ("bull", "neutral"),
) -> pd.DataFrame:
    """One signal per divergence that goes on to break structure."""
    if side == "short":
        # Price inversion: a short on X is a long on 1/X with high and low
        # swapped, so the whole long pipeline -- divergence, oversold, falling
        # trendline, money flow -- prices the short side unchanged. This is the
        # technique backend/research/strategy.py already uses. WaveTrend is
        # odd-symmetric in price (ci negates when hlc3 negates, d is unchanged),
        # so a bull divergence on the inverted series IS a bear divergence on
        # the original. Funding is NOT modelled.
        flip = pd.DataFrame({"open": 1.0 / df["open"], "high": 1.0 / df["low"],
                             "low": 1.0 / df["high"], "close": 1.0 / df["close"],
                             "volume": df["volume"]}, index=df.index)
        out = divergence_breakout(
            flip, side="long", wt2_max=wt2_max, pivot_lookback=pivot_lookback,
            trigger=trigger, wait_bars=wait_bars, min_wait=min_wait,
            mfi_min=mfi_min, require_hold=require_hold, breadth=breadth,
            breadth_min=breadth_min, breadth_max=breadth_max,
            atr_mult=atr_mult, atr_len=atr_len, max_risk_pct=max_risk_pct,
            gate=None, gate_allow=gate_allow)
        if out.empty:
            return out
        out = out.copy()
        out["direction"] = -1
        out["stop"] = 1.0 / out["stop"]          # back to real price space
        if gate is not None:
            keep = [ts for ts in out.index
                    if gate.get(ts, "unknown") in gate_allow]
            out = out.loc[keep]
        return out

    bulls, wt2 = _vmc(df, pivot_lookback)
    if wt2 is None:
        return pd.DataFrame(columns=["direction", "stop"])

    a = _atr_c(df, atr_len)
    mfi = _mfi(df) if mfi_min is not None else None
    highs, lows, closes = (df["high"].to_numpy(), df["low"].to_numpy(),
                           df["close"].to_numpy())
    n = len(df)
    rows = []

    for p, _ts in bulls:
        c = p + pivot_lookback                    # divergence confirmed here
        if c >= n - 1 or float(wt2.iloc[p]) > wt2_max:
            continue
        pivot_low = float(lows[p])
        end = min(n, c + wait_bars + 1)
        if c + min_wait >= end:
            continue

        trig_bar = None
        for i in range(c + min_wait, end):
            # the setup dies if price loses the low that made the divergence
            if require_hold and lows[i] < pivot_low:
                break
            if trigger == "none":
                trig_bar = i
                break
            window_hi = highs[c:i]                # highs strictly before bar i
            if window_hi.size == 0:
                continue
            if trigger == "swing":
                level = float(window_hi.max())
            else:                                  # "slope": a falling line
                k = window_hi.size
                if k < 3:
                    continue
                xs = np.arange(k, dtype=float)
                slope, intercept = np.polyfit(xs, window_hi, 1)
                if slope > 0:                      # only fade a FALLING line
                    level = float(window_hi.max())
                else:
                    level = float(intercept + slope * k)
            if closes[i] > level:
                trig_bar = i
                break

        if trig_bar is None or not np.isfinite(a[trig_bar]):
            continue
        if mfi is not None and not (mfi[trig_bar] >= mfi_min):
            continue
        ts = df.index[trig_bar]
        if breadth is not None and (breadth_min is not None
                                    or breadth_max is not None):
            bv = breadth.get(ts, np.nan)
            if not np.isfinite(bv):
                continue
            if breadth_min is not None and bv < breadth_min:
                continue
            if breadth_max is not None and bv > breadth_max:
                continue
        if gate is not None and gate.get(ts, "unknown") not in gate_allow:
            continue

        # stop under the low that produced the divergence
        stop = min(pivot_low, float(lows[c:trig_bar + 1].min())) - atr_mult * a[trig_bar]
        ref = float(closes[trig_bar])
        if stop <= 0 or ref <= 0 or (ref - stop) / ref > max_risk_pct:
            continue
        rows.append({"ts": ts, "direction": 1, "stop": float(stop)})

    if not rows:
        return pd.DataFrame(columns=["direction", "stop"])
    out = pd.DataFrame(rows).set_index("ts")
    return out[~out.index.duplicated(keep="first")].sort_index()
