"""CCXT adapter — optional secondary source (Binance/Bybit/OKX/...).

Only imported when ``exchange: ccxt`` is configured, so ``ccxt`` stays an
optional dependency.
"""
from __future__ import annotations

import logging

import pandas as pd

from backend.config import Config
from ..frames import empty_ohlcv, from_records
from .base import ExchangeAdapter, Market

log = logging.getLogger(__name__)


class CcxtAdapter(ExchangeAdapter):
    name = "ccxt"

    def __init__(self, config: Config):
        try:
            import ccxt  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "ccxt is not installed. `pip install ccxt` to use the ccxt adapter."
            ) from exc
        self.config = config
        exchange_id = config.ccxt_exchange
        self._exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        self._markets: dict[tuple[str, str], Market] = {}

    def refresh_markets(self) -> dict[tuple[str, str], Market]:
        raw = self._exchange.load_markets()
        try:
            tickers = self._exchange.fetch_tickers()
        except Exception:  # best effort
            tickers = {}
        markets: dict[tuple[str, str], Market] = {}
        for symbol, m in raw.items():
            base, quote = m.get("base"), m.get("quote")
            if not base or not quote or not m.get("active", True):
                continue
            if m.get("type") not in (None, "spot") and not m.get("spot", True):
                continue
            qv = 0.0
            tk = tickers.get(symbol)
            if tk:
                qv = float(tk.get("quoteVolume") or 0.0)
            markets[(base.upper(), quote.upper())] = Market(
                coin=base.upper(), quote=quote.upper(), symbol=symbol,
                quote_volume_24h=qv,
            )
        self._markets = markets
        return markets

    def markets(self) -> dict[tuple[str, str], Market]:
        if not self._markets:
            self.refresh_markets()
        return self._markets

    def fetch_ohlcv(self, coin: str, quote: str, timeframe: str,
                    limit: int = 500) -> pd.DataFrame:
        market = self.markets().get((coin.upper(), quote.upper()))
        if market is None:
            return empty_ohlcv()
        try:
            rows = self._exchange.fetch_ohlcv(market.symbol, timeframe, limit=limit)
        except Exception as exc:
            log.warning("ccxt fetch_ohlcv failed for %s: %s", market.symbol, exc)
            return empty_ohlcv()
        records = [
            {"time": r[0], "open": r[1], "high": r[2], "low": r[3],
             "close": r[4], "volume": r[5]}
            for r in rows
        ]
        return from_records(records, time_key="time", time_unit="ms")
