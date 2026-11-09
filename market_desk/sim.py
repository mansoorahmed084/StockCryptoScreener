"""How one planned trade plays out on daily candles.

The backtest and the paper trader both use these two functions, so a paper
trade follows exactly the rules that were tested.

Fill: a buy stop at ``entry`` fills on the first candle whose high reaches
it, at the entry or at the open if the candle opened above it. A candle that
opens at or above the target is a miss (price ran away; we do not chase).

Exit: the stop is checked before the target, so a candle that touches both
counts as a loss. A gap through the stop fills at the open. After
``max_hold`` closed candles the trade closes at the close. A candle that is
still forming can hit the stop or target but never the time exit.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Fill:
    idx: int
    price: float


@dataclass(frozen=True)
class Exit:
    idx: int
    price: float
    why: str          # stop | target | time


def find_fill(o: np.ndarray, h: np.ndarray, start: int, entry: float, target: float,
              order_bars: int, slip: float, n_complete: int | None = None
              ) -> tuple[str, Fill | None]:
    """('filled', Fill) | ('expired', None) | ('missed', idx) | ('pending', None)."""
    n = len(o)
    n_complete = n if n_complete is None else n_complete
    for k in range(start, min(start + order_bars, n)):
        if o[k] >= target:
            return "missed", Fill(k, float(o[k]))
        if h[k] >= entry:
            return "filled", Fill(k, float(max(o[k], entry) * (1 + slip)))
    if start + order_bars <= n_complete:
        return "expired", None
    return "pending", None


def manage(o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray, fill_idx: int,
           stop: float, target: float, max_hold: int, slip: float,
           n_complete: int | None = None) -> Exit | None:
    """The exit of a trade filled on candle ``fill_idx``, or None (still open)."""
    n = len(o)
    n_complete = n if n_complete is None else n_complete
    for j in range(fill_idx, n):
        if lo[j] <= stop:
            px = stop if j == fill_idx else min(o[j], stop)
            return Exit(j, float(px * (1 - slip)), "stop")
        if h[j] >= target:
            px = target if j == fill_idx else max(o[j], target)
            return Exit(j, float(px), "target")
        if j - fill_idx + 1 >= max_hold and j < n_complete:
            return Exit(j, float(c[j] * (1 - slip)), "time")
    return None


def r_multiple(fill: float, stop: float, exit_px: float, fee: float) -> float:
    """Profit in R after fees on both sides. 1R = fill - stop."""
    risk = fill - stop
    if risk <= 0:
        return 0.0
    return (exit_px - fill - fee * (fill + exit_px)) / risk
