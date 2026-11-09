"""The desk's setups, and the indicators they use.

Every rule looks at one *closed* daily candle ``i`` and may return a plan:
a buy-stop entry for the next candles, a stop and a target. Long only.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.indicators.common import ema, rsi

WARMUP = 200
MIN_STOP_PCT, MAX_STOP_PCT = 0.005, 0.20

TEXT = {
    "breakout20": "Uptrend (close > EMA50 > EMA200) and the close is within 3% of the "
                  "20-day high. Buy stop just above the 20-day high. Stop 2 ATR under entry.",
    "pullback20": "Strong uptrend (EMA20 > EMA50 > EMA200). The candle dipped to EMA20 "
                  "and closed above EMA50. Buy stop above its high. Stop under the 3-day "
                  "low minus 0.5 ATR.",
    "rsi_dip": "Close above EMA200 and RSI(14) under 40: a dip in an uptrend. Buy stop "
               "above the candle's high. Stop 1.5 ATR under entry.",
}
RULES = tuple(TEXT)


@dataclass(frozen=True)
class Setup:
    rule: str
    entry: float
    stop: float
    target: float

    @property
    def risk_pct(self) -> float:
        return (self.entry - self.stop) / self.entry * 100

    @property
    def rr(self) -> float:
        return (self.target - self.entry) / (self.entry - self.stop)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def with_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["close"]
    out["ema20"] = ema(c, 20)
    out["ema50"] = ema(c, 50)
    out["ema200"] = ema(c, 200)
    out["rsi14"] = rsi(c, 14)
    out["atr14"] = atr(out, 14)
    out["hh20"] = out["high"].rolling(20, min_periods=1).max()
    out["low3"] = out["low"].rolling(3, min_periods=1).min()
    out["vol5"] = out["volume"].rolling(5, min_periods=1).mean()
    out["vol50"] = out["volume"].rolling(50, min_periods=1).mean()
    return out


def arrays(d: pd.DataFrame) -> dict[str, np.ndarray]:
    return {k: d[k].to_numpy(dtype=float) for k in d.columns}


def setup_at(rule: str, a: dict[str, np.ndarray], i: int,
             target_r: float = 2.0) -> Setup | None:
    """The plan ``rule`` makes on closed candle ``i``, or None."""
    if i < WARMUP:
        return None
    c, h, lo = a["close"][i], a["high"][i], a["low"][i]
    e20, e50, e200 = a["ema20"][i], a["ema50"][i], a["ema200"][i]
    atr_ = a["atr14"][i]
    if not np.isfinite(atr_) or atr_ <= 0:
        return None
    if rule == "breakout20":
        if not (c > e50 > e200 and c >= 0.97 * a["hh20"][i]):
            return None
        entry = a["hh20"][i] * 1.001
        stop = entry - 2 * atr_
    elif rule == "pullback20":
        if not (e20 > e50 > e200 and lo <= e20 * 1.005 and c > e50):
            return None
        entry = h * 1.001
        stop = a["low3"][i] - 0.5 * atr_
    elif rule == "rsi_dip":
        r = a["rsi14"][i]
        if not (c > e200 and np.isfinite(r) and r < 40):
            return None
        entry = h * 1.001
        stop = entry - 1.5 * atr_
    else:
        raise ValueError(f"unknown rule {rule!r}")
    risk = entry - stop
    if risk <= 0 or not MIN_STOP_PCT <= risk / entry <= MAX_STOP_PCT:
        return None
    return Setup(rule, float(entry), float(stop), float(entry + target_r * risk))
