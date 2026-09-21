"""Named custom watchlists, kept in a small JSON file.

The file lives at ``data.watchlists_file`` in config.yaml (default
``data_cache/watchlists.json``). data_cache/ is gitignored, and Docker mounts it
as a volume, so the lists survive restarts. Shape: ``{"name": ["SOL", "ETH"]}``.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

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
        self.path = Path(path)

    @classmethod
    def from_config(cls, config: Config) -> "WatchlistStore":
        path = Path(config.watchlists_file)
        return cls(path if path.is_absolute() else REPO_ROOT / path)

    def load(self) -> dict[str, list[str]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        return {str(k): [str(c).upper() for c in v] for k, v in data.items()}

    def save(self, name: str, coins: list[str]) -> list[str]:
        """Create or replace list ``name``; returns the coins stored."""
        name = name.strip()
        if not name:
            raise ValueError("A watchlist needs a name.")
        coins = list(dict.fromkeys(c.strip().upper() for c in coins if c.strip()))
        lists = self.load()
        lists[name] = coins
        self._write(lists)
        return coins

    def delete(self, name: str) -> None:
        lists = self.load()
        if lists.pop(name, None) is not None:
            self._write(lists)

    def _write(self, lists: dict[str, list[str]]) -> None:
        # Write a temp file, then swap it in: a crash never leaves half a file.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(dict(sorted(lists.items())), fh, indent=2)
        os.replace(tmp, self.path)
