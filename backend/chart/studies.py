"""Server-side studies for the chart workspace.

* VuManChu Cipher B on the candles the chart has loaded — the same code the
  screener uses (backend/indicators/vumanchu.py), so the numbers match.
* Auto analysis: the trendlines, levels, Fibonacci, patterns, swing labels
  and daily order blocks the Chart Patterns page finds
  (backend/screener/patterns.py), as JSON shapes with times instead of bar
  indexes, for the chart to draw read-only.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from backend.indicators.vumanchu import VuManChuCipherB
from backend.screener import patterns as pt


def frame(bars: list[dict]) -> pd.DataFrame:
    """Chart bars ({time, open, high, low, close, volume}) as an OHLCV frame."""
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(bars)
    df.index = pd.to_datetime(df.pop("time"), unit="s", utc=True)
    df.index.name = "ts"
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def _num(v) -> float | None:
    v = float(v)
    return v if math.isfinite(v) else None


def _series(s: pd.Series) -> list[dict]:
    return [{"time": int(ts.timestamp()), "value": float(v)}
            for ts, v in s.items() if v is not None and np.isfinite(v)]


def vumanchu(bars: list[dict], **params) -> dict:
    """WT1, WT2, money flow and signal markers. The forming (last) candle gets
    lines but no markers: its signals can still change."""
    df = frame(bars)
    res = VuManChuCipherB(**params).compute(df)
    last = df.index[-1] if len(df) else None
    return {
        "wt1": _series(res.panes.get("wt1", pd.Series(dtype=float))),
        "wt2": _series(res.panes.get("wt2", pd.Series(dtype=float))),
        "mfi": _series(res.panes.get("mfi", pd.Series(dtype=float))),
        "markers": [{"time": int(m.ts.timestamp()), "kind": m.kind, "price": m.price,
                     "label": m.label} for m in res.markers if m.ts != last],
    }


def analysis(df: pd.DataFrame, daily: pd.DataFrame | None = None) -> dict:
    """Shapes for the auto-analysis layer. Line points are (time, price);
    lines are meant to be extended to the right."""
    n = len(df)
    if n < 30:
        return {"lines": [], "levels": [], "fib": None, "patterns": [], "swings": [],
                "order_blocks": []}
    a = pt.analyse(df)
    times = [int(t.timestamp()) for t in df.index]
    step = int(np.median(np.diff(times))) if n > 1 else 60

    def t_of(i: float) -> int:
        i = int(round(i))
        return times[i] if 0 <= i < n else times[-1] + (i - (n - 1)) * step

    def line(ln: pt.Line, rank: int) -> dict:
        return {"kind": ln.kind, "t0": t_of(ln.i0), "p0": ln.p0, "t1": t_of(ln.i1),
                "p1": ln.p1, "touches": ln.touches, "broken": ln.broken, "rank": rank,
                "now": _num(ln.at(n - 1))}

    out = {
        "lines": [line(ln, k) for lines in (a.supports, a.resistances)
                  for k, ln in enumerate(lines[:2])],
        "levels": [{"kind": lv.kind, "price": lv.price, "touches": lv.touches,
                    "t0": t_of(lv.first)} for lv in a.levels],
        "fib": None,
        "patterns": [],
        "swings": [{"time": t_of(i), "price": p, "label": lab}
                   for i, p, lab in pt.price_action(df, a.pivot).labels],
        "order_blocks": [],
    }
    if a.fib:
        f = a.fib
        out["fib"] = {"direction": f.direction, "t0": t_of(f.start_i), "p0": f.start,
                      "t1": t_of(f.end_i), "p1": f.end,
                      "levels": [{"ratio": r, "price": v} for r, v in f.levels.items()]}
    for p in a.patterns:
        item = {"name": p.name, "bias": p.bias, "status": p.status, "note": p.note,
                "start": t_of(p.start),
                "target_up": _num(p.target_up), "target_down": _num(p.target_down),
                "breakout_up": _num(p.breakout_up), "breakout_down": _num(p.breakout_down),
                "points": [{"time": t_of(i), "price": v} for i, v in p.points]}
        for side in ("upper", "lower"):
            ln = getattr(p, side)
            item[side] = None if ln is None else {
                "t0": t_of(p.start), "p0": ln.at(p.start), "t1": t_of(n - 1), "p1": ln.at(n - 1)}
        out["patterns"].append(item)
    if daily is not None and len(daily) > 20:
        for ob in pt.order_blocks(daily):
            out["order_blocks"].append({
                "kind": ob.kind, "bottom": ob.bottom, "top": ob.top,
                "time": int(ob.ts.timestamp()), "broken": ob.broken, "tests": ob.tests,
                "label": ob.label})
    return out
