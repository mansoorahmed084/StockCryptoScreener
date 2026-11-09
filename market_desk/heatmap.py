"""Sector heatmap: % change of each sector index (India, US) or each coin
in its group (crypto) over 1 day, 1 week and 1 month.

The 1-day change counts the forming candle: last price vs the previous
daily close. Stocks are delayed about 15 minutes.
"""
from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .data import DeskData, frame
from .screen import change_since
from .settings import Settings, short, to_symbol

log = logging.getLogger(__name__)


def tiles(settings: Settings) -> list[dict]:
    """(market, group, label, symbol) for every tile in desk.yaml."""
    cfg = settings.section("heatmap")
    out = []
    for market in ("india", "us"):
        for label, sym in (cfg.get(market) or {}).items():
            out.append({"market": market, "group": str(label), "label": str(label),
                        "symbol": to_symbol(market, sym)})
    for group, coins in (cfg.get("crypto") or {}).items():
        for coin in coins or []:
            sym = to_symbol("crypto", coin)
            out.append({"market": "crypto", "group": str(group), "label": short(sym),
                        "symbol": sym})
    return out


def changes(bars: list[dict]) -> dict:
    df = frame(bars)
    if len(df) < 2:
        return {"last": math.nan, "chg_1d": math.nan, "chg_1w": math.nan, "chg_1m": math.nan}
    last = float(df["close"].iloc[-1])
    return {"last": last,
            "chg_1d": float((last / df["close"].iloc[-2] - 1) * 100),
            "chg_1w": change_since(df, 7), "chg_1m": change_since(df, 30)}


def build(settings: Settings, data: DeskData, market: str | None = None) -> pd.DataFrame:
    todo = [t for t in tiles(settings) if market in (None, t["market"])]

    def one(t: dict) -> dict | None:
        try:
            return {**t, **changes(data.last_bars(t["symbol"], 40))}
        except Exception as exc:   # a delisted coin or a Yahoo hiccup
            log.info("heatmap: %s failed: %s", t["symbol"], exc)
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [r for r in pool.map(one, todo) if r]
    return pd.DataFrame(rows, columns=["market", "group", "label", "symbol", "last",
                                       "chg_1d", "chg_1w", "chg_1m"])


def group_means(df: pd.DataFrame, col: str) -> pd.DataFrame:
    return (df.groupby(["market", "group"], as_index=False)[col].mean()
            .sort_values(col, ascending=False))

