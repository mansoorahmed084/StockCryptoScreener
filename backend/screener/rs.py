"""Relative-strength engine — noise-filtered bull/bear/neutral classification.

Implements the design in IMPLEMENTATION_PLAN.md sec 4.7:

  1. closed candles only (drop the still-forming last candle)
  2. deadband / neutral zone -> three states, not two
  3. volatility-normalised score (z-scores, so one band works across TFs/coins)
  4. smoothing (EMA position + slope)
  5. persistence (k consecutive candles before a flip)
  6. hysteresis (sticky exit threshold)

The public entry point is :func:`classify`, a pure function of a ratio close
series + timeframe params, so it is fully unit-testable with synthetic data.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.config import ClassifierParams

BULL, BEAR, NEUTRAL, UNKNOWN = "bull", "bear", "neutral", "unknown"


@dataclass
class RSResult:
    direction: str = UNKNOWN
    strength: float = float("nan")     # blended z-score, ~[-3, 3]
    change_pct: float = float("nan")   # last closed candle % change of the ratio
    n: int = 0
    parts: dict[str, float] = field(default_factory=dict)
    rank: float | None = None          # percentile vs peers, filled by the matrix
    reason: str = ""

    @property
    def is_known(self) -> bool:
        return self.direction != UNKNOWN


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def strength_series(close: pd.Series, params: ClassifierParams) -> pd.DataFrame:
    """Return a frame with the blended strength score and its components."""
    close = close.astype(float)
    returns = close.pct_change()

    # Return volatility (one sigma of a single candle) — the common yardstick that
    # lets one neutral band work across timeframes and coins.
    min_p = max(5, params.vol_lookback // 3)
    ret_std = returns.rolling(params.vol_lookback, min_periods=min_p).std(ddof=0)
    ret_std = ret_std.replace(0, np.nan)

    # (3) volatility-normalised momentum: latest return in units of its own sigma
    z_return = (returns / ret_std).clip(-3, 3)

    # (4) EMA position: distance from trend, measured in candle-sigmas. Normalising
    # by *return* volatility (not dev's own std) keeps this strong in steady trends.
    ema = _ema(close, params.ema_len)
    dev = close / ema - 1.0
    ema_pos = (dev / ret_std).clip(-3, 3)

    # (4) EMA slope direction, bounded to [-1, 1]
    ema_slope = np.tanh(ema.pct_change() / ret_std)

    w = params.weights
    w_sum = sum(w.get(k, 0.0) for k in ("z_return", "ema_pos", "ema_slope")) or 1.0
    strength = (
        w.get("z_return", 0.0) * z_return.fillna(0.0)
        + w.get("ema_pos", 0.0) * ema_pos.fillna(0.0)
        + w.get("ema_slope", 0.0) * ema_slope.fillna(0.0)
    ) / w_sum

    return pd.DataFrame({
        "strength": strength,
        "z_return": z_return,
        "ema_pos": ema_pos,
        "ema_slope": ema_slope,
    })


def _hysteresis_states(strength: np.ndarray, enter: float, exit_: float) -> list[str]:
    states: list[str] = []
    prev = NEUTRAL
    for s in strength:
        if np.isnan(s):
            st = NEUTRAL
        elif s >= enter:
            st = BULL
        elif s <= -enter:
            st = BEAR
        elif prev == BULL and s >= exit_:
            st = BULL
        elif prev == BEAR and s <= -exit_:
            st = BEAR
        else:
            st = NEUTRAL
        states.append(st)
        prev = st
    return states


def _apply_persistence(states: list[str], persistence: int) -> list[str]:
    if persistence <= 1:
        return states
    reported: list[str] = []
    current = NEUTRAL
    run_state: str | None = None
    run = 0
    for st in states:
        if st == run_state:
            run += 1
        else:
            run_state, run = st, 1
        if run >= persistence:
            current = st
        reported.append(current)
    return reported


def classify(close: pd.Series, params: ClassifierParams, *,
             drop_forming: bool = True, min_rows: int = 30) -> RSResult:
    """Classify a ratio close series into bull/bear/neutral with noise filtering."""
    close = close.dropna().astype(float)
    if drop_forming and len(close) > 0:
        close = close.iloc[:-1]  # (1) exclude the still-forming candle
    if len(close) < min_rows:
        return RSResult(direction=UNKNOWN, n=len(close), reason="insufficient_data")

    comp = strength_series(close, params)
    strength = comp["strength"].to_numpy()
    states = _hysteresis_states(strength, params.neutral_band, params.hysteresis_out)
    reported = _apply_persistence(states, params.persistence)

    last_strength = float(strength[-1])
    change_pct = float(close.iloc[-1] / close.iloc[-2] - 1.0) * 100 if len(close) > 1 else 0.0
    parts = {k: float(comp[k].iloc[-1]) for k in ("z_return", "ema_pos", "ema_slope")}
    return RSResult(
        direction=reported[-1],
        strength=last_strength,
        change_pct=change_pct,
        n=len(close),
        parts=parts,
    )
