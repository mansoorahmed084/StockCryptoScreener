"""BTC dominance (BTC.D) data.

CoinDCX has no dominance series, so two free public sources (no API key) fill in:

  * candles   — Binance USDⓈ-M futures ``BTCDOMUSDT``, the BTC Dominance index
    contract. It tracks BTC against a basket of top alts, so it rises when BTC
    takes share from alts. Unlike TradingView's BTC.D it leaves out stablecoins.
  * current % — CoinGecko ``/global`` ``market_cap_percentage.btc``. One live
    number; CoinGecko's free tier has no dominance history.

Both are best-effort: a failure returns an empty frame / None so the board marks
BTC.D unknown instead of crashing.
"""
from __future__ import annotations

import logging
import time

import httpx
import pandas as pd

from .frames import empty_ohlcv, from_records

log = logging.getLogger(__name__)

BINANCE_FAPI = "https://fapi.binance.com"
COINGECKO_API = "https://api.coingecko.com/api/v3"
BTCDOM_SYMBOL = "BTCDOMUSDT"

# Binance names every timeframe the board uses the same way we do.
BINANCE_INTERVALS = {"15m", "1h", "4h", "1d", "1w", "1M"}
BINANCE_MAX_KLINES = 1500


class BtcDominance:
    """BTC.D candles (Binance BTCDOM) and the live BTC.D % (CoinGecko)."""

    def __init__(self, *, client: httpx.Client | None = None,
                 timeout: float = 10.0, cache_ttl: float = 30.0):
        self._client = client or httpx.Client(timeout=timeout, headers={
            "User-Agent": "crypto-rs-screener/0.1",
        })
        self.cache_ttl = cache_ttl
        self._cache: dict[tuple, tuple[float, object]] = {}

    def _cached(self, key: tuple, fetch):
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and now - hit[0] < self.cache_ttl:
            return hit[1]
        value = fetch()
        self._cache[key] = (now, value)
        return value

    def candles(self, timeframe: str, limit: int = 500) -> pd.DataFrame:
        """BTCDOM OHLCV at ``timeframe``; empty frame when unavailable."""
        if timeframe not in BINANCE_INTERVALS:
            raise ValueError(f"BTCDOM has no {timeframe!r} candles "
                             f"({sorted(BINANCE_INTERVALS)})")
        limit = min(limit, BINANCE_MAX_KLINES)
        return self._cached(("candles", timeframe, limit),
                            lambda: self._fetch_candles(timeframe, limit))

    def _fetch_candles(self, timeframe: str, limit: int) -> pd.DataFrame:
        try:
            resp = self._client.get(f"{BINANCE_FAPI}/fapi/v1/klines", params={
                "symbol": BTCDOM_SYMBOL, "interval": timeframe, "limit": limit})
            resp.raise_for_status()
            rows = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("BTCDOM %s candles fetch failed: %s", timeframe, exc)
            return empty_ohlcv()
        # Kline row: [open_time, open, high, low, close, volume, close_time, ...]
        records = [{"time": r[0], "open": r[1], "high": r[2], "low": r[3],
                    "close": r[4], "volume": r[5]} for r in rows]
        return from_records(records, time_key="time", time_unit="ms")

    def current_pct(self) -> float | None:
        """BTC's share of the whole crypto market cap right now, in %."""
        return self._cached(("current_pct",), self._fetch_current_pct)

    def _fetch_current_pct(self) -> float | None:
        try:
            resp = self._client.get(f"{COINGECKO_API}/global")
            resp.raise_for_status()
            return float(resp.json()["data"]["market_cap_percentage"]["btc"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.warning("CoinGecko BTC dominance fetch failed: %s", exc)
            return None
