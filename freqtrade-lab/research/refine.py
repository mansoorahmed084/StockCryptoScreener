"""Time the trendline entry on 1h candles instead of taking the next daily open.

Why this should help, mechanically. The daily entry pays the next daily open and
stops out under a 20-day low minus 1.5 ATR, which sits 15-25% away. Everything
the account earns is measured in R, and R is the size of that stop. Cut the
distance to the stop and the SAME price move is worth more R.

The catch is symmetric: a tighter stop is hit more often, and the cost of a
round trip stops being 1.5% of R and starts being 5%. So this is a genuine
trade-off, not a free improvement, and the grid has to settle it.

Four ways to time the entry, all of them functions of closed 1h bars:

    next_open     the daily open, unchanged. THE CONTROL -- it is in the grid so
                  every refinement is measured against it in the same engine.
    ltf_break     wait for a 1h close above the daily break bar's high.
                  Demands follow-through; skips the breaks that die on day one.
    retest        wait for price to come back to the broken line, then enter on
                  the first 1h close above the previous 1h high. Buys the
                  pullback, so the stop can sit just under it.
    pullback_ema  wait for a 1h close below EMA(n), then one back above it.

Four ways to place the stop:

    daily         the daily stop, unchanged (the control)
    ltf_swing     the lowest 1h low of the last `swing_hours`, minus ATR(1h)
    line          the broken trendline, now read as support, minus ATR(1h)
    tighter       whichever of daily and ltf_swing is nearer to price

Timing rules, so nothing here is hindsight. A daily bar stamped D covers
D 00:00 to D+1 00:00, so its close is known at D+1 00:00 and the first tradable
hour is the one starting then. `next_open` therefore emits on the 1h bar that
closes at that same instant, which makes its fill the daily open exactly. Every
other mode scans forward from there and emits on the bar whose CLOSE confirms
the trigger; `harness.simulate` then enters at the following 1h open.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from strategies import atr  # noqa: E402

DAY = pd.Timedelta("1D")
HOUR = pd.Timedelta("1h")

ENTRY_MODES = ("next_open", "ltf_break", "retest", "pullback_ema")
STOP_MODES = ("daily", "ltf_swing", "line", "tighter")

_ATR: dict = {}
_EMA: dict = {}


def _atr_c(df: pd.DataFrame, length: int) -> np.ndarray:
    key = (id(df), len(df), length)
    if key not in _ATR:
        _ATR[key] = atr(df, length).to_numpy()
    return _ATR[key]


def _ema_c(df: pd.DataFrame, length: int) -> np.ndarray:
    key = (id(df), len(df), length)
    if key not in _EMA:
        _EMA[key] = df["close"].ewm(span=length, adjust=False).mean().to_numpy()
    return _EMA[key]


def refined_signals(
        daily_sig: pd.DataFrame, hourly: pd.DataFrame, *,
        entry_mode: str = "next_open",
        wait_hours: int = 72,
        stop_mode: str = "ltf_swing",
        swing_hours: int = 24,
        atr_mult: float = 1.0, atr_len: int = 14,
        retest_tol: float = 0.02,
        ema_len: int = 20,
        min_risk_pct: float = 0.02,
        max_risk_pct: float = 0.25,
) -> pd.DataFrame:
    """Turn daily trendline signals into 1h-timed signals with 1h-placed stops.

    `daily_sig` must carry the columns trendline_breakout emits: stop, line,
    bhigh. The result is indexed on 1h bars and is fed to harness.simulate with
    base = the 1h frame, so entry lands on the next 1h open.
    """
    cols = ["direction", "stop"]
    if daily_sig.empty or hourly.empty:
        return pd.DataFrame(columns=cols)

    hi = hourly["high"].to_numpy()
    lo = hourly["low"].to_numpy()
    cl = hourly["close"].to_numpy()
    a1 = _atr_c(hourly, atr_len)
    ema = _ema_c(hourly, ema_len) if entry_mode == "pullback_ema" else None
    idx = hourly.index
    n = len(idx)
    rows = []

    for ts, sig in daily_sig.iterrows():
        act_from = ts + DAY                 # the daily bar's close, to the hour
        # Anchor on the bar that CLOSES at act_from, not the one that opens
        # there. That bar is the last one whose content is known when the daily
        # candle closes, so anchoring here keeps every array read at or before
        # the decision bar -- which is what makes the truncation replay pass.
        t0 = idx.searchsorted(act_from - HOUR, side="left")
        if t0 >= n or idx[t0] != act_from - HOUR:
            continue                        # 1h data does not cover this signal
        i0 = t0 + 1

        d_stop = float(sig["stop"])
        line = float(sig["line"])
        bhigh = float(sig["bhigh"])

        # ---- find the bar whose CLOSE triggers the entry ----
        if entry_mode == "next_open":
            t = t0                          # closes exactly when the day closes
        else:
            end = min(n, i0 + wait_hours)
            t = None
            armed = False                   # phase 1 of the two-phase modes
            for j in range(i0, end):
                if lo[j] < d_stop:
                    break                   # the setup failed before it started
                if entry_mode == "ltf_break":
                    if cl[j] > bhigh:
                        t = j
                        break
                elif entry_mode == "retest":
                    if not armed:
                        if lo[j] <= line * (1.0 + retest_tol):
                            armed = True    # price came back to the line
                    elif cl[j] > hi[j - 1]:
                        t = j               # and turned back up
                        break
                else:                       # pullback_ema
                    if not armed:
                        if cl[j] < ema[j]:
                            armed = True
                    elif cl[j] > ema[j]:
                        t = j
                        break
            if t is None:
                continue                    # the trigger never came: no trade

        if not np.isfinite(a1[t]):
            continue

        # ---- place the stop ----
        swing = float(lo[max(0, t - swing_hours + 1):t + 1].min())
        cand = {"daily": d_stop,
                "ltf_swing": swing - atr_mult * a1[t],
                "line": line - atr_mult * a1[t]}
        cand["tighter"] = max(d_stop, cand["ltf_swing"])
        stop = cand[stop_mode]

        # Size the risk check off THIS bar's close. An earlier version used the
        # next bar's open -- the price the fill actually lands on -- which is
        # not known when the decision is made. The difference is small but it is
        # the future, and a truncation replay caught it. harness.simulate drops
        # any signal whose next bar does not exist, so nothing needs to look
        # ahead to confirm the entry bar is there either.
        ref = float(cl[t])
        if stop <= 0 or ref <= 0:
            continue
        risk = (ref - stop) / ref
        # A stop closer than min_risk_pct is noise: it is inside the bar-to-bar
        # chop, and a 0.3% round trip would be a tenth of R.
        if not (min_risk_pct <= risk <= max_risk_pct):
            continue
        rows.append({"ts": idx[t], "direction": 1, "stop": float(stop)})

    if not rows:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows).set_index("ts")
    return out[~out.index.duplicated(keep="first")].sort_index()
