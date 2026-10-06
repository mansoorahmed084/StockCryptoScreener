"""Exhaustion scalps: coins that moved a lot whose momentum is fading while
price still sits near the extreme. See SCALP.md for the method.

For an up-move (a short scalp; a down-move is the mirror for a long scalp):

1. Moved a lot: at least ``min_move_pct`` over the last 24h of candles, or
   stretched ``min_ext_atr`` ATRs away from the 24h VWAP.
2. Price hasn't followed yet: the last close is still within ``max_from_extreme_atr``
   ATRs of the move's extreme.
3. The trend is weakening, scored by confluence (one point each):
   rsi_div   price made a higher high, RSI a lower high
   wt_div    the same on WaveTrend (VuManChu's wave), with the first high
             overbought
   macd_div  the same on the MACD histogram
   vol_fade  less volume on the second push than on the first
   cvd_fade  cumulative taker-buy minus taker-sell (CVD) did not make a new high
   rsi_ext   RSI was overbought (>= 70) at the first high
   htf_ext   the 1h RSI is overbought too
   crowded   funding favours the side that is late (longs paying after a
             pump; a negative funding rate takes a point away: shorts are
             crowded and a squeeze is likelier)
4. A trade plan: the trigger is a close through the low of the last 3 closed
   candles; the stop sits a quarter ATR beyond the extreme; T1 is EMA 20, T2
   the 38.2% retracement of the move, T3 the 24h VWAP.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.indicators import common, wavetrend
from backend.screener.patterns import swing_points

BARS_24H = {"5m": 288, "15m": 96, "1h": 24}
CHECKS = ("rsi_div", "wt_div", "macd_div", "vol_fade", "cvd_fade", "rsi_ext", "htf_ext",
          "crowded")


@dataclass
class Params:
    min_move_pct: float = 8.0
    min_ext_atr: float = 3.0
    max_from_extreme_atr: float = 1.5
    pivot: int = 2                # bars each side of a swing point (right side = delay)
    max_pivot_age: int = 12       # the second swing must be this recent
    min_quote_volume: float = 5e6  # 24h USDT volume
    min_score: int = 3
    min_rr2: float = 1.5
    funding_crowded: float = 0.0002   # 0.02% per 8h


@dataclass
class ScalpSetup:
    coin: str
    symbol: str
    side: str                     # short (after an up-move) | long (after a down-move)
    price: float
    move_pct: float               # 24h change
    ext_atr: float                # distance from the 24h VWAP in ATRs
    extreme: float                # the move's high (short) or low (long)
    score: int
    checks: list[str] = field(default_factory=list)
    status: str = "armed"         # armed (waiting) | triggered (just closed through)
    trigger: float = float("nan")
    stop: float = float("nan")
    t1: float = float("nan")      # EMA 20
    t2: float = float("nan")      # 38.2% retracement of the move
    t3: float = float("nan")      # 24h VWAP
    rr1: float = float("nan")
    rr2: float = float("nan")
    rsi: float = float("nan")
    funding_pct: float = float("nan")
    oi_24h_pct: float = float("nan")


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def macd_hist(close: pd.Series) -> pd.Series:
    line = common.ema(close, 12) - common.ema(close, 26)
    return line - common.ema(line, 9)


def _pivots(s: pd.Series, k: int, high: bool) -> np.ndarray:
    """Swing highs / lows with ``k`` bars each side (a tie with the next bar
    still counts, as on the chart: the first bar to print the extreme)."""
    return swing_points(s, k, high=high)


def evaluate(df: pd.DataFrame, htf: pd.DataFrame | None = None, *, tf: str = "15m",
             funding: float = float("nan"), oi_24h_pct: float = float("nan"),
             p: Params | None = None) -> ScalpSetup | None:
    """One coin's candles (oldest first, the last one may still be forming)
    -> a setup, or None when it isn't an exhaustion candidate."""
    p = p or Params()
    d = df.iloc[:-1] if len(df) > 60 else df            # closed candles only
    n24 = BARS_24H.get(tf, 96)
    if len(d) < max(n24, 60) + 5:
        return None
    close, high, low = d["close"], d["high"], d["low"]
    a = float(atr(d).iloc[-1])
    if not a > 0:
        return None
    last = float(close.iloc[-1])
    win = d.iloc[-n24:]
    if "quote_volume" in d and float(win["quote_volume"].sum()) < p.min_quote_volume:
        return None
    vwap = float((win["close"] * win["volume"]).sum() / max(win["volume"].sum(), 1e-12))
    move = (last / float(close.iloc[-n24 - 1]) - 1) * 100
    ext = (last - vwap) / a
    hi_i, lo_i = int(np.argmax(win["high"].to_numpy())), int(np.argmin(win["low"].to_numpy()))
    up = move >= p.min_move_pct or ext >= p.min_ext_atr
    down = move <= -p.min_move_pct or ext <= -p.min_ext_atr
    if up and down:
        up, down = move > 0, move < 0
    if not (up or down):
        return None
    side = "short" if up else "long"
    extreme = float(win["high"].iloc[hi_i] if up else win["low"].iloc[lo_i])
    if abs(extreme - last) / a > p.max_from_extreme_atr:
        return None                                  # price already followed

    r = common.rsi(close)
    wt1, wt2 = wavetrend.wavetrend(d)
    mh = macd_hist(close)
    s = high if up else low
    piv = list(_pivots(s, p.pivot, high=up))
    piv = [i for i in piv if i >= len(d) - n24]
    # A fresh extreme on the last closed candle counts as the second swing
    # before it is confirmed: the point is to catch the push still in play.
    lastk = s.iloc[-p.pivot - 1:]
    fresh = s.iloc[-1] == (lastk.max() if up else lastk.min())
    if piv and fresh and ((s.iloc[-1] > s.iloc[piv[-1]]) if up
                          else (s.iloc[-1] < s.iloc[piv[-1]])):
        piv.append(len(d) - 1)
    checks: list[str] = []
    i1 = i2 = None
    if len(piv) >= 2 and piv[-1] >= len(d) - 1 - p.max_pivot_age:
        i1, i2 = int(piv[-2]), int(piv[-1])
        new_extreme = s.iloc[i2] > s.iloc[i1] if up else s.iloc[i2] < s.iloc[i1]
        if new_extreme:
            weaker = (lambda x: x.iloc[i2] < x.iloc[i1]) if up else (lambda x: x.iloc[i2] > x.iloc[i1])
            if weaker(r):
                checks.append("rsi_div")
            if weaker(wt2) and (wt2.iloc[i1] >= 53 if up else wt2.iloc[i1] <= -53):
                checks.append("wt_div")
            if weaker(mh):
                checks.append("macd_div")
            v = d["volume"]
            if v.iloc[max(i2 - 2, 0):i2 + 1].mean() < v.iloc[max(i1 - 2, 0):i1 + 1].mean():
                checks.append("vol_fade")
            if "taker_buy_quote" in d:
                delta = 2 * d["taker_buy_quote"] - d["quote_volume"]
                cvd = delta.cumsum()
                if weaker(cvd):
                    checks.append("cvd_fade")
        if (r.iloc[i1] >= 70) if up else (r.iloc[i1] <= 30):
            checks.append("rsi_ext")
    if htf is not None and len(htf) > 20:
        hr = float(common.rsi(htf["close"]).iloc[-1])
        if (hr >= 70) if up else (hr <= 30):
            checks.append("htf_ext")
    score = len(checks)
    if np.isfinite(funding):
        crowded_late = funding >= p.funding_crowded if up else funding <= -p.funding_crowded
        squeeze_risk = funding <= -p.funding_crowded if up else funding >= p.funding_crowded
        if crowded_late:
            checks.append("crowded")
            score += 1
        elif squeeze_risk:
            score -= 1
    if not checks or score < p.min_score:
        return None

    # The trade plan. Triggered = the last closed candle closed through the
    # 3 candles before it; armed = waiting for the next one to do so.
    prev3, cur = d.iloc[-4:-1], d.iloc[-1]
    if up:
        just = cur["close"] < prev3["low"].min()
        trigger = float(prev3["low"].min() if just else d.iloc[-3:]["low"].min())
        stop = extreme + 0.25 * a
        start = float(win["low"].iloc[:hi_i + 1].min())
        t2 = extreme - 0.382 * (extreme - start)
    else:
        just = cur["close"] > prev3["high"].max()
        trigger = float(prev3["high"].max() if just else d.iloc[-3:]["high"].max())
        stop = extreme - 0.25 * a
        start = float(win["high"].iloc[:lo_i + 1].max())
        t2 = extreme + 0.382 * (start - extreme)
    t1 = float(common.ema(close, 20).iloc[-1])
    live = float(df["close"].iloc[-1])
    triggered = bool(just)
    entry = float(cur["close"]) if triggered else trigger
    risk = (stop - entry) if up else (entry - stop)
    rr = (lambda t: ((entry - t) if up else (t - entry)) / risk if risk > 0 else float("nan"))
    setup = ScalpSetup(
        coin="", symbol="", side=side, price=live, move_pct=move, ext_atr=ext,
        extreme=extreme, score=score, checks=checks,
        status="triggered" if triggered else "armed", trigger=trigger, stop=stop,
        t1=t1, t2=t2, t3=vwap, rr1=rr(t1), rr2=rr(t2), rsi=float(r.iloc[-1]),
        funding_pct=funding * 100 if np.isfinite(funding) else float("nan"),
        oi_24h_pct=oi_24h_pct)
    if not (setup.rr2 >= p.min_rr2):
        return None
    return setup


def scan(fetch: Callable[[str, str, int], pd.DataFrame], coins: dict[str, str], *,
         tf: str = "15m", funding: dict[str, float] | None = None,
         open_interest: Callable[[str], float] | None = None,
         p: Params | None = None, workers: int = 8) -> list[ScalpSetup]:
    """``fetch(symbol, tf, limit)`` gives candles; ``open_interest(symbol)``
    the 24h OI change in % (optional; only asked for candidates)."""
    p = p or Params()
    funding = funding or {}

    def one(item: tuple[str, str]) -> ScalpSetup | None:
        coin, sym = item
        try:
            df = fetch(sym, tf, 300)
            htf = fetch(sym, "1h", 100) if tf != "1h" else None
            s = evaluate(df, htf, tf=tf, funding=funding.get(sym, float("nan")), p=p)
            if s is None:
                return None
            s.coin, s.symbol = coin, sym
            if open_interest:
                try:
                    s.oi_24h_pct = open_interest(sym)
                except Exception:
                    pass
            return s
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        out = [s for s in pool.map(one, coins.items()) if s is not None]
    return sorted(out, key=lambda s: (s.status != "triggered", -s.score, -s.rr2))
