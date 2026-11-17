"""Backtest green (buy) / red (sell) signals on one price series.

Rules, the same for every signal source so the comparison is fair:
  * a signal on bar i is acted on at the OPEN of bar i + 1 (LuxAlgo confirms signals at the next candle's open)
  * green opens a long, red opens a short; an opposite signal closes the position and reverses it
    (``long_only``: red just closes the long)
  * ``strong_only`` ignores the normal signals, keeping only the ones marked "+"
  * the whole equity is in the trade, no leverage; a fee on every entry and exit (``fee`` per side)
  * equity is marked to market at each close, so the drawdown includes the open trade
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Result:
    trades: pd.DataFrame
    equity: np.ndarray            # one value per bar in the tested range
    stats: dict


def backtest(o: np.ndarray, c: np.ndarray, sig: np.ndarray, start: int, end: int, *, long_only: bool = False,
             strong_only: bool = False, fee: float = 0.0006) -> Result:
    """``sig``: +-1 normal, +-2 strong per bar. Trades only on bars ``start``..``end`` inclusive."""
    pos = 0
    entry_px = 0.0
    entry_i = -1
    eq = 1.0                       # equity while flat
    eq_before = 1.0                # equity just before the open trade was entered
    eq_net = 1.0                   # equity just after the entry fee
    curve: list[float] = []
    trades: list[dict] = []

    def close_trade(i: int, px: float):
        nonlocal eq, pos
        eq = eq_net * (1.0 + pos * (px / entry_px - 1.0)) * (1.0 - fee)
        trades.append({"entry_bar": entry_i, "exit_bar": i, "side": pos, "entry": entry_px, "exit": px,
                       "ret": eq / eq_before - 1.0, "bars": i - entry_i})
        pos = 0

    for i in range(start, end + 1):
        s = sig[i - 1] if i - 1 >= start else 0          # the previous bar's signal, acted on at this open
        if s != 0 and not (strong_only and abs(s) != 2):
            want = 1 if s > 0 else -1
            if want != pos:
                if pos != 0:
                    close_trade(i, o[i])
                if not (long_only and want < 0):
                    pos, entry_px, entry_i = want, o[i], i
                    eq_before = eq
                    eq_net = eq * (1.0 - fee)
        curve.append(eq_net * (1.0 + pos * (c[i] / entry_px - 1.0)) if pos != 0 else eq)
    if pos != 0:                                         # still open: close it at the last close
        close_trade(end, c[end])
        curve[-1] = eq
    tr = pd.DataFrame(trades)
    curve_a = np.array(curve)
    return Result(tr, curve_a, stats(tr, curve_a, o, c, start, end, pos_open=False))


def stats(tr: pd.DataFrame, curve: np.ndarray, o, c, start: int, end: int, pos_open: bool) -> dict:
    n = len(curve)
    out = {"trades": int(len(tr)), "total_return": float(curve[-1] - 1.0),
           "buy_hold": float(c[end] / o[start] - 1.0)}
    peak = np.maximum.accumulate(curve)
    out["max_drawdown"] = float((curve / peak - 1.0).min())
    if len(tr):
        w = tr[tr["ret"] > 0]
        l = tr[tr["ret"] <= 0]
        out["win_rate"] = float(len(w) / len(tr))
        out["avg_trade"] = float(tr["ret"].mean())
        out["avg_win"] = float(w["ret"].mean()) if len(w) else 0.0
        out["avg_loss"] = float(l["ret"].mean()) if len(l) else 0.0
        gl = -l["ret"].sum()
        out["profit_factor"] = float(w["ret"].sum() / gl) if gl > 0 else float("inf")
        out["best"] = float(tr["ret"].max())
        out["worst"] = float(tr["ret"].min())
        out["avg_bars"] = float(tr["bars"].mean())
        out["longs"] = int((tr["side"] > 0).sum())
        out["shorts"] = int((tr["side"] < 0).sum())
        out["long_return"] = float((1 + tr[tr["side"] > 0]["ret"]).prod() - 1) if (tr["side"] > 0).any() else 0.0
        out["short_return"] = float((1 + tr[tr["side"] < 0]["ret"]).prod() - 1) if (tr["side"] < 0).any() else 0.0
    dr = np.diff(curve) / curve[:-1] if n > 1 else np.array([0.0])
    out["bar_vol"] = float(dr.std())
    out["bars"] = n
    return out
