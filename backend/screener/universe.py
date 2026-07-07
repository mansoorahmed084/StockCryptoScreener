"""Universe selection and liquidity gating (plan sec 4.8)."""
from __future__ import annotations

from backend.config import Config
from backend.data.adapters.base import ExchangeAdapter

USD_QUOTE = "USDT"


def pair_quote_volume(adapter: ExchangeAdapter, coin: str, base: str) -> float:
    """24h quote volume of the (coin, base) market in its own quote currency.

    Informational only (displayed per cell). Not comparable across bases — BTC
    pairs are denominated in BTC, INR pairs in INR, etc. Use
    :func:`route_volume_usdt` for the liquidity gate.
    """
    markets = adapter.markets()
    m = markets.get((coin.upper(), base.upper()))
    if m is not None:
        return m.quote_volume_24h
    leg = markets.get((coin.upper(), USD_QUOTE))
    return leg.quote_volume_24h if leg else 0.0


def route_volume_usdt(adapter: ExchangeAdapter, coin: str) -> float:
    """USDT-denominated liquidity of the coin — the leg you actually route through.

    Gives one consistent, cross-base yardstick for the liquidity gate regardless
    of whether the pair is quoted in BTC, ETH or INR.
    """
    leg = adapter.markets().get((coin.upper(), USD_QUOTE))
    return leg.quote_volume_24h if leg else 0.0


def liquidity_ok(adapter: ExchangeAdapter, coin: str, base: str,
                 min_quote_volume: float) -> bool:
    if min_quote_volume <= 0:
        return True
    return route_volume_usdt(adapter, coin) >= min_quote_volume


def select_universe(adapter: ExchangeAdapter, config: Config) -> list[str]:
    """Return the list of coins to scan, honouring the configured mode."""
    mode = config.universe.get("mode", "watchlist")
    if mode == "watchlist":
        return [c.upper() for c in config.watchlist]

    if mode == "top_volume":
        top_n = int(config.universe.get("top_n", 40))
        min_qv = config.min_quote_volume_24h
        usdt_markets = [
            m for (coin, quote), m in adapter.markets().items()
            if quote == USD_QUOTE and m.quote_volume_24h >= min_qv
        ]
        usdt_markets.sort(key=lambda m: m.quote_volume_24h, reverse=True)
        return [m.coin for m in usdt_markets[:top_n]]

    raise ValueError(f"Unknown universe mode: {mode!r}")
