"""Adapter interface shared by all data sources."""
from __future__ import annotations

import abc
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Market:
    """A tradeable market on the exchange, normalised.

    ``coin`` is the target/traded asset, ``quote`` is the settlement asset,
    ``symbol`` is the exchange-native identifier passed back to the API.
    """

    coin: str
    quote: str
    symbol: str
    quote_volume_24h: float = 0.0   # in units of the QUOTE currency
    last_price: float = 0.0         # quote units per coin; lets volumes be
                                    # converted to a common USDT yardstick

    @property
    def key(self) -> tuple[str, str]:
        return (self.coin.upper(), self.quote.upper())


class ExchangeAdapter(abc.ABC):
    """Contract every data source implements.

    Implementations must return canonical OHLCV frames (see ``data.frames``).
    Methods that hit the network should be resilient (timeouts + retry) and must
    return an *empty* frame rather than raise on a missing/thin pair, so the RS
    engine can mark the cell ``unknown`` instead of crashing the whole scan.
    """

    name: str = "base"

    @abc.abstractmethod
    def refresh_markets(self) -> dict[tuple[str, str], Market]:
        """Fetch and cache the ``(coin, quote) -> Market`` map."""

    @abc.abstractmethod
    def markets(self) -> dict[tuple[str, str], Market]:
        """Return the cached market map (refreshing lazily if empty)."""

    @abc.abstractmethod
    def fetch_ohlcv(
        self, coin: str, quote: str, timeframe: str, limit: int = 500
    ) -> pd.DataFrame:
        """Return a canonical OHLCV frame for ``coin/quote`` at ``timeframe``.

        Returns an empty frame if the market does not exist.
        """

    def has_market(self, coin: str, quote: str) -> bool:
        return (coin.upper(), quote.upper()) in self.markets()
