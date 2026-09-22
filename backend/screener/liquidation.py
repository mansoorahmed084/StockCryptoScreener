"""Estimated liquidation heatmap — a CoinGlass-style model.

No exchange publishes where its traders would be liquidated, so the levels are
estimated from public futures data, candle by candle:

  1. Open interest (OI) rose by ΔOI dollars: that much new exposure opened near
     the candle's VWAP. The taker-buy share of the candle's volume splits it
     into longs (aggressive buyers) and shorts (aggressive sellers).
  2. Each side is spread over typical leverages (10x / 25x / 50x / 100x by
     default). A long at price P with leverage L is liquidated near
     P × (1 - 1/L + mmr); a short near P × (1 + 1/L - mmr).
  3. OI fell: positions closed, so every open level shrinks by the same share.
  4. Price crossed a level (the candle's low for longs, its high for shorts):
     those positions are gone, so the level is wiped.

The heatmap is the open levels after every candle; bright bands are the
"liquidity zones" price tends to be drawn to. The window starts empty — levels
from positions opened before it are unknown — so its first candles are faint.
Sizes are model estimates in USDT, not exchange data.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Display range -> (candle / OI period, candles). Binance keeps 30 days of OI.
RANGES: dict[str, tuple[str, int]] = {
    "12h": ("5m", 144),
    "1d": ("5m", 288),
    "3d": ("15m", 288),
    "7d": ("30m", 336),
    "30d": ("2h", 360),
}

DEFAULT_LEVERAGES = {10: 0.30, 25: 0.30, 50: 0.25, 100: 0.15}
LONG, SHORT = "long", "short"


@dataclass
class LiqParams:
    leverages: dict[float, float] = field(
        default_factory=lambda: dict(DEFAULT_LEVERAGES))  # leverage -> share
    mmr: float = 0.005        # maintenance margin: liquidation comes a bit early
    bins: int = 400           # log-spaced price bins
    margin: float = 0.15      # grid reaches this far past the traded range

    @classmethod
    def from_config(cls, raw: dict) -> "LiqParams":
        lev = raw.get("leverages") or DEFAULT_LEVERAGES
        return cls(leverages={float(k): float(v) for k, v in lev.items()},
                   mmr=float(raw.get("maintenance_margin", 0.005)),
                   bins=int(raw.get("bins", 400)),
                   margin=float(raw.get("margin", 0.15)))


@dataclass
class LiqMap:
    candles: pd.DataFrame     # the window's candles (open .. close, volumes)
    prices: np.ndarray        # bin centre prices, ascending (B)
    heat: np.ndarray          # open liquidation USDT per bin after each candle (T, B)
    longs: np.ndarray         # open long-liquidation USDT per bin at the end (B)
    shorts: np.ndarray        # open short-liquidation USDT per bin at the end (B)

    @property
    def last_price(self) -> float:
        return float(self.candles["close"].iloc[-1])


def build(candles: pd.DataFrame, oi: pd.DataFrame,
          params: LiqParams | None = None) -> LiqMap:
    """Run the model over ``candles`` (oldest first) and OI snapshots."""
    params = params or LiqParams()
    candles = candles.dropna(subset=["high", "low", "close"])
    n = len(candles)
    lo = float(candles["low"].min()) * (1 - params.margin)
    hi = float(candles["high"].max()) * (1 + params.margin)
    edges = np.geomspace(lo, hi, params.bins + 1)
    prices = np.sqrt(edges[:-1] * edges[1:])

    # A snapshot at t is the OI at the candle's open, so the change during
    # candle t is OI(next snapshot) - OI(t). The forming candle has none yet.
    oi_value = oi["oi_value"].sort_index().reindex(candles.index, method="ffill")
    d_oi = (oi_value.shift(-1) - oi_value).fillna(0.0).to_numpy()
    level = oi_value.to_numpy()

    qv = candles["quote_volume"].to_numpy() if "quote_volume" in candles else \
        np.zeros(n)
    vol = candles["volume"].to_numpy() if "volume" in candles else np.zeros(n)
    typical = ((candles["high"] + candles["low"] + candles["close"]) / 3).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap = np.where(vol > 0, qv / vol, typical)
        buy = np.where(qv > 0, candles.get("taker_buy_quote", 0.5 * qv) / qv, 0.5)
    buy = np.clip(np.nan_to_num(buy, nan=0.5), 0.0, 1.0)

    highs, lows = candles["high"].to_numpy(), candles["low"].to_numpy()
    longs = np.zeros(params.bins)
    shorts = np.zeros(params.bins)
    heat = np.zeros((n, params.bins))

    def bin_of(price: float) -> int:
        return int(np.clip(np.searchsorted(edges, price) - 1, 0, params.bins - 1))

    for t in range(n):
        # Price crossed these levels during the candle: those positions are gone.
        longs[prices >= lows[t]] = 0.0
        shorts[prices <= highs[t]] = 0.0
        d = d_oi[t]
        if d > 0:
            for lev, share in params.leverages.items():
                longs[bin_of(vwap[t] * (1 - 1 / lev + params.mmr))] += d * buy[t] * share
                shorts[bin_of(vwap[t] * (1 + 1 / lev - params.mmr))] += d * (1 - buy[t]) * share
        elif d < 0 and level[t] > 0:
            keep = max(0.0, 1.0 + d / level[t])
            longs *= keep
            shorts *= keep
        heat[t] = longs + shorts

    return LiqMap(candles=candles, prices=prices, heat=heat,
                  longs=longs.copy(), shorts=shorts.copy())


def zones(m: LiqMap, k: int = 3, *, min_gap: float = 0.006,
          width: float = 0.003) -> pd.DataFrame:
    """The ``k`` biggest liquidation clusters on each side of the last price.

    A cluster is the open liquidation USDT within ±``width`` of a peak; peaks
    closer than ``min_gap`` (relative) to a bigger one are merged into it.
    Columns: side (long = below price, short = above), price, size_usd,
    dist_pct, low, high. Biggest first within each side.
    """
    last = m.last_price
    profile = m.longs + m.shorts
    rows = []
    for side, mask in ((SHORT, m.prices > last), (LONG, m.prices < last)):
        idx = np.flatnonzero(mask & (profile > 0))
        # Cluster size around every candidate bin, then greedy peak picking.
        sizes = [(profile[(m.prices >= m.prices[i] * (1 - width))
                          & (m.prices <= m.prices[i] * (1 + width))].sum(), i)
                 for i in idx]
        picked: list[int] = []
        for size, i in sorted(sizes, reverse=True):
            if len(picked) == k:
                break
            if all(abs(m.prices[i] / m.prices[j] - 1) >= min_gap for j in picked):
                picked.append(i)
                rows.append({"side": side, "price": float(m.prices[i]),
                             "size_usd": float(size),
                             "dist_pct": float(m.prices[i] / last - 1) * 100,
                             "low": float(m.prices[i] * (1 - width)),
                             "high": float(m.prices[i] * (1 + width))})
    return pd.DataFrame(rows, columns=["side", "price", "size_usd", "dist_pct",
                                       "low", "high"])


def summary(m: LiqMap) -> dict:
    """One row for the overview table: totals and the biggest zone each side."""
    z = zones(m, k=1)
    above = z[z["side"] == SHORT]
    below = z[z["side"] == LONG]
    return {
        "price": m.last_price,
        "above_usd": float(m.shorts[m.prices > m.last_price].sum()),
        "below_usd": float(m.longs[m.prices < m.last_price].sum()),
        "zone_above": float(above["price"].iloc[0]) if len(above) else np.nan,
        "zone_above_pct": float(above["dist_pct"].iloc[0]) if len(above) else np.nan,
        "zone_above_usd": float(above["size_usd"].iloc[0]) if len(above) else np.nan,
        "zone_below": float(below["price"].iloc[0]) if len(below) else np.nan,
        "zone_below_pct": float(below["dist_pct"].iloc[0]) if len(below) else np.nan,
        "zone_below_usd": float(below["size_usd"].iloc[0]) if len(below) else np.nan,
    }
