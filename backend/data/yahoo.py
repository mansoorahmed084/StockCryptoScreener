"""Stock candles, quotes and symbol search from Yahoo Finance (free, no key).

Covers NSE / BSE (RELIANCE.NS, RELIANCE.BO) and US listings (AAPL). Prices are
delayed about 15 minutes. Yahoo keeps intraday history only for a while:

  1m        last ~30 days, at most 7 days per request
  5m-30m    last 60 days
  60m       last 730 days
  1d/1wk/1mo  all history

It has no 2h or 4h candles, so those are built from 60m candles, counted from
the first candle of each session (NSE 4h candles start at 09:15 IST, like
TradingView). Daily and bigger candles are stamped at 00:00 UTC of their
exchange date, so the chart shows the right day.
"""
from __future__ import annotations

import calendar
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import httpx

from backend.chart.symbols import ChartSymbol, from_yahoo, is_listed_yahoo

log = logging.getLogger(__name__)

API = "https://query1.finance.yahoo.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
DAY = 86400

# chart timeframe -> (Yahoo interval, 60m candles per chart candle, seconds)
INTERVALS = {
    "1m": ("1m", 1, 60), "5m": ("5m", 1, 300), "15m": ("15m", 1, 900),
    "30m": ("30m", 1, 1800), "1h": ("60m", 1, 3600), "2h": ("60m", 2, 7200),
    "4h": ("60m", 4, 14400), "1d": ("1d", 1, DAY), "1w": ("1wk", 1, 7 * DAY),
    "1M": ("1mo", 1, 31 * DAY),
}
# How far back Yahoo serves each interval, and the widest single request.
LOOKBACK = {"1m": 29 * DAY, "5m": 59 * DAY, "15m": 59 * DAY, "30m": 59 * DAY,
            "60m": 729 * DAY}
MAX_WINDOW = {"1m": 7 * DAY}
SESSION_SEC = 6.5 * 3600          # a trading day, roughly (NSE 6.25h, US 6.5h)

INDIA_SUFFIXES = (".NS", ".BO")
US_INDEX = ("^GSPC", "^NDX", "^IXIC", "^DJI", "^VIX")
INDIA_INDEX = ("^NSEI", "^NSEBANK", "^BSESN", "^CNXIT")


