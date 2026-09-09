"""Long-term descending trendline breakout — the setup the trader drew by hand.

The chart supplied was TAO/USDT on the daily: a single falling line anchored at
the Nov-2024 peak, resting on every lower high for ten months, with price
pressing into it. The claim attached to it is that these breaks run 50-200%.

That is a DIFFERENT setup from `breakout.divergence_breakout`, which this repo
already proved. There the line is fitted over the handful of bars since a
divergence pivot and the trade is closed at 3R. Here the line spans months, the
trade is meant to run, and no divergence is required at all.

How the line is drawn, without cheating
---------------------------------------
A hand-drawn trendline is chosen with hindsight; a mechanical one must not be.
So at every candidate break bar `i` the line is rebuilt from bars STRICTLY
BEFORE `i`:

    a = the highest high in the previous `lookback` bars   (the anchor)
    s = max over k in (a, i) of (high[k] - high[a]) / (k - a)

`s` is the shallowest slope from the anchor that still keeps every intervening
high at or below the line — exactly the line a trader draws down across the
lower highs, touching at least two of them and cut by none. It is a pure
function of past bars, so acting on it at bar `i` is knowable in real time.

The break is `close[i]` above the line while `close[i-1]` was below it. One
signal per anchor, so a bar that stays above the line does not re-fire.

Everything else is a filter on the QUALITY of that line: how long it has stood
(`min_span`), how far price fell under it (`min_drop_pct`), and how many highs
actually sit on it (`min_touches`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from strategies import atr  # noqa: E402

_ATR: dict = {}


def _atr_c(df: pd.DataFrame, length: int) -> np.ndarray:
    key = (id(df), len(df), length)
    if key not in _ATR:
        _ATR[key] = atr(df, length).to_numpy()
    return _ATR[key]


def weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Daily -> weekly candles, closing Sunday, whole weeks only.

    The last bucket is dropped because a part-formed weekly candle is not a
    closed bar and acting on one would be lookahead.
    """
    w = df.resample("W-SUN", label="right", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last",
         "volume": "sum"}).dropna()
    return w.iloc[:-1] if len(w) else w


def trendline_breakout(
        df: pd.DataFrame, *, side: str = "long",
        # --- how the line is drawn ---
        lookback: int = 260,        # bars the anchor may be found in
        min_span: int = 60,         # bars from anchor to break: "long term"
        min_touches: int = 3,       # highs on the line, anchor included
        touch_tol: float = 0.03,    # "on the line" means within this fraction
        # --- quality of the downtrend being broken ---
        min_drop_pct: float = 0.25,  # price must have fallen this far from peak
        vol_mult: float | None = None,  # break volume vs its 20-bar mean
        # --- risk ---
        stop_lookback: int = 20,
        atr_mult: float = 1.0, atr_len: int = 14,
        max_risk_pct: float = 0.25,
        # One event, one trade. The anchor can slide by a bar or two and redraw
        # a near-identical line, which fired 4 entries on one DOT break. Those
        # are not independent trades; counting them inflates annual R and hides
        # correlation.
        cooldown: int = 20,
        gate: pd.Series | None = None,
        gate_allow: tuple[str, ...] = ("bull", "neutral"),
) -> pd.DataFrame:
    """One signal per descending line that price closes back above."""
    if side == "short":
        # A short on X is a long on 1/X with high and low swapped: the falling
        # line on the inverted series IS the rising line on the original. Same
        # inversion breakout.py uses. Funding is NOT modelled.
        flip = pd.DataFrame({"open": 1.0 / df["open"], "high": 1.0 / df["low"],
                             "low": 1.0 / df["high"], "close": 1.0 / df["close"],
                             "volume": df["volume"]}, index=df.index)
        out = trendline_breakout(
            flip, side="long", lookback=lookback, min_span=min_span,
            min_touches=min_touches, touch_tol=touch_tol,
            min_drop_pct=min_drop_pct, vol_mult=vol_mult,
            stop_lookback=stop_lookback, atr_mult=atr_mult, atr_len=atr_len,
            max_risk_pct=max_risk_pct, cooldown=cooldown,
            gate=None, gate_allow=gate_allow)
        if out.empty:
            return out
        out = out.copy()
        out["direction"] = -1
        for col in ("stop", "line", "bhigh", "bclose"):
            out[col] = 1.0 / out[col]
        if gate is not None:
            out = out.loc[[ts for ts in out.index
                           if gate.get(ts, "unknown") in gate_allow]]
        return out

    n = len(df)
    if n < lookback + 2:
        return pd.DataFrame(columns=["direction", "stop"])

    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    a_arr = _atr_c(df, atr_len)
    volmean = (df["volume"].rolling(20).mean().to_numpy()
               if vol_mult is not None else None)
    vols = df["volume"].to_numpy()

    rows: list[dict] = []
    seen_anchor: set[int] = set()
    last_i = -10 ** 9

    for i in range(lookback + 1, n):
        # cheap pre-filter: a break is an up close, and it must clear the
        # previous bar. Skips ~half the bars before any window work.
        if closes[i] <= closes[i - 1]:
            continue

        if i - last_i < cooldown:
            continue

        lo_w = i - lookback
        a = lo_w + int(np.argmax(highs[lo_w:i]))    # anchor: strictly before i
        if i - a < min_span or a in seen_anchor:
            continue

        # shallowest slope from the anchor that no later high pokes through
        ks = np.arange(a + 1, i)
        if ks.size == 0:
            continue
        slopes = (highs[a + 1:i] - highs[a]) / (ks - a)
        j = int(np.argmax(slopes))
        s = float(slopes[j])
        if s >= 0:                                   # must be a FALLING line
            continue

        level = highs[a] + s * (i - a)
        prev = highs[a] + s * (i - 1 - a)
        if not (closes[i] > level and closes[i - 1] <= prev):
            continue

        # how far price actually fell beneath the line
        trough = float(lows[a:i].min())
        if highs[a] <= 0 or (highs[a] - trough) / highs[a] < min_drop_pct:
            continue

        # how many highs genuinely sit on the line (the anchor is one of them)
        idx = np.arange(a, i)
        line = highs[a] + s * (idx - a)
        touches = int(np.sum(highs[a:i] >= line * (1.0 - touch_tol)))
        if touches < min_touches:
            continue

        if volmean is not None:
            vm = volmean[i]
            if not np.isfinite(vm) or vm <= 0 or vols[i] < vol_mult * vm:
                continue

        ts = df.index[i]
        if gate is not None and gate.get(ts, "unknown") not in gate_allow:
            continue
        if not np.isfinite(a_arr[i]):
            continue

        swing_low = float(lows[max(0, i - stop_lookback + 1):i + 1].min())
        stop = swing_low - atr_mult * a_arr[i]
        ref = float(closes[i])
        if stop <= 0 or ref <= 0 or (ref - stop) / ref > max_risk_pct:
            continue

        seen_anchor.add(a)
        last_i = i
        # `line` and `bhigh` are what a lower-timeframe entry needs: the level
        # that was broken (a retest aims at it) and the break bar's high (a
        # confirmation entry waits for it). Carried as extra columns, which
        # harness.simulate ignores -- it reads only direction and stop.
        rows.append({"ts": ts, "direction": 1, "stop": float(stop),
                     "line": float(level), "bhigh": float(highs[i]),
                     "bclose": ref})

    if not rows:
        return pd.DataFrame(columns=["direction", "stop", "line", "bhigh",
                                     "bclose"])
    out = pd.DataFrame(rows).set_index("ts")
    return out[~out.index.duplicated(keep="first")].sort_index()
