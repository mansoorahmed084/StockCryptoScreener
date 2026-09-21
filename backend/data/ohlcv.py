"""OHLCV fetch orchestration: timeframe resolution, resampling and caching.

The CoinDCX public candles endpoint only serves 1m / 15m / 1h / 1d. Every other
timeframe the screener uses (3m, 4h, 1w, 30m, 2h, ...) is transparently built by
fetching the largest *fetchable* timeframe that divides it and resampling up.
Results are memoised for a short TTL so a single scan does not hammer the API.
"""
from __future__ import annotations

import time

import pandas as pd

from backend.config import (
    COINDCX_FETCHABLE_TIMEFRAMES,
    COINDCX_MAX_CANDLES,
    Config,
    timeframe_to_seconds,
)
from .adapters.base import ExchangeAdapter
from .frames import resample_ohlcv


class OHLCVService:
    def __init__(self, adapter: ExchangeAdapter, config: Config,
                 *, cache_ttl: float = 30.0,
                 fetchable: set[str] | None = None,
                 max_candles: int = COINDCX_MAX_CANDLES):
        self.adapter = adapter
        self.config = config
        self.cache_ttl = cache_ttl
        self.fetchable = fetchable or set(COINDCX_FETCHABLE_TIMEFRAMES)
        self.max_candles = max_candles
        self._cache: dict[tuple[str, str, str], tuple[float, pd.DataFrame]] = {}
        # (coin, quote, source tf) -> (time, candles asked for, raw frame)
        self._raw: dict[tuple[str, str, str], tuple[float, int, pd.DataFrame]] = {}

    def source_for(self, timeframe: str) -> tuple[str, int]:
        """Return (source_timeframe, factor) used to build ``timeframe``.

        Factor is how many source candles make one target candle (1 when the
        timeframe is fetched directly).
        """
        if timeframe in self.fetchable:
            return timeframe, 1
        target_s = timeframe_to_seconds(timeframe)
        candidates = [
            (tf, target_s // timeframe_to_seconds(tf))
            for tf in self.fetchable
            if timeframe_to_seconds(tf) < target_s
            and target_s % timeframe_to_seconds(tf) == 0
        ]
        if not candidates:
            raise ValueError(
                f"No fetchable source timeframe divides {timeframe!r}; "
                f"fetchable = {sorted(self.fetchable)}"
            )
        # Largest source (smallest factor) minimises the number of candles pulled.
        source, factor = min(candidates, key=lambda c: c[1])
        return source, factor

    def get(self, coin: str, quote: str, timeframe: str,
            limit: int | None = None) -> pd.DataFrame:
        """Return an OHLCV frame for ``coin/quote`` at ``timeframe`` (cached)."""
        key = (coin.upper(), quote.upper(), timeframe)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and now - cached[0] < self.cache_ttl:
            return cached[1]

        df = self._fetch(coin, quote, timeframe, limit)
        self._cache[key] = (now, df)
        return df

    def _fetch(self, coin: str, quote: str, timeframe: str,
               limit: int | None) -> pd.DataFrame:
        limit = limit or self.config.candle_limit
        source, factor = self.source_for(timeframe)
        source_limit = min(self.max_candles, max(limit, limit * factor))
        raw = self._source(coin, quote, source, source_limit)
        if factor == 1:
            return raw
        return resample_ohlcv(raw, timeframe)

    def _source(self, coin: str, quote: str, source: str, limit: int) -> pd.DataFrame:
        """Raw candles of a fetchable timeframe.

        A fresh fetch of at least ``limit`` candles is reused (its newest
        ``limit`` rows), so 1h and 4h (built from 1h), or 1d, 1w and 1M (built
        from 1d), share one request when the bigger one is asked for first.
        """
        key = (coin.upper(), quote.upper(), source)
        now = time.monotonic()
        hit = self._raw.get(key)
        if hit and now - hit[0] < self.cache_ttl and hit[1] >= limit:
            return hit[2].tail(limit)
        raw = self.adapter.fetch_ohlcv(coin, quote, source, limit=limit)
        self._raw[key] = (now, limit, raw)
        return raw

    def clear_cache(self) -> None:
        self._cache.clear()
        self._raw.clear()
