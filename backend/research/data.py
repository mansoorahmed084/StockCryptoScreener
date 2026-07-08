"""Historical candle data for research: windowed CoinDCX fetch + disk cache.

The public candles endpoint caps at 1000 rows/request but honours
startTime/endTime (verified live), so long histories are fetched in windows.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx
import pandas as pd

from backend.config import timeframe_to_seconds
from backend.data.frames import from_records

log = logging.getLogger(__name__)

BASE = "https://public.coindcx.com/market_data/candles"
CACHE_DIR = Path("data_cache/research")
MS = 1000


def fetch_history(pair: str, interval: str, days: int, *,
                  client: httpx.Client | None = None) -> pd.DataFrame:
    """Fetch ``days`` of candles for ``pair`` by paging start/end windows."""
    own = client is None
    client = client or httpx.Client(timeout=25,
                                    headers={"User-Agent": "rs-research"})
    try:
        now_ms = int(time.time() * MS)
        start_ms = now_ms - days * 86400 * MS
        window_ms = 1000 * timeframe_to_seconds(interval) * MS  # 1000 candles
        frames: list[pd.DataFrame] = []
        cursor = start_ms
        while cursor < now_ms:
            end = min(cursor + window_ms, now_ms)
            try:
                resp = client.get(BASE, params={
                    "pair": pair, "interval": interval, "limit": 1000,
                    "startTime": cursor, "endTime": end})
                resp.raise_for_status()
                rows = resp.json()
            except httpx.HTTPError as exc:
                log.warning("window fetch failed %s %s: %s", pair, cursor, exc)
                rows = []
            if rows:
                frames.append(from_records(rows))
            cursor = end
            time.sleep(0.12)  # stay polite to the public endpoint
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        return df
    finally:
        if own:
            client.close()


def load_1h(coin: str, days: int = 540, *, refresh: bool = False) -> pd.DataFrame:
    """1h history for COIN/USDT, cached on disk keyed by coin+span."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{coin.upper()}_USDT_1h_{days}d.pkl"
    if path.exists() and not refresh:
        return pd.read_pickle(path)
    df = fetch_history(f"B-{coin.upper()}_USDT", "1h", days)
    if not df.empty:
        df.to_pickle(path)
    return df


def load_1d(coin: str, days: int = 1800, *, refresh: bool = False) -> pd.DataFrame:
    """Daily history for COIN/USDT (native 1d candles), cached on disk."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{coin.upper()}_USDT_1d_{days}d.pkl"
    if path.exists() and not refresh:
        return pd.read_pickle(path)
    df = fetch_history(f"B-{coin.upper()}_USDT", "1d", days)
    if not df.empty:
        df.to_pickle(path)
    return df


def load_daily_dataset(coins: list[str], days: int = 1800,
                       *, refresh: bool = False) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for coin in coins:
        df = load_1d(coin, days, refresh=refresh)
        if df.empty or len(df) < 300:
            log.warning("skipping %s: only %d daily candles", coin,
                        0 if df.empty else len(df))
            continue
        out[coin.upper()] = df
        log.info("%s: %d 1d candles (%s .. %s)", coin, len(df),
                 df.index[0].date(), df.index[-1].date())
    return out


def load_dataset(coins: list[str], days: int = 540,
                 *, refresh: bool = False) -> dict[str, pd.DataFrame]:
    """coin -> 1h OHLCV frame; coins with no data are dropped (logged)."""
    out: dict[str, pd.DataFrame] = {}
    for coin in coins:
        df = load_1h(coin, days, refresh=refresh)
        if df.empty or len(df) < 2000:
            log.warning("skipping %s: only %d candles", coin,
                        0 if df.empty else len(df))
            continue
        out[coin.upper()] = df
        log.info("%s: %d 1h candles (%s .. %s)", coin, len(df),
                 df.index[0].date(), df.index[-1].date())
    return out
