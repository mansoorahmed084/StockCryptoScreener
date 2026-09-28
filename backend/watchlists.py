"""Named custom watchlists, shared with the chart workspace.

The lists live in the chart workspace's SQLite store (``chart.db`` in
config.yaml, default ``data_cache/chart.db``), where each row is a full
``EXCHANGE:TICKER`` symbol. This module is the coin-only view the BTC Strength
and Pattern Scanner pages use: ``{"name": ["SOL", "ETH"]}``. Stocks and
section rows in a list are left alone. Lists from the old
``data.watchlists_file`` JSON are copied in once.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from backend.chart.store import SECTION, ChartStore
from backend.chart.symbols import try_parse
from backend.config import Config

REPO_ROOT = Path(__file__).resolve().parent.parent

# Quote suffixes stripped from exchange tickers ("BINANCE:SOLUSDT" -> SOL),
# longest first. Bare symbols only lose USDT: "WBTC" and "PYUSD" are coins.
_PAIR_QUOTES = ("FDUSD", "USDT", "USDC", "BUSD", "PERP", "USD", "BTC", "INR")


def parse_symbols(text: str) -> list[str]:
    """Coin symbols from pasted text, in order, without duplicates.

    Accepts commas, spaces or new lines, and exchange-style tickers:
    ``BINANCE:SOLUSDT``, ``SOLUSDT.P``, ``SOL/USDT``, ``B-SOL_USDT`` and
    ``SOLUSDT`` all give SOL.
    """
    out: list[str] = []
    for raw in re.split(r"[\s,;]+", text.upper()):
        exchange, _, sym = raw.rpartition(":")
        perp = sym.endswith(".P")
        sym = sym.removesuffix(".P").removeprefix("B-").removeprefix("I-")
        if re.search(r"[/_]", sym):
            sym = re.split(r"[/_]", sym)[0]
        elif exchange or perp:
            for q in _PAIR_QUOTES:
                if sym.endswith(q) and len(sym) > len(q):
                    sym = sym[:-len(q)]
                    break
        elif sym.endswith("USDT") and len(sym) > 4:
            sym = sym[:-4]
        sym = re.sub(r"[^A-Z0-9]", "", sym)
        if sym and sym not in out:
            out.append(sym)
    return out


class WatchlistStore:
    def __init__(self, path: str | Path):
        self.chart = ChartStore(path)

    @classmethod
    def from_config(cls, config: Config) -> "WatchlistStore":
        def at_root(p: str) -> Path:
            path = Path(p)
            return path if path.is_absolute() else REPO_ROOT / path
        store = cls(at_root(config.chart_db))
        store.import_legacy(at_root(config.watchlists_file))
        return store

    def import_legacy(self, json_path: Path) -> None:
        """Copy the lists of the old JSON file in, once."""
        if self.chart.get_meta("legacy_watchlists_imported"):
            return
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            data = {}
        for name, coins in data.items():
            if self.chart.list_id(str(name)) is None:
                self.save(str(name), [str(c) for c in coins])
        self.chart.set_meta("legacy_watchlists_imported", "1")

    def load(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for lst in self.chart.lists():
            coins: list[str] = []
            for it in self.chart.get_list(lst["id"])["items"]:
                sym = try_parse(it["symbol"])
                if sym and sym.coin and sym.coin not in coins:
                    coins.append(sym.coin)
            out[lst["name"]] = coins
        return out

    def save(self, name: str, coins: list[str]) -> list[str]:
        """Create or replace the coins of list ``name``; returns the coins
        stored. Crypto rows for coins still wanted keep their place, new coins
        are added as USDT perpetuals, and stock / section rows stay."""
        name = name.strip()
        if not name:
            raise ValueError("A watchlist needs a name.")
        coins = list(dict.fromkeys(c.strip().upper() for c in coins if c.strip()))
        list_id = self.chart.list_id(name)
        if list_id is None:
            list_id = self.chart.create_list(name)
        kept, have = [], set()
        for it in self.chart.get_list(list_id)["items"]:
            sym = None if it["symbol"].startswith(SECTION) else try_parse(it["symbol"])
            if sym is not None and sym.coin:
                if sym.coin not in coins:
                    continue
                have.add(sym.coin)
            kept.append(it)
        kept += [{"symbol": f"BINANCE:{c}USDT.P"} for c in coins if c not in have]
        self.chart.set_items(list_id, kept)
        return coins

    def delete(self, name: str) -> None:
        list_id = self.chart.list_id(name)
        if list_id is not None:
            self.chart.delete_list(list_id)
