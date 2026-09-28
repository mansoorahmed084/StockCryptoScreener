"""Chart symbols in TradingView's ``EXCHANGE:TICKER`` form.

  BINANCE:BTCUSDT.P     Binance USDT perpetual (".P" like TradingView)
  BINANCE:ETHBTC        Binance spot
  CRYPTOCAP:BTC.D       BTC dominance (Binance's BTCDOMUSDT index contract)
  NSE:RELIANCE          India, Yahoo RELIANCE.NS
  BSE:500325            India, Yahoo 500325.BO
  NASDAQ:AAPL, NYSE:JPM, AMEX:SPY   US, Yahoo AAPL / JPM / SPY
  NSE:NIFTY, SP:SPX ... indices with a TradingView name (INDEX_ALIASES)
  YAHOO:^N225           anything else Yahoo has
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.data.binance_futures import coin_of

CRYPTO_EXCHANGES = ("BINANCE", "CRYPTOCAP")
INDIA_EXCHANGES = ("NSE", "BSE")
US_EXCHANGES = ("NASDAQ", "NYSE", "AMEX")
STOCK_EXCHANGES = INDIA_EXCHANGES + US_EXCHANGES + ("SP", "DJ", "YAHOO")

# Quote assets of Binance spot pairs, longest first so "FDUSD" wins over "USD".
CRYPTO_QUOTES = ("FDUSD", "USDT", "USDC", "TUSD", "BUSD", "BTC", "ETH", "BNB",
                 "TRY", "EUR", "BRL", "JPY", "INR")

# TradingView index names -> Yahoo symbols.
INDEX_ALIASES = {
    "NSE:NIFTY": "^NSEI", "NSE:BANKNIFTY": "^NSEBANK", "NSE:CNXIT": "^CNXIT",
    "BSE:SENSEX": "^BSESN", "SP:SPX": "^GSPC", "NASDAQ:NDX": "^NDX",
    "NASDAQ:IXIC": "^IXIC", "DJ:DJI": "^DJI", "CBOE:VIX": "^VIX",
}
_YAHOO_TO_INDEX = {v: k for k, v in INDEX_ALIASES.items()}

# Yahoo exchange codes of the US markets we list.
_YAHOO_US = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ",
             "NYQ": "NYSE", "NYS": "NYSE", "ASE": "AMEX", "PCX": "AMEX",
             "BTS": "AMEX"}

DOMINANCE = {"BTC.D": "BTCDOMUSDT"}


@dataclass(frozen=True)
class ChartSymbol:
    exchange: str
    ticker: str

    @property
    def full(self) -> str:
        return f"{self.exchange}:{self.ticker}"

    @property
    def market(self) -> str:
        """perp | spot | dominance | stock"""
        if self.exchange == "CRYPTOCAP":
            return "dominance"
        if self.exchange == "BINANCE":
            return "perp" if self.ticker.endswith(".P") else "spot"
        return "stock"

    @property
    def is_crypto(self) -> bool:
        return self.exchange in CRYPTO_EXCHANGES

    @property
    def binance_symbol(self) -> str:
        """The symbol Binance's REST and WebSocket APIs use."""
        if self.market == "dominance":
            return DOMINANCE[self.ticker]
        return self.ticker.removesuffix(".P")

    @property
    def pair(self) -> tuple[str, str]:
        """(base, quote) of a Binance symbol: BTCUSDT.P -> (BTC, USDT)."""
        sym = self.binance_symbol
        for q in CRYPTO_QUOTES:
            if sym.endswith(q) and len(sym) > len(q):
                return sym[:-len(q)], q
        return sym, ""

    @property
    def coin(self) -> str | None:
        """The coin behind a crypto symbol (1000PEPEUSDT.P -> PEPE)."""
        if self.market in ("perp", "spot"):
            return coin_of(self.pair[0])
        return None

    @property
    def yahoo_symbol(self) -> str:
        if self.full in INDEX_ALIASES:
            return INDEX_ALIASES[self.full]
        if self.exchange == "NSE":
            return f"{self.ticker}.NS"
        if self.exchange == "BSE":
            return f"{self.ticker}.BO"
        return self.ticker

    @property
    def drawing_key(self) -> str:
        """Drawings are shared by symbols with the same prices: the spot and
        perpetual USDT legs of one coin share, everything else is its own."""
        if self.market in ("perp", "spot"):
            base, quote = self.pair
            return f"BINANCE:{base}{quote}"
        return self.full

    @property
    def delayed(self) -> bool:
        return not self.is_crypto


def parse(text: str) -> ChartSymbol:
    """``EXCHANGE:TICKER`` or a bare ticker whose market is clear from its
    shape (BTCUSDT.P, ETHBTC, BTC.D, RELIANCE.NS, 500325.BO)."""
    raw = text.strip().upper()
    if not raw:
        raise ValueError("empty symbol")
    exchange, _, ticker = raw.rpartition(":")
    if exchange:
        if exchange not in CRYPTO_EXCHANGES + STOCK_EXCHANGES + ("CBOE",):
            raise ValueError(f"unknown exchange {exchange!r}")
        if exchange == "CRYPTOCAP" and ticker not in DOMINANCE:
            raise ValueError(f"no data for {raw}")
        return ChartSymbol(exchange, ticker)
    if ticker in DOMINANCE:
        return ChartSymbol("CRYPTOCAP", ticker)
    if ticker.endswith(".NS"):
        return ChartSymbol("NSE", ticker[:-3])
    if ticker.endswith(".BO"):
        return ChartSymbol("BSE", ticker[:-3])
    if ticker.startswith("^"):
        return from_yahoo(ticker)
    sym = ticker.removesuffix(".P")
    if any(sym.endswith(q) and len(sym) > len(q) for q in CRYPTO_QUOTES):
        return ChartSymbol("BINANCE", ticker)
    raise ValueError(f"cannot tell the market of {raw!r}; use EXCHANGE:TICKER")


def try_parse(text: str) -> ChartSymbol | None:
    try:
        return parse(text)
    except ValueError:
        return None


def from_yahoo(symbol: str, exchange_code: str = "") -> ChartSymbol:
    """A Yahoo symbol (plus its exchange code from search) as a chart symbol."""
    symbol = symbol.upper()
    if symbol in _YAHOO_TO_INDEX:
        return parse(_YAHOO_TO_INDEX[symbol])
    if symbol.endswith(".NS"):
        return ChartSymbol("NSE", symbol[:-3])
    if symbol.endswith(".BO"):
        return ChartSymbol("BSE", symbol[:-3])
    if exchange_code in _YAHOO_US and not symbol.startswith("^"):
        return ChartSymbol(_YAHOO_US[exchange_code], symbol)
    return ChartSymbol("YAHOO", symbol)


def is_listed_yahoo(symbol: str, exchange_code: str) -> bool:
    """Only India and US listings (and the aliased indices) are offered."""
    s = symbol.upper()
    return (s.endswith((".NS", ".BO")) or s in _YAHOO_TO_INDEX
            or (exchange_code in _YAHOO_US and not re.search(r"[.^=]", s)))
