"""Ratio / pair builder.

Produces a ``COIN/BASE`` OHLCV series for any (coin, base, timeframe), using a
native market when one exists and otherwise synthesising it:

    SOL/BTC   = SOL/USDT ÷ BTC/USDT           (no native SOL_BTC? divide)
    SOL/ETH   = SOL/USDT ÷ ETH/USDT
    SOL/INR   = SOL/USDT × USDT/INR           (no native SOL_INR? multiply)
    SOL/INDEX = SOL/USDT ÷ equal-weight-alt-index

The resulting ratio *is* the relative-strength series consumed by the RS engine.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.config import Config
from . import quality
from .frames import OHLCV_COLUMNS, empty_ohlcv
from .ohlcv import OHLCVService

USD_QUOTE = "USDT"
INDEX_BASE = "INDEX"


@dataclass
class RatioResult:
    frame: pd.DataFrame          # OHLCV of the ratio (may be empty)
    method: str                  # 'direct' | 'divide' | 'multiply' | 'index' | 'identity'
    quality: quality.QualityReport
    synthetic: bool = False

    @property
    def close(self) -> pd.Series:
        return self.frame["close"] if not self.frame.empty else pd.Series(dtype=float)


def _combine(a: pd.DataFrame, b: pd.DataFrame, op: str) -> pd.DataFrame:
    """Elementwise OHLC combine of two aligned frames; volume taken from ``a``."""
    a, b = quality.align(a, b)
    if a.empty:
        return empty_ohlcv()
    out = pd.DataFrame(index=a.index)
    for col in ("open", "high", "low", "close"):
        if op == "divide":
            out[col] = a[col] / b[col]
        else:  # multiply
            out[col] = a[col] * b[col]
    # high/low can invert under division; re-derive from the extremes.
    out["high"] = out[["open", "high", "low", "close"]].max(axis=1)
    out["low"] = out[["open", "high", "low", "close"]].min(axis=1)
    out["volume"] = a["volume"]
    out.index.name = "ts"
    return out[OHLCV_COLUMNS].replace([np.inf, -np.inf], np.nan).dropna(subset=["close"])


class RatioBuilder:
    def __init__(self, service: OHLCVService, config: Config,
                 universe_coins: list[str] | None = None):
        self.service = service
        self.config = config
        self.universe_coins = [c.upper() for c in (universe_coins or config.watchlist)]
        self._index_cache: dict[str, pd.Series] = {}

    # -- public ---------------------------------------------------------------
    def ratio(self, coin: str, base: str, timeframe: str) -> RatioResult:
        coin, base = coin.upper(), base.upper()
        if coin == base:
            return RatioResult(empty_ohlcv(), "identity",
                               quality.QualityReport(ok=False, reason="coin==base"))

        if base == INDEX_BASE:
            frame, method, synthetic = self._index_ratio(coin, timeframe)
        elif self.service.adapter.has_market(coin, base):
            frame, method, synthetic = (
                self.service.get(coin, base, timeframe), "direct", False)
        elif base == "INR":
            frame, method, synthetic = self._multiply_leg(coin, "USDT", "USDT", "INR",
                                                          timeframe)
        else:
            frame, method, synthetic = self._divide_leg(coin, base, timeframe)

        rep = quality.assess(frame, timeframe,
                             stale_multiplier=self.config.stale_multiplier)
        return RatioResult(frame, method, rep, synthetic)

    # -- synthesis helpers ----------------------------------------------------
    def _divide_leg(self, coin: str, base: str, timeframe: str):
        """coin/base = coin/USDT ÷ base/USDT."""
        a = self.service.get(coin, USD_QUOTE, timeframe)
        b = self.service.get(base, USD_QUOTE, timeframe)
        if a.empty or b.empty:
            return empty_ohlcv(), "divide", True
        return _combine(a, b, "divide"), "divide", True

    def _multiply_leg(self, coin: str, coin_quote: str, mid: str, base: str,
                      timeframe: str):
        """coin/base = coin/coin_quote × mid/base  (e.g. SOL/USDT × USDT/INR)."""
        a = self.service.get(coin, coin_quote, timeframe)
        b = self.service.get(mid, base, timeframe)
        if a.empty or b.empty:
            return empty_ohlcv(), "multiply", True
        return _combine(a, b, "multiply"), "multiply", True

    def _index_ratio(self, coin: str, timeframe: str):
        """coin/INDEX = coin/USDT ÷ equal-weight alt index level (USDT)."""
        coin_usdt = self.service.get(coin, USD_QUOTE, timeframe)
        index = self.index_level(timeframe)
        if coin_usdt.empty or index.empty:
            return empty_ohlcv(), "index", True
        common = coin_usdt.index.intersection(index.index)
        if len(common) == 0:
            return empty_ohlcv(), "index", True
        c = coin_usdt.loc[common]
        idx = index.loc[common]
        out = pd.DataFrame(index=common)
        for col in ("open", "high", "low", "close"):
            out[col] = c[col] / idx
        out["high"] = out[["open", "high", "low", "close"]].max(axis=1)
        out["low"] = out[["open", "high", "low", "close"]].min(axis=1)
        out["volume"] = c["volume"]
        out.index.name = "ts"
        out = out[OHLCV_COLUMNS].replace([np.inf, -np.inf], np.nan).dropna(subset=["close"])
        return out, "index", True

    def index_level(self, timeframe: str) -> pd.Series:
        """Equal-weight alt-index close series (base 1.0), cached per timeframe."""
        if timeframe in self._index_cache:
            return self._index_cache[timeframe]
        exclude = {c.upper() for c in self.config.index_exclude}
        members = [c for c in self.universe_coins
                   if c not in exclude and c != USD_QUOTE]
        normalised: list[pd.Series] = []
        for m in members:
            df = self.service.get(m, USD_QUOTE, timeframe)
            if df.empty:
                continue
            close = df["close"].dropna()
            if close.empty or close.iloc[0] == 0:
                continue
            normalised.append(close / close.iloc[0])
        if not normalised:
            level = pd.Series(dtype=float)
        else:
            mat = pd.concat(normalised, axis=1, join="inner")
            level = mat.mean(axis=1)
            level.index.name = "ts"
        self._index_cache[timeframe] = level
        return level

    def clear_index_cache(self) -> None:
        self._index_cache.clear()
