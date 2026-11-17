"""Grid searches of our Signals & Overlays rules against a reference (see so_compare)."""
from __future__ import annotations

import numpy as np

from . import so_compare as sc
from . import so_variants as V

so = sc.so


def signal_grid(book, ref, ns=(5, 7, 10, 14, 20, 30), mults=np.arange(0.5, 6.01, 0.25)):
    rows = []
    h, l, c = book.h, book.l, book.c
    for n in ns:
        atr = so.smc._atr(h, l, c, n)
        d = so._conf(h, l, c, atr, np.asarray(mults) / 0.25, 0.25)
        for j, m in enumerate(mults):
            s = sc.score_signals(ref, so._conf_sig(d[j], c, book.base))
            f1 = 2 * s["recall"] * s["precision"] / max(s["recall"] + s["precision"], 1e-9)
            rows.append({"f1": f1, "atr": n, "mult": float(m), **s})
    return sorted(rows, key=lambda r: -r["f1"])


def trail_grid(book, ref, ns=(7, 10, 14, 20, 30, 50, 100), ks=np.arange(1.0, 9.01, 0.25), which="trail"):
    rows = []
    h, l, c = book.h, book.l, book.c
    for n in ns:
        atr = so.smc._atr(h, l, c, n)
        for k in ks:
            w = k * atr
            for name, (tr, dr) in (("close", V.trail_close(c, w)), ("hl", V.trail_hl(h, l, c, w)),
                                   ("supertrend", V.supertrend(h, l, c, w))):
                s = sc.score_trail(ref, tr, dr, book.atr14, which=which)
                rows.append({"score": s["dir"] - 0.15 * s["mae_atr"], "variant": name, "atr": n, "k": float(k), **s})
    return sorted(rows, key=lambda r: -r["score"])


def exits_from_signals(book, ref, rsi_len: int, upper: float, lower: float, tol_profit: bool = True, once: bool = False):
    """X marks predicted by 'RSI crosses back through a level while in profit', starting from the reference's own
    signals (so the rule is tested on its own, not through our signal mismatch).

    After a buy, a blue X at the first bar where RSI falls back under ``upper`` (in profit); after a sell, an orange
    X where RSI rises back over ``lower``. Several per signal unless ``once``. Returns {bar: +1 blue / -1 orange}.
    """
    c = book.c
    r = so.rsi(c, rsi_len)
    prev = np.concatenate(([np.nan], r[:-1]))
    cross_dn = (r < upper) & (prev >= upper)
    cross_up = (r > lower) & (prev <= lower)
    sigs = sorted(ref.signals.items())
    out = {}
    for k, (i, (side, _)) in enumerate(sigs):
        end = sigs[k + 1][0] if k + 1 < len(sigs) else len(c) - 1
        for t in range(i + 1, min(end, len(c) - 1) + 1):
            if side > 0 and cross_dn[t] and (c[t] > c[i] or not tol_profit):
                out[t] = 1
                if once:
                    break
            elif side < 0 and cross_up[t] and (c[t] < c[i] or not tol_profit):
                out[t] = -1
                if once:
                    break
    return out


def x_grid(book, ref, lens=(5, 7, 9, 14, 21), uppers=(60, 65, 70, 75, 80, 85)):
    rows = []
    for n in lens:
        for up in uppers:
            for once in (False, True):
                m = exits_from_signals(book, ref, n, up, 100 - up, once=once)
                s = sc.score_x(ref, m, tol=1)
                f1 = 2 * s["recall"] * s["precision"] / max(s["recall"] + s["precision"], 1e-9)
                rows.append({"f1": f1, "rsi": n, "upper": up, "once": once, **s})
    return sorted(rows, key=lambda r: -r["f1"])
