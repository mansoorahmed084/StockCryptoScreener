"""Shared test helpers: synthetic OHLCV frames and a fake exchange adapter."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from backend.config import timeframe_to_seconds
from backend.data.adapters.base import ExchangeAdapter, Market
from backend.data.frames import OHLCV_COLUMNS


def make_ohlcv(closes: Sequence[float], *, timeframe: str = "1h",
               start: str | None = None, volume: float = 1000.0) -> pd.DataFrame:
    """Build a canonical OHLCV frame from a list of closes (flat-ish candles).

    When ``start`` is None the series is anchored so its last candle is ~now, so
    it passes the staleness check. Pass an explicit ``start`` to test staleness.
    """
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    freq = pd.Timedelta(seconds=timeframe_to_seconds(timeframe))
    if start is None:
        end = pd.Timestamp.now(tz="UTC").floor("min")
        idx = pd.date_range(end=end, periods=n, freq=freq, tz="UTC", name="ts")
    else:
        idx = pd.date_range(start=start, periods=n, freq=freq, tz="UTC", name="ts")
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes)
    lows = np.minimum(opens, closes)
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "volume": np.full(n, volume)},
        index=idx,
    )
    return df[OHLCV_COLUMNS]


def trend(n: int, start: float, drift: float, *, noise: float = 0.0,
          seed: int = 0) -> list[float]:
    """Geometric trend series: start * (1+drift)^i plus optional noise."""
    rng = np.random.default_rng(seed)
    vals = []
    price = start
    for _ in range(n):
        price *= (1 + drift + rng.normal(0, noise))
        vals.append(price)
    return vals


def matrix_df(rows: list[dict]) -> pd.DataFrame:
    """Build a long-form RS matrix DataFrame from partial cell specs (for tests)."""
    from backend.screener.matrix import CELL_COLUMNS
    defaults = {
        "coin": "", "base": "", "timeframe": "", "direction": "neutral",
        "strength": 0.0, "change_pct": 0.0, "rank": 50.0, "method": "direct",
        "synthetic": False, "quote_volume_24h": 1e9, "quality_ok": True,
        "quality_reason": "", "n": 100,
    }
    full = [{**defaults, **r} for r in rows]
    return pd.DataFrame(full, columns=CELL_COLUMNS)


class FakeAdapter(ExchangeAdapter):
    """In-memory adapter returning pre-canned frames. No network."""

    name = "fake"

    def __init__(self, frames: dict[tuple[str, str, str], pd.DataFrame],
                 volumes: dict[tuple[str, str], float] | None = None,
                 prices: dict[tuple[str, str], float] | None = None):
        self._frames = frames
        volumes = volumes or {}
        prices = prices or {}
        self._markets = {}
        for (coin, quote, _tf) in frames:
            key = (coin.upper(), quote.upper())
            if key not in self._markets:
                self._markets[key] = Market(
                    coin=key[0], quote=key[1], symbol=f"{key[0]}_{key[1]}",
                    quote_volume_24h=volumes.get(key, 1e9),
                    last_price=prices.get(key, 1.0),
                )

    def refresh_markets(self):
        return self._markets

    def markets(self):
        return self._markets

    def fetch_ohlcv(self, coin, quote, timeframe, limit=500):
        from backend.data.frames import empty_ohlcv
        df = self._frames.get((coin.upper(), quote.upper(), timeframe))
        return df.copy() if df is not None else empty_ohlcv()
