"""Market-cap ranking of coins, from CoinGecko ``/coins/markets`` (free, no key).

CoinDCX has no market-cap data, so "top 500 coins" means the 500 biggest coins
by CoinGecko market cap among the ones CoinDCX lists.
"""
from __future__ import annotations

import logging
import time

import httpx

from .dominance import COINGECKO_API

log = logging.getLogger(__name__)

PER_PAGE = 250   # CoinGecko's maximum page size


def top_symbols(n: int, *, among: set[str] | None = None, max_pages: int = 8,
                pause: float = 1.5, rate_limit_wait: float = 20.0,
                client: httpx.Client | None = None,
                timeout: float = 15.0) -> list[str]:
    """Upper-case symbols of the ``n`` biggest coins by market cap, biggest first.

    With ``among`` (e.g. the coins CoinDCX lists), only those count toward
    ``n``, and pages are read until ``n`` are found or ``max_pages`` run out.
    ``pause`` seconds between pages keeps inside the keyless rate limit; a
    429 answer is retried once after ``rate_limit_wait`` seconds.

    Symbols are not unique on CoinGecko; the first (biggest) coin wins, so a
    small token that shares a big coin's ticker never replaces it. If a later
    page fails, the pages already read are kept; [] only when page 1 fails.
    """
    own = client is None
    client = client or httpx.Client(timeout=timeout, headers={
        "User-Agent": "crypto-rs-screener/0.1"})
    out: list[str] = []
    seen: set[str] = set()
    try:
        for page in range(1, max_pages + 1):
            if page > 1 and pause:
                time.sleep(pause)
            try:
                params = {"vs_currency": "usd", "order": "market_cap_desc",
                          "per_page": PER_PAGE, "page": page}
                resp = client.get(f"{COINGECKO_API}/coins/markets", params=params)
                if resp.status_code == 429 and rate_limit_wait:
                    time.sleep(rate_limit_wait)
                    resp = client.get(f"{COINGECKO_API}/coins/markets", params=params)
                resp.raise_for_status()
                rows = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("CoinGecko market-cap page %d failed: %s", page, exc)
                break
            for coin in rows:
                sym = str(coin.get("symbol", "")).upper()
                if sym and sym not in seen:
                    seen.add(sym)
                    if among is None or sym in among:
                        out.append(sym)
            if len(out) >= n or len(rows) < PER_PAGE:
                break
            if among is None and page * PER_PAGE >= n:
                break
    finally:
        if own:
            client.close()
    return out[:n]
