"""Daily candles for the desk: crypto from Binance, stocks from Yahoo.

It reads through the chart workspace's MarketData (read-only use; the desk
changes nothing there). Candle ``time`` is the UTC epoch second of the
candle open. A daily candle is *complete* once its day has passed in UTC:
``time + 86400 <= now``. That rule fits every market here: crypto days end
at 00:00 UTC, and Yahoo stamps a stock's daily candle at 00:00 UTC of its
exchange date, so an NSE or US session is always over by the next 00:00 UTC.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time
from pathlib import Path

import pandas as pd

from .settings import market_of

log = logging.getLogger(__name__)

DAY = 86400
COLUMNS = ["time", "open", "high", "low", "close", "volume"]
WARMUP = 220            # extra candles so EMA200 is settled when a test starts


def frame(bars: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(bars, columns=COLUMNS)
    if df.empty:
        return df
    df["time"] = df["time"].astype("int64")
    return df.drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)


def complete(df: pd.DataFrame, now: float | None = None) -> pd.DataFrame:
    """Only the closed daily candles."""
    now = time.time() if now is None else now
    return df[df["time"] + DAY <= now].reset_index(drop=True)


def _utc_date(ts: float) -> dt.date:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()


class DeskData:
    def __init__(self, md=None, cache_dir: str | Path | None = None):
        if md is None:
            from backend.chart.market_data import MarketData
            from backend.data.yahoo import Yahoo
            md = MarketData(yahoo=Yahoo())
        self.md = md
        self.cache_dir = Path(cache_dir) if cache_dir else None

    # --- long history (backtests, screen) -----------------------------------
    def history(self, symbol: str, years: float = 6.0) -> pd.DataFrame:
        """Daily candles for ``years`` plus warm-up, oldest first. Kept on disk
        for the rest of the UTC day (a new daily candle closes at 00:00 UTC)."""
        path = self._cache_path(symbol, years)
        if path and path.exists():
            age = time.time() - path.stat().st_mtime
            if age < 6 * 3600 and _utc_date(path.stat().st_mtime) == _utc_date(time.time()):
                try:
                    return pd.read_csv(path)
                except (OSError, ValueError) as exc:
                    log.warning("candle cache %s unreadable: %s", path.name, exc)
        df = frame(self._fetch(symbol, years))
        if path and not df.empty:
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(path, index=False)
        return df

    def _fetch(self, symbol: str, years: float) -> list[dict]:
        if market_of(symbol) == "crypto":
            need = int(years * 365) + WARMUP
            bars: list[dict] = []
            end = None
            while len(bars) < need:
                c = self.md.candles(symbol, "1d", end=end, limit=1000)
                if not c.bars:
                    break
                bars = c.bars + bars
                if not c.more:
                    break
                end = c.bars[0]["time"]
            return bars[-need:]
        need = int(years * 252) + WARMUP
        return self.md.candles(symbol, "1d", limit=min(2000, need)).bars

    def _cache_path(self, symbol: str, years: float) -> Path | None:
        if not self.cache_dir:
            return None
        safe = re.sub(r"[^A-Za-z0-9]+", "_", symbol).strip("_")
        return self.cache_dir / f"{safe}_{years:g}y.csv"

    # --- the newest candles (paper trades, heatmap) ---------------------------
    def recent(self, symbol: str, since: int, now: float | None = None) -> list[dict]:
        """Daily candles opening at or after ``since``, the forming one included."""
        now = time.time() if now is None else now
        days = int((now - since) // DAY) + 3
        c = self.md.candles(symbol, "1d", limit=max(5, min(days, 500)))
        return [b for b in c.bars if b["time"] >= since]

    def last_bars(self, symbol: str, n: int = 40) -> list[dict]:
        return self.md.candles(symbol, "1d", limit=n).bars

    def quotes(self, symbols: list[str]) -> dict[str, dict]:
        return self.md.quotes(symbols)

    def name(self, symbol: str) -> str:
        try:
            return self.md.describe(self.md.resolve(symbol))
        except Exception as exc:   # a name is nice to have, never required
            log.info("no name for %s: %s", symbol, exc)
            return symbol.split(":")[-1]