class Yahoo:
    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 15.0):
        self._client = client or httpx.Client(timeout=timeout, headers={"User-Agent": UA})
        self._cache: dict[tuple, tuple[float, object]] = {}
        self._names: dict[str, str] = {}

    def _cached(self, key: tuple, ttl: float, fetch: Callable):
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        value = fetch()
        self._cache[key] = (now, value)
        return value

    def _chart(self, yahoo_symbol: str, params: dict) -> dict:
        resp = self._client.get(f"{API}/v8/finance/chart/{yahoo_symbol}", params=params)
        if resp.status_code == 404:
            raise LookupError(f"Yahoo has no data for {yahoo_symbol}")
        resp.raise_for_status()
        result = resp.json()["chart"]["result"]
        if not result:
            raise LookupError(f"Yahoo has no data for {yahoo_symbol}")
        meta = result[0].get("meta", {})
        name = meta.get("longName") or meta.get("shortName")
        if name:
            self._names[yahoo_symbol] = name
        return result[0]

    # --- search --------------------------------------------------------------
    def search(self, q: str, market: str = "all", limit: int = 30) -> list[dict]:
        q = q.strip()
        if not q:
            return []

        def fetch():
            resp = self._client.get(f"{API}/v1/finance/search", params={
                "q": q, "quotesCount": 25, "newsCount": 0})
            resp.raise_for_status()
            return resp.json().get("quotes", [])
        rows = []
        for r in self._cached(("search", q.upper()), 300, fetch):
            ysym, exch = r.get("symbol", ""), r.get("exchange", "")
            qtype = r.get("quoteType", "")
            if qtype not in ("EQUITY", "ETF", "INDEX") or not is_listed_yahoo(ysym, exch):
                continue
            india = ysym.upper().endswith(INDIA_SUFFIXES) or ysym.upper() in INDIA_INDEX
            if (market == "india" and not india) or (market == "us" and india):
                continue
            sym = from_yahoo(ysym, exch)
            name = r.get("longname") or r.get("shortname") or sym.ticker
            self._names.setdefault(sym.yahoo_symbol, name)
            rows.append({"symbol": sym.full, "ticker": sym.ticker, "description": name,
                         "exchange": sym.exchange,
                         "market": {"EQUITY": "stock", "ETF": "etf",
                                    "INDEX": "index"}[qtype]})
        return rows[:limit]

    def name(self, sym: ChartSymbol) -> str | None:
        ys = sym.yahoo_symbol
        if ys not in self._names:
            try:
                self._cached(("meta", ys), 3600, lambda: self._chart(
                    ys, {"interval": "1d", "range": "1d"}))
            except (httpx.HTTPError, LookupError) as exc:
                log.warning("Yahoo name for %s failed: %s", ys, exc)
        return self._names.get(ys)

    # --- candles -------------------------------------------------------------
    def candles(self, sym: ChartSymbol, tf: str, *, end: int | None = None,
                limit: int = 500) -> tuple[list[dict], bool]:
        """(bars, more): up to ``limit`` candles opening before ``end``."""
        if tf not in INTERVALS:
            raise ValueError(f"stocks have no {tf} candles "
                             f"(use one of {', '.join(INTERVALS)})")
        interval, n, sec = INTERVALS[tf]
        limit = max(1, min(limit, 2000))
        now = int(time.time())
        period2 = min(end, now + 60) if end else now + 60
        if sec < DAY:
            base_sec = sec // n
            sessions = limit * n * base_sec / SESSION_SEC
            span = int(sessions * 7 / 5 * DAY * 1.3 + 4 * DAY)
        else:
            span = int(limit * sec * (7 / 5 if tf == "1d" else 1) * 1.1 + 10 * DAY)
        floor = now - LOOKBACK[interval] if interval in LOOKBACK else 0
        period1 = max(period2 - span, floor, period2 - MAX_WINDOW.get(interval, span))
        if period1 >= period2:
            return [], False
        ttl = 600 if end else 20
        raw = self._cached(("chart", sym.yahoo_symbol, interval, period1 // 60, period2 // 60),
                           ttl, lambda: self._chart(sym.yahoo_symbol, {
                               "interval": interval, "period1": period1,
                               "period2": period2, "includePrePost": "false"}))
        bars = self._bars(raw, tf, n)
        if end:
            bars = [b for b in bars if b["time"] < end]
        first_trade = raw.get("meta", {}).get("firstTradeDate") or 0
        more = bool(bars) and period1 > max(floor, first_trade)
        return bars[-limit:], more

    @staticmethod
    def _bars(raw: dict, tf: str, n: int) -> list[dict]:
        ts = raw.get("timestamp") or []
        quote = (raw.get("indicators", {}).get("quote") or [{}])[0]
        offset = int(raw.get("meta", {}).get("gmtoffset") or 0)
        daily = INTERVALS[tf][2] >= DAY
        step = INTERVALS[tf][2] // n
        bars: list[dict] = []
        for i, t in enumerate(ts):
            o, h, lo, c = (quote.get(k, [None] * len(ts))[i]
                           for k in ("open", "high", "low", "close"))
            if None in (o, h, lo, c):
                continue
            v = quote.get("volume", [0] * len(ts))[i] or 0
            if daily:
                t = (t + offset) // DAY * DAY   # 00:00 UTC of the exchange date
                if tf == "1M":
                    t = _month_start(t)
            bar = {"time": int(t), "open": float(o), "high": float(h),
                   "low": float(lo), "close": float(c), "volume": float(v)}
            prev = bars[-1] if bars else None
            if prev and prev["time"] == bar["time"]:
                bars[-1] = bar                  # Yahoo repeats the live candle
            elif prev and not daily and bar["time"] - prev["time"] < step:
                # An off-grid tick (the live price, or the 15:30 close print)
                # belongs to the candle before it.
                prev["high"] = max(prev["high"], bar["high"])
                prev["low"] = min(prev["low"], bar["low"])
                prev["close"] = bar["close"]
                prev["volume"] += bar["volume"]
            else:
                bars.append(bar)
        return _group_sessions(bars, n, offset) if n > 1 else bars

    # --- quotes --------------------------------------------------------------
    def quotes(self, syms: list[ChartSymbol]) -> dict[str, dict]:
        def one(sym: ChartSymbol):
            try:
                raw = self._cached(("quote", sym.yahoo_symbol), 30, lambda: self._chart(
                    sym.yahoo_symbol, {"interval": "1d", "range": "1d"}))
            except (httpx.HTTPError, LookupError) as exc:
                log.warning("Yahoo quote for %s failed: %s", sym.full, exc)
                return None
            meta = raw.get("meta", {})
            last = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            if last is None or not prev:
                return None
            return sym.full, {"last": float(last), "change": float(last - prev),
                              "change_pct": float((last - prev) / prev * 100)}
        with ThreadPoolExecutor(max_workers=8) as pool:
            return dict(r for r in pool.map(one, syms) if r)


def _month_start(t: int) -> int:
    d = time.gmtime(t)
    return calendar.timegm((d.tm_year, d.tm_mon, 1, 0, 0, 0))


def _group_sessions(bars: list[dict], n: int, offset: int) -> list[dict]:
    """Join every ``n`` hourly candles of one session into one candle."""
    out: list[dict] = []
    day, count = None, 0
    for b in bars:
        d = (b["time"] + offset) // DAY
        if d != day:
            day, count = d, 0
        if count % n == 0:
            out.append(dict(b))
        else:
            cur = out[-1]
            cur["high"] = max(cur["high"], b["high"])
            cur["low"] = min(cur["low"], b["low"])
            cur["close"] = b["close"]
            cur["volume"] += b["volume"]
        count += 1
    return out
