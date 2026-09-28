"""SQLite store for the chart workspace (``data_cache/chart.db``).

Watchlists: named lists of ``EXCHANGE:TICKER`` symbols, in order. A row whose
symbol starts with ``###`` is a section header (TradingView's export format
uses the same marker), e.g. ``###ALTS``. Each row can carry a colour flag.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SECTION = "###"
FLAGS = ("red", "orange", "green", "blue", "purple", "cyan", "pink")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    position INTEGER NOT NULL DEFAULT 0,
    created_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS watchlist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    flag TEXT,
    position INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS watchlist_items_list ON watchlist_items(list_id, position);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULT_LIST = "Watchlist"
DEFAULT_ITEMS = [
    "###DOMINANCE", "CRYPTOCAP:BTC.D", "BINANCE:ETHBTC",
    "###CRYPTO", "BINANCE:BTCUSDT.P", "BINANCE:ETHUSDT.P", "BINANCE:SOLUSDT.P",
    "BINANCE:XRPUSDT.P", "BINANCE:LINKUSDT.P",
    "###INDIA", "NSE:NIFTY", "NSE:BANKNIFTY", "NSE:RELIANCE",
    "###US", "SP:SPX", "NASDAQ:NDX", "NASDAQ:AAPL",
]


def _now_ms() -> int:
    return int(time.time() * 1000)


class ChartStore:
    _locks: dict[str, threading.Lock] = {}

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = self._locks.setdefault(str(self.path.resolve()), threading.Lock())
        with self._db() as db:
            db.executescript(_SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            try:
                with db:
                    yield db
            finally:
                db.close()

    # --- meta ----------------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._db() as db:
            row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._db() as db:
            db.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # --- watchlists ----------------------------------------------------------
    def lists(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("""
                SELECT w.id, w.name, COUNT(i.id) AS count
                FROM watchlists w LEFT JOIN watchlist_items i
                  ON i.list_id = w.id AND i.symbol NOT LIKE '###%'
                GROUP BY w.id ORDER BY w.position, w.id""").fetchall()
        return [dict(r) for r in rows]

    def list_id(self, name: str) -> int | None:
        with self._db() as db:
            row = db.execute("SELECT id FROM watchlists WHERE name = ?", (name,)).fetchone()
        return row["id"] if row else None

    def create_list(self, name: str, symbols: list[str] | None = None) -> int:
        name = name.strip()
        if not name:
            raise ValueError("A watchlist needs a name.")
        with self._db() as db:
            if db.execute("SELECT 1 FROM watchlists WHERE name = ?", (name,)).fetchone():
                raise ValueError(f"A watchlist named {name!r} exists already.")
            pos = db.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM watchlists").fetchone()[0]
            cur = db.execute("INSERT INTO watchlists(name, position, created_ms) VALUES(?, ?, ?)",
                             (name, pos, _now_ms()))
            list_id = cur.lastrowid
        if symbols:
            self.set_items(list_id, [{"symbol": s} for s in symbols])
        return list_id

    def rename_list(self, list_id: int, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("A watchlist needs a name.")
        with self._db() as db:
            other = db.execute("SELECT id FROM watchlists WHERE name = ?", (name,)).fetchone()
            if other and other["id"] != list_id:
                raise ValueError(f"A watchlist named {name!r} exists already.")
            if not db.execute("UPDATE watchlists SET name = ? WHERE id = ?",
                              (name, list_id)).rowcount:
                raise LookupError("no such watchlist")

    def delete_list(self, list_id: int) -> None:
        with self._db() as db:
            db.execute("DELETE FROM watchlists WHERE id = ?", (list_id,))

    def get_list(self, list_id: int) -> dict:
        with self._db() as db:
            head = db.execute("SELECT id, name FROM watchlists WHERE id = ?", (list_id,)).fetchone()
            if not head:
                raise LookupError("no such watchlist")
            items = db.execute("SELECT id, symbol, flag FROM watchlist_items "
                               "WHERE list_id = ? ORDER BY position", (list_id,)).fetchall()
        return {"id": head["id"], "name": head["name"], "items": [dict(i) for i in items]}

    def set_items(self, list_id: int, items: list[dict]) -> dict:
        """Replace a list's rows (order, flags, sections) in one go."""
        clean: list[tuple[str, str | None]] = []
        seen: set[str] = set()
        for it in items:
            sym = str(it.get("symbol", "")).strip()
            if not sym:
                continue
            if sym.startswith(SECTION):
                name = sym[len(SECTION):].strip()
                if name:
                    clean.append((SECTION + name, None))
                continue
            sym = sym.upper()
            if sym in seen:
                continue
            seen.add(sym)
            flag = it.get("flag")
            clean.append((sym, flag if flag in FLAGS else None))
        with self._db() as db:
            if not db.execute("SELECT 1 FROM watchlists WHERE id = ?", (list_id,)).fetchone():
                raise LookupError("no such watchlist")
            db.execute("DELETE FROM watchlist_items WHERE list_id = ?", (list_id,))
            db.executemany(
                "INSERT INTO watchlist_items(list_id, symbol, flag, position) VALUES(?, ?, ?, ?)",
                [(list_id, s, f, i) for i, (s, f) in enumerate(clean)])
        return self.get_list(list_id)

    def ensure_default(self) -> None:
        """A first-time user gets one list with a few symbols of each market."""
        if not self.lists():
            self.create_list(DEFAULT_LIST, DEFAULT_ITEMS)
