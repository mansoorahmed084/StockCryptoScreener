"""Binance USDⓈ-M futures public data (no key): perpetuals, candles and
open-interest history. Binance keeps only 30 days of open-interest history.
"""
from __future__ import annotations

import logging
import re
import time

import httpx
import pandas as pd

log = logging.getLogger(__name__)

FAPI = "https://fapi.binance.com"
OI_PERIODS = ("5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")
MAX_OI_ROWS = 500

# Cheap coins trade as 1000PEPEUSDT, 1000000MOGUSDT, 1MBABYDOGEUSDT ...
_MULTIPLIER = re.compile(r"^(1000000|1000|1M)(?=[A-Z])")


def coin_of(base_asset: str) -> str:
    """The coin behind a futures base asset: 1000PEPE -> PEPE."""
    return _MULTIPLIER.sub("", base_asset.upper())


class BinanceFutures:
    def __init__(self, *, client: httpx.Client | None = None,
                 timeout: float = 15.0, cache_ttl: float = 60.0):
        self._client = client or httpx.Client(timeout=timeout, headers={
            "User-Agent": "crypto-rs-screener/0.1"})
        self.cache_ttl = cache_ttl
        self._cache: dict[tuple, tuple[float, object]] = {}

    def _get(self, path: str, params: dict | None = None):
        resp = self._client.get(f"{FAPI}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def _cached(self, key: tuple, fetch, ttl: float | None = None):
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and now - hit[0] < (self.cache_ttl if ttl is None else ttl):
            return hit[1]
        value = fetch()
        self._cache[key] = (now, value)
        return value

    def perpetuals(self) -> dict[str, str]:
        """Coin -> USDT perpetual symbol for every trading contract,
        e.g. {"BTC": "BTCUSDT", "PEPE": "1000PEPEUSDT"}."""
        def fetch() -> dict[str, str]:
            out: dict[str, str] = {}
            for s in self._get("/fapi/v1/exchangeInfo")["symbols"]:
                if (s.get("contractType") == "PERPETUAL"
                        and s.get("quoteAsset") == "USDT"
                        and s.get("status") == "TRADING"):
                    out.setdefault(coin_of(s["baseAsset"]), s["symbol"])
            return out
        return self._cached(("perpetuals",), fetch, ttl=3600)

    def funding_rates(self) -> dict[str, float]:
        """Symbol -> last funding rate (a fraction per 8h) for every perpetual."""
        def fetch() -> dict[str, float]:
            return {r["symbol"]: float(r["lastFundingRate"])
                    for r in self._get("/fapi/v1/premiumIndex")
                    if r.get("lastFundingRate") not in (None, "")}
        return self._cached(("funding",), fetch)

    def klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """Candles with quote volume and taker-buy quote volume, oldest first."""
        def fetch() -> pd.DataFrame:
            rows = self._get("/fapi/v1/klines", {
                "symbol": symbol, "interval": interval, "limit": min(limit, 1500)})
            df = pd.DataFrame(rows).iloc[:, [0, 1, 2, 3, 4, 5, 7, 10]]
            df.columns = ["ts", "open", "high", "low", "close", "volume",
                          "quote_volume", "taker_buy_quote"]
            df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
            return df.set_index("ts").astype(float)
        return self._cached(("klines", symbol, interval, limit), fetch)

    def open_interest(self, symbol: str, period: str, limit: int) -> pd.DataFrame:
        """Open-interest snapshots (``oi`` in coins, ``oi_value`` in USDT)."""
        if period not in OI_PERIODS:
            raise ValueError(f"open interest period must be one of {OI_PERIODS}")

        def fetch() -> pd.DataFrame:
            rows = self._get("/futures/data/openInterestHist", {
                "symbol": symbol, "period": period,
                "limit": min(limit, MAX_OI_ROWS)})
            df = pd.DataFrame(rows)
            if df.empty:
                return pd.DataFrame(columns=["oi", "oi_value"],
                                    index=pd.DatetimeIndex([], tz="UTC", name="ts"))
            df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.set_index("ts")[["sumOpenInterest", "sumOpenInterestValue"]]
            df.columns = ["oi", "oi_value"]
            return df.astype(float).sort_index()
        return self._cached(("oi", symbol, period, limit), fetch)
