"""Universe selection and liquidity gating (plan sec 4.8).

The gate checks every leg a ratio actually uses — the native market when one
exists, otherwise the coin's USDT leg plus the base's bridging leg — and converts
each leg's 24h volume into USDT terms so one configured floor is meaningful
across USDT-, BTC- and INR-quoted books.
"""
from __future__ import annotations

from backend.config import Config
from backend.data.adapters.base import ExchangeAdapter
from backend.data.pairs import INDEX_BASE

USD_QUOTE = "USDT"


def pair_quote_volume(adapter: ExchangeAdapter, coin: str, base: str) -> float:
    """24h volume of the (coin, base) market in its own quote currency.

    Display-only: not comparable across bases (BTC pairs are denominated in BTC,
    INR pairs in INR). The liquidity gate uses the USDT-converted helpers below.
    """
    markets = adapter.markets()
    m = markets.get((coin.upper(), base.upper()))
    if m is not None:
        return m.quote_volume_24h
    leg = markets.get((coin.upper(), USD_QUOTE))
    return leg.quote_volume_24h if leg else 0.0


def _usdt_price_of(adapter: ExchangeAdapter, asset: str) -> float | None:
    """Price of 1 unit of ``asset`` in USDT, via either market orientation."""
    if asset == USD_QUOTE:
        return 1.0
    markets = adapter.markets()
    m = markets.get((asset, USD_QUOTE))
    if m is not None and m.last_price > 0:
        return m.last_price
    inv = markets.get((USD_QUOTE, asset))          # e.g. USDT/INR
    if inv is not None and inv.last_price > 0:
        return 1.0 / inv.last_price
    return None


def _leg_volume_usdt(adapter: ExchangeAdapter, coin: str,
                     quote: str) -> float | None:
    """USDT-equivalent 24h volume of the coin/quote market; None if unknown."""
    m = adapter.markets().get((coin.upper(), quote.upper()))
    if m is None:
        return None
    price = _usdt_price_of(adapter, quote.upper())
    if price is None:
        return None
    return m.quote_volume_24h * price


def liquidity_ok(adapter: ExchangeAdapter, coin: str, base: str,
                 min_quote_volume: float) -> bool:
    """True when every leg the (coin, base) ratio uses clears the USDT floor.

    A coin can be liquid vs USDT but dead vs INR (plan sec 4.8) — a native
    market is gated on its own book, and a synthesized ratio is gated on both
    the coin's USDT leg and the base's bridging leg.
    """
    if min_quote_volume <= 0:
        return True
    coin, base = coin.upper(), base.upper()

    direct = _leg_volume_usdt(adapter, coin, base)
    if direct is not None:
        return direct >= min_quote_volume

    legs = [_leg_volume_usdt(adapter, coin, USD_QUOTE)]
    if base not in (USD_QUOTE, INDEX_BASE):
        bridge = _leg_volume_usdt(adapter, base, USD_QUOTE)
        if bridge is None:                          # e.g. INR trades as USDT/INR
            bridge = _leg_volume_usdt(adapter, USD_QUOTE, base)
        legs.append(bridge)
    return all(v is not None and v >= min_quote_volume for v in legs)


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
