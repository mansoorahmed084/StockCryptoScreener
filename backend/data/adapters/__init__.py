"""Exchange adapters. CoinDCX is primary; CCXT is an optional secondary source."""
from __future__ import annotations

from backend.config import Config
from .base import ExchangeAdapter, Market


def build_adapter(config: Config) -> ExchangeAdapter:
    """Instantiate the adapter selected in config (``coindcx`` | ``ccxt``)."""
    name = config.exchange.lower()
    if name == "coindcx":
        from .coindcx import CoinDcxAdapter

        return CoinDcxAdapter(config)
    if name == "ccxt":
        from .ccxt_adapter import CcxtAdapter

        return CcxtAdapter(config)
    raise ValueError(f"Unknown exchange adapter: {config.exchange!r}")


__all__ = ["ExchangeAdapter", "Market", "build_adapter"]
