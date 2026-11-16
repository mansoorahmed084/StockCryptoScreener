"""Score our structure breaks against events read off LuxAlgo's Price Action Concepts."""
from __future__ import annotations

import pickle

import numpy as np
import pandas as pd

from backend.screener import price_action as pa


def ours(candles: pd.DataFrame, k: int, scope: str = "internal"):
    o, h, l, c = (candles[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
    v = candles["volume"].to_numpy(dtype=float) * c
    breaks, _, _ = pa.structure(o, h, l, c, v, k, scope)
    return breaks


def score(ref, mine, tol: int = 1, covered: tuple[int, int] | None = None) -> dict:
    """Recall of the reference events by ours, with type and pivot agreement among the matches."""
    used, matched, kind_ok, pivot_ok = set(), 0, 0, 0
    for e in ref:
        best = None
        for j, b in enumerate(mine):
            if j in used or b.side != e.side or abs(b.i - e.break_bar) > tol:
                continue
            if best is None or abs(b.i - e.break_bar) < abs(mine[best].i - e.break_bar):
                best = j
        if best is None:
            continue
        used.add(best)
        matched += 1
        b = mine[best]
        kind_ok += (b.kind == e.kind) or (b.kind == "CHoCH" and e.kind == "CHoCH+")
        pivot_ok += abs(b.level_i - e.pivot_bar) <= tol
    lo, hi = covered if covered else (min(e.break_bar for e in ref), max(e.break_bar for e in ref))
    in_range = [b for b in mine if lo <= b.i <= hi]
    return {"ref": len(ref), "matched": matched, "recall": matched / len(ref),
            "kind": kind_ok / max(matched, 1), "pivot": pivot_ok / max(matched, 1),
            "ours_in_range": len(in_range), "extra": len(in_range) - matched}


if __name__ == "__main__":
    candles = pd.read_csv("calibration/data/pac_btcusdt_15m.csv")
    ref = pickle.load(open("calibration/data/pac/events_internal.pkl", "rb"))
    print(f"{len(ref)} reference events, bars {min(e.break_bar for e in ref)}..{max(e.break_bar for e in ref)}")
    print(" k   ours  recall  type  pivot  extra")
    for k in range(2, 11):
        s = score(ref, ours(candles, k))
        print(f"{k:2d}  {s['ours_in_range']:5d}  {s['recall']:5.0%}  {s['kind']:5.0%}  {s['pivot']:5.0%}  {s['extra']:5d}")


# ---------------------------------------------------------------- candidate engines
def structure_legs(o, h, l, c, size: int, strict_cross: bool = True):
    """Structure breaks the way LuxAlgo's open-source Smart Money Concepts finds them.

    A bar is a swing high when it is higher than every later bar up to now (``size`` bars on); the first
    such bar after a swing low sets the leg to bearish and registers the swing high, and the mirror for lows.
    So swing highs and lows alternate. A close crossing the latest unbroken swing breaks structure once;
    it is a CHoCH if the trend was the other way, otherwise a BOS.
    """
    from backend.screener.price_action import Break
    n = len(c)
    leg = 0                                   # 0 bearish leg, 1 bullish leg
    hi_lvl = hi_bar = lo_lvl = lo_bar = None
    hi_crossed = lo_crossed = True
    bias = 0
    out = []
    for t in range(size, n):
        win_h = h[t - size + 1:t + 1].max()
        win_l = l[t - size + 1:t + 1].min()
        new_leg = leg
        if h[t - size] > win_h:
            new_leg = 0
        elif l[t - size] < win_l:
            new_leg = 1
        if new_leg != leg:
            if new_leg == 1:                  # a bullish leg starts: the swing low at t - size
                lo_lvl, lo_bar, lo_crossed = float(l[t - size]), t - size, False
            else:
                hi_lvl, hi_bar, hi_crossed = float(h[t - size]), t - size, False
            leg = new_leg
        up = c[t] > hi_lvl and (c[t - 1] <= hi_lvl if strict_cross else True) if hi_lvl is not None else False
        dn = c[t] < lo_lvl and (c[t - 1] >= lo_lvl if strict_cross else True) if lo_lvl is not None else False
        if up and not hi_crossed:
            out.append(Break(t, 1, "BOS" if bias == 1 else "CHoCH", hi_lvl, hi_bar, hi_bar, False, "internal"))
            hi_crossed, bias = True, 1
        elif dn and not lo_crossed:
            out.append(Break(t, -1, "BOS" if bias == -1 else "CHoCH", lo_lvl, lo_bar, lo_bar, False, "internal"))
            lo_crossed, bias = True, -1
    return out


def ours_legs(candles: pd.DataFrame, size: int, strict_cross: bool = True):
    o, h, l, c = (candles[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
    return structure_legs(o, h, l, c, size, strict_cross)
