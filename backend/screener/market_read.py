"""Short-term market read: 1h charts plus liquidation liquidity.

A transparent, rules-based lean for BTC and the top coins, built from the same
data as the liquidation heatmap. Each rule adds to a score:

  1h trend            close > EMA20 > EMA50 with EMA20 rising: +1 (mirror: -1)
  nearest pull        the side (above / below) whose nearest big liquidation
                      cluster is bigger per % of distance, if it is at least
                      1.5x the other side: +1 above / -1 below
  7d balance          7d map holds < half as much liquidity above as below:
                      -0.5 (more than twice as much above: +0.5)
  stretched           1h RSI > 70: -0.5 (< 30: +0.5)
  crowded             open interest +15% in 24h while price moved 5% the
                      same way: -0.5 after a pump, +0.5 after a dump
  funding             > 0.03% per 8h, longs paying: -0.5 (< -0.01%: +0.5)

When the 1h trend and the nearest pull disagree and the rest is small, the
lean is "dip first, then up" (or "bounce first, then down"). Confidence never
goes above medium: liquidity "magnets" are a tendency, not a rule.

This is a read of the data, not financial advice.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import liquidation as liq

UP, DOWN, SIDEWAYS = "up", "down", "sideways"
DIP_THEN_UP, BOUNCE_THEN_DOWN = "dip_then_up", "bounce_then_down"
LEAN_TEXT = {
    UP: "▲ Up",
    DOWN: "▼ Down",
    SIDEWAYS: "► Sideways",
    DIP_THEN_UP: "↘↗ Dip first, then up",
    BOUNCE_THEN_DOWN: "↗↘ Bounce first, then down",
}
FIRST_MOVE = {UP: UP, BOUNCE_THEN_DOWN: UP, DOWN: DOWN, DIP_THEN_UP: DOWN,
              SIDEWAYS: SIDEWAYS}

PULL_RATIO = 1.5          # one side must pull this much harder to count
MIN_DIST_PCT = 0.3        # floor on distance, so a cluster at +0.01% can't win alone
SMALL_MAP_USD = 5e6       # nearest clusters smaller than this together: weak data


@dataclass
class Cluster:
    price: float
    dist_pct: float
    size_usd: float


@dataclass
class CoinRead:
    coin: str
    symbol: str
    price: float
    trend_1h: str
    rsi_1h: float
    chg_6h: float
    chg_24h: float
    funding_pct: float
    oi_24h_pct: float
    ab_7d: float                      # 7d open liquidity above ÷ below
    above: Cluster | None             # nearest big cluster above (1d map)
    below: Cluster | None             # nearest big cluster below (1d map)
    lean: str
    confidence: str
    score: float
    reasons: list[str] = field(default_factory=list)
    closes_48h: list[float] = field(default_factory=list)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def trend_1h(closed: pd.Series) -> str:
    """up / down / mixed from closed 1h candles."""
    if len(closed) < 55:
        return "mixed"
    e20 = closed.ewm(span=20, adjust=False).mean()
    e50 = closed.ewm(span=50, adjust=False).mean()
    last = closed.iloc[-1]
    if last > e20.iloc[-1] > e50.iloc[-1] and e20.iloc[-1] > e20.iloc[-4]:
        return UP
    if last < e20.iloc[-1] < e50.iloc[-1] and e20.iloc[-1] < e20.iloc[-4]:
        return DOWN
    return "mixed"


def nearest_clusters(m: liq.LiqMap, k: int = 3) -> tuple[Cluster | None, Cluster | None]:
    """Nearest of the ``k`` biggest clusters on each side: (above, below)."""
    z = liq.zones(m, k=k)

    def pick(side: str) -> Cluster | None:
        sub = z[z["side"] == side]
        if sub.empty:
            return None
        r = sub.loc[sub["dist_pct"].abs().idxmin()]
        return Cluster(float(r["price"]), float(r["dist_pct"]), float(r["size_usd"]))
    return pick(liq.SHORT), pick(liq.LONG)


def _money(v: float) -> str:
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"${v / div:.1f}{unit}"
    return f"${v:.0f}"


def read_coin(coin: str, symbol: str, klines_1h: pd.DataFrame, oi_1h: pd.DataFrame,
              funding: float, map_1d: liq.LiqMap, map_7d: liq.LiqMap) -> CoinRead:
    """Score one coin. ``funding`` is the last funding rate as a fraction."""
    close = klines_1h["close"]
    price = float(close.iloc[-1])
    closed = close.iloc[:-1]                       # the forming candle repaints
    trend = trend_1h(closed)
    r = float(rsi(closed).iloc[-1]) if len(closed) > 15 else float("nan")
    chg_6h = (price / float(close.iloc[-7]) - 1) * 100 if len(close) > 7 else 0.0
    chg_24h = (price / float(close.iloc[-25]) - 1) * 100 if len(close) > 25 else 0.0
    oi = oi_1h["oi_value"].dropna()
    oi_24h = (float(oi.iloc[-1]) / float(oi.iloc[-25]) - 1) * 100 if len(oi) > 25 else 0.0
    s7 = liq.summary(map_7d)
    ab_7d = s7["above_usd"] / s7["below_usd"] if s7["below_usd"] else float("nan")
    above, below = nearest_clusters(map_1d)

    reasons: list[str] = []
    trend_s = {UP: 1.0, DOWN: -1.0}.get(trend, 0.0)
    reasons.append({UP: "1h uptrend", DOWN: "1h downtrend"}.get(trend, "1h trend mixed"))

    pull_s = 0.0
    pa = above.size_usd / max(abs(above.dist_pct), MIN_DIST_PCT) if above else 0.0
    pb = below.size_usd / max(abs(below.dist_pct), MIN_DIST_PCT) if below else 0.0
    if pb > 0 and pb >= PULL_RATIO * pa:
        pull_s = -1.0
        reasons.append(f"nearest pull is below: {_money(below.size_usd)} of long "
                       f"liquidations {below.dist_pct:+.1f}%")
    elif pa > 0 and pa >= PULL_RATIO * pb:
        pull_s = 1.0
        reasons.append(f"nearest pull is above: {_money(above.size_usd)} of short "
                       f"liquidations {above.dist_pct:+.1f}%")
    else:
        reasons.append("liquidity balanced near price")

    extra = 0.0
    if ab_7d == ab_7d and ab_7d < 0.5:
        extra -= 0.5
        reasons.append(f"7d map: {1 / ab_7d:.1f}x more liquidity below")
    elif ab_7d == ab_7d and ab_7d > 2:
        extra += 0.5
        reasons.append(f"7d map: {ab_7d:.1f}x more liquidity above")
    if r == r and r > 70:
        extra -= 0.5
        reasons.append(f"1h RSI {r:.0f}: stretched")
    elif r == r and r < 30:
        extra += 0.5
        reasons.append(f"1h RSI {r:.0f}: oversold")
    if oi_24h > 15 and chg_24h > 5:
        extra -= 0.5
        reasons.append(f"open interest {oi_24h:+.0f}% after a {chg_24h:+.0f}% move: "
                       "many new leveraged longs")
    elif oi_24h > 15 and chg_24h < -5:
        extra += 0.5
        reasons.append(f"open interest {oi_24h:+.0f}% after a {chg_24h:+.0f}% move: "
                       "many new leveraged shorts")
    fpct = funding * 100
    if fpct > 0.03:
        extra -= 0.5
        reasons.append(f"funding {fpct:.3f}%: longs paying")
    elif fpct < -0.01:
        extra += 0.5
        reasons.append(f"funding {fpct:.3f}%: shorts paying")

    score = trend_s + pull_s + extra
    if trend_s and pull_s and trend_s != pull_s and abs(score) < 1:
        lean = DIP_THEN_UP if trend_s > 0 else BOUNCE_THEN_DOWN
        confidence = "Low–medium"
    else:
        lean = UP if score >= 1 else DOWN if score <= -1 else SIDEWAYS
        confidence = ("Medium" if abs(score) >= 2 else
                      "Low–medium" if abs(score) >= 1 else "Low")
    # The clusters the lean leans on, not the whole map: a coin can hold $5M
    # spread thin and still have only crumbs near the price.
    near = (above.size_usd if above else 0.0) + (below.size_usd if below else 0.0)
    if near < SMALL_MAP_USD:
        confidence = "Low"
        reasons.append(f"small clusters ({_money(near)} near price): weak data")

    return CoinRead(coin=coin, symbol=symbol, price=price, trend_1h=trend,
                    rsi_1h=r, chg_6h=chg_6h, chg_24h=chg_24h, funding_pct=fpct,
                    oi_24h_pct=oi_24h, ab_7d=ab_7d, above=above, below=below,
                    lean=lean, confidence=confidence, score=score,
                    reasons=reasons, closes_48h=[float(v) for v in close.iloc[-48:]])


def market_summary(reads: list[CoinRead]) -> str:
    """One paragraph for the whole list."""
    if not reads:
        return "No data."
    btc = next((r for r in reads if r.coin == "BTC"), reads[0])
    n = len(reads)
    pull_below = sum(1 for r in reads if r.below and (
        not r.above or r.below.size_usd / max(abs(r.below.dist_pct), MIN_DIST_PCT)
        > r.above.size_usd / max(abs(r.above.dist_pct), MIN_DIST_PCT)))
    abs_ = [r.ab_7d for r in reads if r.ab_7d == r.ab_7d and r.ab_7d > 0]
    first = [FIRST_MOVE[r.lean] for r in reads]
    downs, ups = first.count(DOWN), first.count(UP)
    text = (f"{btc.coin} is {btc.chg_24h:+.1f}% over 24h and {btc.chg_6h:+.1f}% "
            f"over 6h. For {pull_below} of {n} coins the nearest big "
            f"liquidation cluster is below the price.")
    if abs_:
        med = float(np.median(abs_))
        text += (f" On the 7d maps the typical coin has "
                 + (f"{1 / med:.1f}x more liquidity below than above."
                    if med < 1 else f"{med:.1f}x more liquidity above than below."))
    if downs > n / 2:
        dists = [abs(r.below.dist_pct) for r in reads if r.below]
        d = float(np.median(dists)) if dists else float("nan")
        text += (f" Most likely next move for most coins: a dip of about {d:.1f}% "
                 f"toward the long-liquidation clusters ({downs} of {n} coins).")
    elif ups > n / 2:
        dists = [r.above.dist_pct for r in reads if r.above]
        d = float(np.median(dists)) if dists else float("nan")
        text += (f" Most likely next move for most coins: a push of about {d:.1f}% "
                 f"toward the short-liquidation clusters ({ups} of {n} coins).")
    else:
        text += " No clear direction across the list."
    return text
