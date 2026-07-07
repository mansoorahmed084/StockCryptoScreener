"""CoinDCX futures signals — funding rate (plan sec 4.10, optional).

Public real-time endpoint returns per-perp funding rate (`fr`), estimated funding
(`efr`) and volume. Open interest is not exposed by this endpoint, so we surface
funding + volume. Positive funding = longs pay shorts (crowded longs → caution).
Best-effort: returns {} on any failure.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

FUTURES_RT_URL = "https://public.coindcx.com/market_data/v3/current_prices/futures/rt"


@dataclass(frozen=True)
class FuturesInfo:
    coin: str
    funding_rate: float
    est_funding_rate: float
    volume: float

    @property
    def bias(self) -> str:
        if self.funding_rate > 1e-4:
            return "longs_pay"      # crowded longs
        if self.funding_rate < -1e-4:
            return "shorts_pay"     # crowded shorts
        return "neutral"


def _coin_from_pair(pair: str) -> str | None:
    # 'B-BTC_USDT' -> 'BTC'
    try:
        return pair.split("-", 1)[1].split("_", 1)[0].upper()
    except (IndexError, AttributeError):
        return None


def fetch_futures(quote: str = "USDT", *,
                  client: httpx.Client | None = None) -> dict[str, FuturesInfo]:
    """Return coin -> FuturesInfo for perps quoted in ``quote``."""
    owns = client is None
    client = client or httpx.Client(timeout=12, headers={"User-Agent": "rs-screener"})
    out: dict[str, FuturesInfo] = {}
    try:
        data = client.get(FUTURES_RT_URL).json()
        prices = data.get("prices", {})
        for pair, p in prices.items():
            if not pair.endswith(f"_{quote}"):
                continue
            coin = _coin_from_pair(pair)
            if not coin:
                continue
            out[coin] = FuturesInfo(
                coin=coin,
                funding_rate=float(p.get("fr", 0) or 0),
                est_funding_rate=float(p.get("efr", 0) or 0),
                volume=float(p.get("v", 0) or 0),
            )
    except Exception as exc:  # best effort
        log.warning("futures fetch failed: %s", exc)
    finally:
        if owns:
            client.close()
    return out
