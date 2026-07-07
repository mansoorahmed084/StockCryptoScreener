"""Signal validation / backtest harness (plan sec 4.11).

Replays the RS classifier over history and measures the ratio's forward return
after each time a signal fired. Lightweight (vectorised) — meant for sanity
checking presets and recalibrating the sec 4.7 thresholds, not full trade sim.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.config import ClassifierParams
from backend.screener import rs


@dataclass
class BacktestStats:
    direction: str
    horizon: int
    n: int
    hit_rate: float          # fraction of entries that moved the "right" way
    mean_fwd: float          # mean forward return (%)
    median_fwd: float

    def as_dict(self) -> dict:
        return {
            "direction": self.direction, "horizon": self.horizon, "n": self.n,
            "hit_rate": self.hit_rate, "mean_fwd": self.mean_fwd,
            "median_fwd": self.median_fwd,
        }


def backtest_signal(close: pd.Series, params: ClassifierParams, *,
                    direction: str = rs.BULL, horizon: int = 10,
                    fresh_only: bool = True) -> BacktestStats:
    """Forward-return stats for a single (ratio, timeframe, direction) signal.

    ``fresh_only`` counts only the candle a signal *flips* on (state changes),
    avoiding overlapping/duplicated entries while a trend persists.
    """
    hist = rs.classify_history(close, params)
    if hist.empty:
        return BacktestStats(direction, horizon, 0, float("nan"),
                             float("nan"), float("nan"))
    c = close.dropna().astype(float).loc[hist.index]
    dirs = hist["direction"]
    active = dirs == direction
    entries = active & (dirs.shift(1) != direction) if fresh_only else active

    fwd = (c.shift(-horizon) / c - 1.0) * 100
    sample = fwd[entries.to_numpy()].dropna()
    if sample.empty:
        return BacktestStats(direction, horizon, 0, float("nan"),
                             float("nan"), float("nan"))

    win = sample > 0 if direction == rs.BULL else sample < 0
    return BacktestStats(
        direction=direction, horizon=horizon, n=int(len(sample)),
        hit_rate=float(win.mean()), mean_fwd=float(sample.mean()),
        median_fwd=float(sample.median()),
    )
