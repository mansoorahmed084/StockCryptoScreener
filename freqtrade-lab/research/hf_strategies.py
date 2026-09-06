"""High-frequency signal families for ETH short-term trading.

The VMC divergence entry tops out near 12-18 trades/year on a single coin,
because it needs a confirmed pivot PAIR. Twelve trades a year is not a tradeable
short-term strategy. These families fire on single-bar conditions instead, so
they produce 50-400 signals/year.

Every one takes the same treatment as the divergence family: an optional daily
regime gate (batch 5 showed it is the most valuable filter available on 1h), a
hard ATR-based stop, and a cap on how far that stop may sit from entry.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategies import atr
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.indicators import common, wavetrend      # noqa: E402


def _emit(df: pd.DataFrame, trig: pd.Series, direction: int,
          stop_price: pd.Series, gate, gate_allow,
          max_risk_pct: float) -> pd.DataFrame:
    """Shared tail: apply the gate, apply the risk cap, build the signal frame."""
    rows = []
    closes = df["close"]
    for ts in df.index[trig.fillna(False)]:
        sp = stop_price.get(ts, np.nan)
        if not np.isfinite(sp) or sp <= 0:
            continue
        if gate is not None and gate.get(ts, "unknown") not in gate_allow:
            continue
        close = float(closes.loc[ts])
        if close <= 0 or abs(close - sp) / close > max_risk_pct:
            continue
        if (direction > 0 and sp >= close) or (direction < 0 and sp <= close):
            continue
        rows.append({"ts": ts, "direction": direction, "stop": float(sp)})
    if not rows:
        return pd.DataFrame(columns=["direction", "stop"])
    return pd.DataFrame(rows).set_index("ts").sort_index()


def ema_pullback(df: pd.DataFrame, *, side: str = "long", ema_len: int = 50,
                 trend_len: int = 200, atr_mult: float = 1.5, atr_len: int = 14,
                 max_risk_pct: float = 0.10, swing_len: int = 10,
                 gate: pd.Series | None = None,
                 gate_allow: tuple[str, ...] = ("bull", "neutral")) -> pd.DataFrame:
    """Buy the dip to a rising EMA while the longer EMA still points up.

    Trigger: the bar low pierces EMA(ema_len) but it closes back above, with
    price above EMA(trend_len). Stop under the recent swing low.
    """
    ema_f = common.ema(df["close"], ema_len)
    ema_s = common.ema(df["close"], trend_len)
    a = atr(df, atr_len)
    direction = 1 if side == "long" else -1

    if direction > 0:
        trig = (df["low"] <= ema_f) & (df["close"] > ema_f) & (df["close"] > ema_s)
        stop = df["low"].rolling(swing_len, min_periods=swing_len).min() - atr_mult * a
    else:
        trig = (df["high"] >= ema_f) & (df["close"] < ema_f) & (df["close"] < ema_s)
        stop = df["high"].rolling(swing_len, min_periods=swing_len).max() + atr_mult * a
    return _emit(df, trig, direction, stop, gate, gate_allow, max_risk_pct)


def rsi_reversion(df: pd.DataFrame, *, side: str = "long", rsi_len: int = 14,
                  rsi_extreme: float = 30.0, trend_len: int = 200,
                  require_trend: bool = True, atr_mult: float = 1.5,
                  atr_len: int = 14, max_risk_pct: float = 0.10,
                  gate: pd.Series | None = None,
                  gate_allow: tuple[str, ...] = ("bull", "neutral")) -> pd.DataFrame:
    """RSI crosses back up out of oversold. Very frequent, deliberately simple."""
    r = common.rsi(df["close"], rsi_len)
    ema_s = common.ema(df["close"], trend_len)
    a = atr(df, atr_len)
    direction = 1 if side == "long" else -1

    if direction > 0:
        trig = (r.shift(1) <= rsi_extreme) & (r > rsi_extreme)
        if require_trend:
            trig = trig & (df["close"] > ema_s)
        stop = df["low"] - atr_mult * a
    else:
        trig = (r.shift(1) >= 100 - rsi_extreme) & (r < 100 - rsi_extreme)
        if require_trend:
            trig = trig & (df["close"] < ema_s)
        stop = df["high"] + atr_mult * a
    return _emit(df, trig, direction, stop, gate, gate_allow, max_risk_pct)


def donchian_break(df: pd.DataFrame, *, side: str = "long", channel: int = 20,
                   atr_mult: float = 2.0, atr_len: int = 14,
                   max_risk_pct: float = 0.10,
                   gate: pd.Series | None = None,
                   gate_allow: tuple[str, ...] = ("bull", "neutral")) -> pd.DataFrame:
    """Momentum: the close takes out the N-bar high. Stop a fixed ATR below."""
    a = atr(df, atr_len)
    direction = 1 if side == "long" else -1
    if direction > 0:
        prior = df["high"].rolling(channel, min_periods=channel).max().shift(1)
        trig = df["close"] > prior
        stop = df["close"] - atr_mult * a
    else:
        prior = df["low"].rolling(channel, min_periods=channel).min().shift(1)
        trig = df["close"] < prior
        stop = df["close"] + atr_mult * a
    return _emit(df, trig, direction, stop, gate, gate_allow, max_risk_pct)


def vol_spike_reversal(df: pd.DataFrame, *, side: str = "long",
                       vol_mult: float = 2.0, vol_len: int = 50,
                       close_pos: float = 0.6, atr_mult: float = 1.0,
                       atr_len: int = 14, max_risk_pct: float = 0.10,
                       gate: pd.Series | None = None,
                       gate_allow: tuple[str, ...] = ("bull", "neutral")) -> pd.DataFrame:
    """A capitulation candle that does not need a divergence pair.

    Wide down bar on unusually heavy volume, but it closes in the upper part of
    its own range: sellers hit, buyers absorbed. Fires far more often than a
    confirmed VMC divergence, which is the whole point.
    """
    a = atr(df, atr_len)
    vol_avg = df["volume"].rolling(vol_len, min_periods=vol_len).mean()
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    pos = (df["close"] - df["low"]) / rng          # 0 = closed on the low
    direction = 1 if side == "long" else -1

    heavy = df["volume"] > vol_mult * vol_avg
    wide = rng > a
    if direction > 0:
        trig = heavy & wide & (df["close"] < df["open"]) & (pos >= close_pos)
        stop = df["low"] - atr_mult * a
    else:
        trig = heavy & wide & (df["close"] > df["open"]) & (pos <= 1 - close_pos)
        stop = df["high"] + atr_mult * a
    return _emit(df, trig, direction, stop, gate, gate_allow, max_risk_pct)


def keltner_squeeze(df: pd.DataFrame, *, side: str = "long", window: int = 20,
                    bb_stds: float = 2.0, kc_mult: float = 1.5,
                    atr_mult: float = 1.5, atr_len: int = 14,
                    max_risk_pct: float = 0.10,
                    gate: pd.Series | None = None,
                    gate_allow: tuple[str, ...] = ("bull", "neutral")) -> pd.DataFrame:
    """Bollinger bands inside Keltner channels (a squeeze), then a breakout."""
    mid = common.sma(df["close"], window)
    sd = df["close"].rolling(window, min_periods=window).std(ddof=0)
    a = atr(df, atr_len)
    squeeze = (((mid + bb_stds * sd) < (mid + kc_mult * a))
               & ((mid - bb_stds * sd) > (mid - kc_mult * a)))
    direction = 1 if side == "long" else -1

    if direction > 0:
        trig = squeeze.shift(1).fillna(False) & (df["close"] > mid + bb_stds * sd)
        stop = df["close"] - atr_mult * a
    else:
        trig = squeeze.shift(1).fillna(False) & (df["close"] < mid - bb_stds * sd)
        stop = df["close"] + atr_mult * a
    return _emit(df, trig, direction, stop, gate, gate_allow, max_risk_pct)


def wt_oversold_cross(df: pd.DataFrame, *, side: str = "long",
                      wt2_extreme: float = -53.0, atr_mult: float = 1.5,
                      atr_len: int = 14, max_risk_pct: float = 0.10,
                      trend_len: int = 200, require_trend: bool = False,
                      gate: pd.Series | None = None,
                      gate_allow: tuple[str, ...] = ("bull", "neutral")) -> pd.DataFrame:
    """The WT cross the repo already killed ungated, retested WITH the daily gate.

    Batch 1 measured it at -0.12R over 1198 trades with no filter. Batch 5 then
    showed the daily gate is worth about +0.37R on 1h VMC entries. This asks
    whether that gate is enough to move a high-frequency anti-edge into profit.
    """
    wt1, wt2 = wavetrend.wavetrend(df)
    a = atr(df, atr_len)
    ema_s = common.ema(df["close"], trend_len)
    direction = 1 if side == "long" else -1

    if direction > 0:
        trig = (wt1.shift(1) <= wt2.shift(1)) & (wt1 > wt2) & (wt2 <= wt2_extreme)
        if require_trend:
            trig = trig & (df["close"] > ema_s)
        stop = df["low"] - atr_mult * a
    else:
        trig = (wt1.shift(1) >= wt2.shift(1)) & (wt1 < wt2) & (wt2 >= wt2_extreme)
        if require_trend:
            trig = trig & (df["close"] < ema_s)
        stop = df["high"] + atr_mult * a
    return _emit(df, trig, direction, stop, gate, gate_allow, max_risk_pct)
