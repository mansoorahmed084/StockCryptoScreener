"""Candles, symbol search and quotes for the chart workspace, one call for
every market. Crypto comes from Binance (spot + USDT perpetuals, no key).

Candle times are UTC epoch seconds of the candle open, oldest first. Paging:
pass ``end`` (exclusive, epoch seconds) to get the ``limit`` candles before it.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from backend.data.binance_futures import BinanceFutures

from .symbols import ChartSymbol, parse

log = logging.getLogger(__name__)

SPOT_API = "https://api.binance.com"
FAPI = "https://fapi.binance.com"

# Chart timeframe -> seconds. "1M" is a calendar month (about 30 days).
TIMEFRAMES = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
              "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200,
              "1d": 86400, "1w": 604800, "1M": 2592000}
SPOT_QUOTES = ("USDT", "USDC", "FDUSD", "BTC", "ETH", "BNB")
MAX_LIMIT = {"perp": 1500, "dominance": 1500, "spot": 1000}


@dataclass
class Candles:
    symbol: ChartSymbol
    timeframe: str
    bars: list[dict]
    more: bool            # older candles exist before the first one
    delayed: bool = False

    def payload(self) -> dict:
        return {"symbol": self.symbol.full, "timeframe": self.timeframe,
                "candles": self.bars, "more": self.more, "delayed": self.delayed}


class MarketData:
    def __init__(self, *, client: httpx.Client | None = None,
                 futures: BinanceFutures | None = None, yahoo=None):
        self._client = client or httpx.Client(timeout=15.0, headers={
            "User-Agent": "crypto-rs-screener/0.1"})
        self.futures = futures or BinanceFutures(client=self._client)
        self.yahoo = yahoo
        self._cache: dict[tuple, tuple[float, object]] = {}

    def _cached(self, key: tuple, ttl: float, fetch: Callable):
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        value = fetch()
        self._cache[key] = (now, value)
        return value

    # --- symbols -------------------------------------------------------------
    def perp_symbols(self) -> set[str]:
        return set(self.futures.perpetuals().values())

    def spot_pairs(self) -> dict[str, tuple[str, str]]:
        """Spot symbol -> (base, quote) for trading pairs in SPOT_QUOTES."""
        def fetch():
            resp = self._client.get(f"{SPOT_API}/api/v3/exchangeInfo",
                                    params={"symbolStatus": "TRADING"})
            resp.raise_for_status()
            return {s["symbol"]: (s["baseAsset"], s["quoteAsset"])
                    for s in resp.json()["symbols"]
                    if s.get("quoteAsset") in SPOT_QUOTES}
        return self._cached(("spot_pairs",), 3600, fetch)

    def resolve(self, text: str) -> ChartSymbol:
        """Parse and check a symbol. A perpetual named by its coin
        (PEPEUSDT.P) resolves to the real contract (1000PEPEUSDT.P)."""
        sym = parse(text)
        if sym.market == "perp":
            perps = self.perp_symbols()
            if sym.binance_symbol not in perps:
                real = self.futures.perpetuals().get(sym.coin or "")
                if not real or sym.pair[1] != "USDT":
                    raise LookupError(f"no Binance perpetual {sym.full}")
                sym = ChartSymbol("BINANCE", f"{real}.P")
        elif sym.market == "spot" and sym.binance_symbol not in self.spot_pairs():
            raise LookupError(f"no Binance spot pair {sym.full}")
        return sym

    def describe(self, sym: ChartSymbol) -> str:
        """Long name for the chart legend."""
        if sym.market == "dominance":
            return "BTC dominance (BTCDOM index)"
        if sym.market in ("perp", "spot"):
            base, quote = sym.pair
            kind = "perpetual" if sym.market == "perp" else "spot"
            return f"{base} / {quote} {kind}"
        if self.yahoo is not None:
            return self.yahoo.name(sym) or sym.ticker
        return sym.ticker

    def search_crypto(self, q: str, limit: int = 30) -> list[dict]:
        q = q.strip().upper().removeprefix("BINANCE:").replace("/", "")
        if not q:
            return []
        out: list[tuple[tuple, dict]] = []
        for s in sorted(self.perp_symbols()):
            base = s.removesuffix("USDT")
            if s.startswith(q) or base.startswith(q) or q == f"{s}.P":
                out.append(((base != q, 0, len(s)), {
                    "symbol": f"BINANCE:{s}.P", "ticker": f"{s}.P",
                    "description": f"{base} / USDT perpetual", "exchange": "BINANCE",
                    "market": "perp"}))
        for s, (base, quote) in self.spot_pairs().items():
            if s.startswith(q) or base.startswith(q):
                rank = SPOT_QUOTES.index(quote) if quote in SPOT_QUOTES else 9
                out.append(((base != q, 1 + rank, len(s)), {
                    "symbol": f"BINANCE:{s}", "ticker": s,
                    "description": f"{base} / {quote} spot", "exchange": "BINANCE",
                    "market": "spot"}))
        if "BTC.D".startswith(q) or q in ("DOMINANCE", "BTCDOM"):
            out.append(((False, -1, 0), {
                "symbol": "CRYPTOCAP:BTC.D", "ticker": "BTC.D",
                "description": "BTC dominance (Binance BTCDOM index)",
                "exchange": "CRYPTOCAP", "market": "dominance"}))
        out.sort(key=lambda r: r[0])
        return [r for _, r in out[:limit]]

    def search(self, q: str, market: str = "all", limit: int = 30) -> list[dict]:
        rows: list[dict] = []
        if market in ("all", "crypto"):
            try:
                rows += self.search_crypto(q, limit)
            except httpx.HTTPError as exc:
                log.warning("crypto symbol search failed: %s", exc)
        if market in ("all", "india", "us") and self.yahoo is not None:
            try:
                rows += self.yahoo.search(q, market=market, limit=limit)
            except httpx.HTTPError as exc:
                log.warning("stock symbol search failed: %s", exc)
        return rows[:limit] if market != "all" else rows[:limit * 2]

    # --- candles -------------------------------------------------------------
    def candles(self, text: str, timeframe: str, *, end: int | None = None,
                limit: int = 500) -> Candles:
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {list(TIMEFRAMES)}")
        sym = self.resolve(text)
        if sym.market == "stock":
            if self.yahoo is None:
                raise LookupError("stock data is not available")
            bars, more = self.yahoo.candles(sym, timeframe, end=end, limit=limit)
            return Candles(sym, timeframe, bars, more, delayed=True)
        limit = max(1, min(limit, MAX_LIMIT[sym.market]))
        # History pages never change; the newest page does.
        ttl = 600 if end else 5
        bars = self._cached(("klines", sym.full, timeframe, end, limit), ttl,
                            lambda: self._binance_klines(sym, timeframe, end, limit))
        return Candles(sym, timeframe, bars, more=len(bars) == limit)

    def _binance_klines(self, sym: ChartSymbol, tf: str, end: int | None,
                        limit: int) -> list[dict]:
        if sym.market == "spot":
            url = f"{SPOT_API}/api/v3/klines"
        else:
            url = f"{FAPI}/fapi/v1/klines"
        params = {"symbol": sym.binance_symbol, "interval": tf, "limit": limit}
        if end:
            params["endTime"] = end * 1000 - 1
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return [{"time": r[0] // 1000, "open": float(r[1]), "high": float(r[2]),
                 "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])}
                for r in resp.json()]

    # --- quotes --------------------------------------------------------------
    def quotes(self, texts: list[str]) -> dict[str, dict]:
        """Last price and 24h / day change for each symbol. Crypto symbols
        normally get live quotes from the Binance WebSocket in the browser;
        this is the fallback and the only source for stocks."""
        out: dict[str, dict] = {}
        crypto: list[ChartSymbol] = []
        stocks: list[ChartSymbol] = []
        for t in texts:
            try:
                sym = parse(t)
            except ValueError:
                continue
            (stocks if sym.market == "stock" else crypto).append(sym)
        if crypto:
            fut, spot = self._tickers()
            for sym in crypto:
                row = (spot if sym.market == "spot" else fut).get(sym.binance_symbol)
                if row:
                    out[sym.full] = row
        if stocks and self.yahoo is not None:
            out.update(self.yahoo.quotes(stocks))
        return out

    def _tickers(self) -> tuple[dict, dict]:
        def fetch(url):
            def go():
                resp = self._client.get(url)
                resp.raise_for_status()
                return {r["symbol"]: {
                    "last": float(r["lastPrice"]),
                    "change": float(r["priceChange"]),
                    "change_pct": float(r["priceChangePercent"])}
                    for r in resp.json()}
            return go
        fut = self._cached(("tickers", "fut"), 10, fetch(f"{FAPI}/fapi/v1/ticker/24hr"))
        spot = self._cached(("tickers", "spot"), 10,
                            fetch(f"{SPOT_API}/api/v3/ticker/24hr"))
        return fut, spot
