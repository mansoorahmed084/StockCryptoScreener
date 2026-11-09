"""SCREEN: rank the watchlist by trend, RSI, moving averages and volume.

Score out of 100, on closed daily candles:

  Trend 40     close > EMA20, > EMA50, > EMA200, and EMA50 > EMA200 (10 each)
  Momentum 20  RSI(14) 50-70 = 20; 40-50 or 70-75 = 10; else 0
  Slope 20     EMA50 higher than 10 candles ago (10); EMA20 higher than 5 ago (10)
  Volume 20    5-day / 50-day average volume >= 1.5 = 20; >= 1.1 = 10

A high score means a strong, rising trend with buyers. It is not a buy
signal by itself: the plans come from the backtested rules (plans.py).
"""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from .data import DAY, DeskData, complete
from .rules import arrays, setup_at, with_indicators
from .settings import MARKETS, Settings

log = logging.getLogger(__name__)


def change_since(d: pd.DataFrame, days: int) -> float:
    """% change of the last close vs the last close at least ``days`` earlier."""
    t_last = d["time"].iloc[-1]
    ref = d[d["time"] <= t_last - days * DAY]
    if ref.empty:
        return math.nan
    return float((d["close"].iloc[-1] / ref["close"].iloc[-1] - 1) * 100)


def score_frame(df: pd.DataFrame, rules: dict[str, dict] | None = None) -> dict | None:
    """The score of one symbol's closed daily candles. None if too short."""
    if len(df) < 60:
        return None
    d = with_indicators(df)
    last = d.iloc[-1]
    c = last["close"]
    pts, notes = 0, []
    for name in ("ema20", "ema50", "ema200"):
        if c > last[name]:
            pts += 10
    if last["ema50"] > last["ema200"]:
        pts += 10
    r = last["rsi14"]
    if 50 <= r <= 70:
        pts += 20
    elif 40 <= r < 50 or 70 < r <= 75:
        pts += 10
    if r > 75:
        notes.append("RSI overbought")
    elif r < 30:
        notes.append("RSI oversold")
    if d["ema50"].iloc[-1] > d["ema50"].iloc[-11]:
        pts += 10
    if d["ema20"].iloc[-1] > d["ema20"].iloc[-6]:
        pts += 10
    vol_ratio = float(last["vol5"] / last["vol50"]) if last["vol50"] > 0 else math.nan
    if vol_ratio >= 1.5:
        pts += 20
        notes.append("volume rising")
    elif vol_ratio >= 1.1:
        pts += 10
    if c > last["ema50"] > last["ema200"]:
        trend = "up"
    elif c < last["ema50"] < last["ema200"]:
        trend = "down"
    else:
        trend = "mixed"
    if len(df) < 200:
        notes.append("short history: EMA200 rough")
    setups = []
    if rules:
        a = arrays(d)
        i = len(d) - 1
        for rule, cfg in rules.items():
            if setup_at(rule, a, i, float(cfg.get("target_r", 2))):
                setups.append(rule)
    return {"score": float(pts), "close": float(c),
            "chg_1d": change_since(d, 1), "chg_1w": change_since(d, 7),
            "chg_1m": change_since(d, 30), "rsi": float(r) if np.isfinite(r) else math.nan,
            "trend": trend, "vol_ratio": vol_ratio, "setups": ",".join(setups),
            "notes": "; ".join(notes), "bar_time": int(last["time"])}


def run_screen(settings: Settings, data: DeskData, now: float | None = None) -> list[dict]:
    years = settings.backtest["years"] + 1
    rows = []
    for market in MARKETS:
        for sym in settings.watch[market]:
            try:
                df = complete(data.history(sym, years), now)
            except Exception as exc:   # one bad symbol must not stop the screen
                log.warning("screen: %s failed: %s", sym, exc)
                continue
            row = score_frame(df, settings.rules)
            if row:
                rows.append({"symbol": sym, "market": market, **row})
    rows.sort(key=lambda r: -r["score"])
    return rows
