"""CoinDCX adapter — primary data source.

Uses only public endpoints (no API key required):
  * candles        GET https://public.coindcx.com/market_data/candles
  * markets detail GET https://api.coindcx.com/exchange/v1/markets_details
  * ticker (vol)   GET https://api.coindcx.com/exchange/ticker

CoinDCX has two market families we care about:
  * ``B-`` Binance-sourced crypto markets  (e.g. B-SOL_USDT, B-SOL_BTC)
  * ``I-`` CoinDCX native INR markets       (e.g. I-SOL_INR, I-BTC_INR)

The ``pair`` field returned by markets_details is exactly the ``pair`` query
parameter the candles endpoint expects, so we never hardcode symbol strings.
"""
from __future__ import annotations

import logging
import time

import httpx
import pandas as pd

from backend.config import COINDCX_FETCHABLE_TIMEFRAMES, Config
from ..frames import empty_ohlcv, from_records
from .base import ExchangeAdapter, Market

log = logging.getLogger(__name__)

PUBLIC_BASE = "https://public.coindcx.com"
API_BASE = "https://api.coindcx.com"


class CoinDcxAdapter(ExchangeAdapter):
    name = "coindcx"

    def __init__(self, config: Config, *, client: httpx.Client | None = None,
                 timeout: float = 15.0, retries: int = 3):
        self.config = config
        self._client = client or httpx.Client(timeout=timeout, headers={
            "User-Agent": "crypto-rs-screener/0.1",
        })
        self._owns_client = client is None
        self._retries = retries
        self._markets: dict[tuple[str, str], Market] = {}
        # pair string -> (coin, quote), for joining volume data
        self._pair_index: dict[str, tuple[str, str]] = {}

    # -- lifecycle -------------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "CoinDcxAdapter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- HTTP with small retry/backoff ----------------------------------------
    def _get(self, url: str, params: dict | None = None):
        last_exc: Exception | None = None
        for attempt in range(self._retries):
            try:
                resp = self._client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, ValueError) as exc:  # network or JSON error
                last_exc = exc
                sleep = 0.5 * (2 ** attempt)
                log.warning("GET %s failed (attempt %d/%d): %s",
                            url, attempt + 1, self._retries, exc)
                time.sleep(sleep)
        assert last_exc is not None
        raise last_exc

    # -- markets ---------------------------------------------------------------
    def refresh_markets(self) -> dict[tuple[str, str], Market]:
        details = self._get(f"{API_BASE}/exchange/v1/markets_details")
        volumes = self._fetch_quote_volumes()
        markets: dict[tuple[str, str], Market] = {}
        pair_index: dict[str, tuple[str, str]] = {}
        for m in details:
            if str(m.get("status", "active")).lower() not in ("active", ""):
                continue
            pair = m.get("pair")
            coin = m.get("target_currency_short_name")
            quote = m.get("base_currency_short_name")
            # markets_details `symbol` (e.g. "SOLUSDT") matches the ticker `market` key.
            market_sym = m.get("symbol")
            if not (pair and coin and quote):
                continue
            coin, quote = coin.upper(), quote.upper()
            qv, px = volumes.get(market_sym, (0.0, 0.0))
            markets[(coin, quote)] = Market(
                coin=coin, quote=quote, symbol=pair,
                quote_volume_24h=qv, last_price=px,
            )
            pair_index[pair] = (coin, quote)
        self._markets = markets
        self._pair_index = pair_index
        log.info("CoinDCX: loaded %d markets", len(markets))
        return markets

    def _fetch_quote_volumes(self) -> dict[str, tuple[float, float]]:
        """market symbol -> (approx 24h quote volume, last price)."""
        out: dict[str, tuple[float, float]] = {}
        try:
            ticker = self._get(f"{API_BASE}/exchange/ticker")
        except Exception as exc:  # ticker is best-effort
            log.warning("CoinDCX ticker fetch failed: %s", exc)
            return out
        for t in ticker:
            sym = t.get("market")
            if not sym:
                continue
            try:
                vol = float(t.get("volume", 0) or 0)
                price = float(t.get("last_price", 0) or 0)
            except (TypeError, ValueError):
                continue
            out[sym] = (vol * price, price)
        return out

    def markets(self) -> dict[tuple[str, str], Market]:
        if not self._markets:
            self.refresh_markets()
        return self._markets

    # -- candles ---------------------------------------------------------------
    def fetch_ohlcv(self, coin: str, quote: str, timeframe: str,
                    limit: int = 500) -> pd.DataFrame:
        if timeframe not in COINDCX_FETCHABLE_TIMEFRAMES:
            raise ValueError(
                f"{timeframe!r} is not fetchable from CoinDCX "
                f"({sorted(COINDCX_FETCHABLE_TIMEFRAMES)}); let OHLCVService "
                "resample it instead of calling the adapter directly."
            )
        market = self.markets().get((coin.upper(), quote.upper()))
        if market is None:
            return empty_ohlcv()
        try:
            data = self._get(
                f"{PUBLIC_BASE}/market_data/candles",
                params={"pair": market.symbol, "interval": timeframe, "limit": limit},
            )
        except Exception as exc:
            log.warning("candles fetch failed for %s/%s %s: %s",
                        coin, quote, timeframe, exc)
            return empty_ohlcv()
        return from_records(data, time_key="time", time_unit="ms")
