"""Candidate rules for the pieces of Signals & Overlays, to be tuned against the reference."""
from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True)
def trail_close(c, w):
    """Trailing stop on closes (our Smart Trail): flips when the close crosses it."""
    n = len(c)
    out = np.full(n, np.nan)
    dr = np.ones(n, np.int8)
    tr = np.nan
    d = 1
    for t in range(n):
        if not np.isnan(w[t]):
            if np.isnan(tr):
                tr = c[t] - w[t]
            elif d == 1:
                if c[t] < tr:
                    d = -1
                    tr = c[t] + w[t]
                else:
                    tr = max(tr, c[t] - w[t])
            else:
                if c[t] > tr:
                    d = 1
                    tr = c[t] - w[t]
                else:
                    tr = min(tr, c[t] + w[t])
        out[t] = tr
        dr[t] = d
    return out, dr


@njit(cache=True)
def trail_hl(h, l, c, w):
    """Trailing stop on lows (up) and highs (down), flipped by a close beyond it."""
    n = len(c)
    out = np.full(n, np.nan)
    dr = np.ones(n, np.int8)
    tr = np.nan
    d = 1
    for t in range(n):
        if not np.isnan(w[t]):
            if np.isnan(tr):
                tr = l[t] - w[t]
            elif d == 1:
                if c[t] < tr:
                    d = -1
                    tr = h[t] + w[t]
                else:
                    tr = max(tr, l[t] - w[t])
            else:
                if c[t] > tr:
                    d = 1
                    tr = l[t] - w[t]
                else:
                    tr = min(tr, h[t] + w[t])
        out[t] = tr
        dr[t] = d
    return out, dr


@njit(cache=True)
def supertrend(h, l, c, w):
    """The classic SuperTrend: bands on hl2 +/- w that only ratchet inwards, flipped by a close."""
    n = len(c)
    out = np.full(n, np.nan)
    dr = np.ones(n, np.int8)
    pu = np.nan
    pl = np.nan
    d = 1
    for t in range(1, n):
        if not np.isnan(w[t]):
            mid = (h[t] + l[t]) / 2
            u = mid + w[t]
            lo = mid - w[t]
            pc = c[t - 1]
            nu = u if (np.isnan(pu) or u < pu or pc > pu) else pu
            nl = lo if (np.isnan(pl) or lo > pl or pc < pl) else pl
            if d == 1:
                d = -1 if c[t] < nl else 1
            else:
                d = 1 if c[t] > nu else -1
            pu = nu
            pl = nl
            out[t] = nl if d == 1 else nu
        dr[t] = d
    return out, dr
