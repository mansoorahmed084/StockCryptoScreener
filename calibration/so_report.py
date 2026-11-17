"""Backtest LuxAlgo's signals (as read off Vela) against ours on the same BTC bars."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import so_compare as sc
from .so_backtest import backtest

so = sc.so


def ref_signals(ref, n: int) -> np.ndarray:
    sig = np.zeros(n)
    for i, (side, kind) in ref.signals.items():
        sig[i] = side * (2 if kind == "strong" else 1)
    return sig


def our_signals(book, atr_len: int | None = None, mult: float | None = None) -> np.ndarray:
    if atr_len is None:
        return book.conf_sig(12)                        # our default (sensitivity 12 = a 3 ATR band)
    atr = so.smc._atr(book.h, book.l, book.c, atr_len)
    d = so._conf(book.h, book.l, book.c, atr, np.array([mult / 0.25]), 0.25)[0]
    return so._conf_sig(d, book.c, book.base)


def run(tf: str, atr_tuned: int):
    c = pd.read_csv(f"calibration/data/so/btcusdt_{tf}.csv")
    df = sc.frame(c)
    ref = sc.load_reference(f"calibration/data/so/ref_{tf}.pkl")
    b = so.Book(df)
    idx = np.where(ref.covered)[0]
    start, end = int(idx[0]), int(idx[-1])
    o, cl = df["open"].to_numpy(), df["close"].to_numpy()
    sources = {"LuxAlgo (read off Vela)": ref_signals(ref, len(df)),
               "Ours, default (sens 12)": our_signals(b),
               f"Ours, tuned (ATR {atr_tuned}, 1.75x)": our_signals(b, atr_tuned, 1.75)}
    variants = {"both sides": dict(), "long only": dict(long_only=True),
                "both, strong (+) only": dict(strong_only=True), "long, strong (+) only": dict(long_only=True, strong_only=True)}
    rows, curves = [], {}
    for sname, sig in sources.items():
        n_sig = int(sum(1 for i in range(start, end + 1) if sig[i] != 0))
        for vname, kw in variants.items():
            r = backtest(o, cl, sig, start, end, **kw)
            rows.append({"source": sname, "variant": vname, "signals": n_sig, **r.stats})
            curves[(sname, vname)] = r.equity
    t = lambda i: pd.Timestamp(c["time"][i], unit="s", tz="UTC")
    return pd.DataFrame(rows), curves, (t(start), t(end), end - start + 1), df.index[start:end + 1]


def run_range(tf: str, ref_file: str, atr_tuned: int, start_date: str, end_date: str | None = None):
    """Like ``run`` but over an explicit date range inside what the reference covers."""
    c = pd.read_csv(f"calibration/data/so/btcusdt_{tf}.csv")
    df = sc.frame(c)
    ref = sc.load_reference(ref_file)
    b = so.Book(df)
    idx = np.where(ref.covered)[0]
    start = max(int(idx[0]), int(df.index.searchsorted(pd.Timestamp(start_date, tz="UTC"))))
    end = int(idx[-1]) if end_date is None else min(int(idx[-1]), int(df.index.searchsorted(pd.Timestamp(end_date, tz="UTC"))))
    o, cl = df["open"].to_numpy(), df["close"].to_numpy()
    sources = {"LuxAlgo (read off Vela)": ref_signals(ref, len(df)),
               "Ours, default (sens 12)": our_signals(b),
               f"Ours, tuned (ATR {atr_tuned}, 1.75x)": our_signals(b, atr_tuned, 1.75)}
    variants = {"both sides": dict(), "long only": dict(long_only=True),
                "both, strong (+) only": dict(strong_only=True), "long, strong (+) only": dict(long_only=True, strong_only=True)}
    rows, curves = [], {}
    for sname, sig in sources.items():
        n_sig = int(sum(1 for i in range(start, end + 1) if sig[i] != 0))
        for vname, kw in variants.items():
            r = backtest(o, cl, sig, start, end, **kw)
            rows.append({"source": sname, "variant": vname, "signals": n_sig, **r.stats})
            curves[(sname, vname)] = r.equity
    return pd.DataFrame(rows), curves, df.index[start:end + 1], (df, ref, b, sources, start, end)
