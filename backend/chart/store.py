"""SQLite store for the chart workspace (``data_cache/chart.db``).

Watchlists: named lists of ``EXCHANGE:TICKER`` symbols, in order. A row whose
symbol starts with ``###`` is a section header (TradingView's export format
uses the same marker), e.g. ``###ALTS``. Each row can carry a colour flag.

Drawings: one row per drawing, keyed by the symbol's drawing key (the spot and
perpetual USDT legs of a coin share one). Points are (time, price) pairs —
UTC seconds, not pixels — so a drawing sits in the same place on every
timeframe. The browser makes the ids, so saving is a plain upsert.
"""
from __future__ import annotations

import json
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
CREATE TABLE IF NOT EXISTS drawings (
    id TEXT PRIMARY KEY,
    symbol_key TEXT NOT NULL,
    tool TEXT NOT NULL,
    points TEXT NOT NULL,
    style TEXT NOT NULL DEFAULT '{}',
    text TEXT NOT NULL DEFAULT '',
    locked INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    created_ms INTEGER NOT NULL,
    updated_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS drawings_key ON drawings(symbol_key);
"""
MAX_POINTS = 10

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

    # --- drawings ------------------------------------------------------------
    @staticmethod
    def _drawing(row: sqlite3.Row) -> dict:
        return {"id": row["id"], "key": row["symbol_key"], "tool": row["tool"],
                "points": json.loads(row["points"]), "style": json.loads(row["style"]),
                "text": row["text"], "locked": bool(row["locked"]),
                "hidden": bool(row["hidden"]), "created_ms": row["created_ms"],
                "updated_ms": row["updated_ms"]}

    def drawings(self, key: str) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM drawings WHERE symbol_key = ? "
                              "ORDER BY created_ms, id", (key,)).fetchall()
        return [self._drawing(r) for r in rows]

    def drawing(self, drawing_id: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT * FROM drawings WHERE id = ?", (drawing_id,)).fetchone()
        if not row:
            raise LookupError("no such drawing")
        return self._drawing(row)

    def save_drawing(self, drawing_id: str, d: dict) -> dict:
        """Create or replace one drawing."""
        if not drawing_id or len(drawing_id) > 64:
            raise ValueError("bad drawing id")
        key, tool = str(d.get("key", "")).strip(), str(d.get("tool", "")).strip()
        if not key or not tool:
            raise ValueError("a drawing needs a symbol key and a tool")
        points = d.get("points") or []
        if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS:
            raise ValueError(f"a drawing has 1 to {MAX_POINTS} points")
        try:
            points = [{"t": float(pt["t"]), "p": float(pt["p"])} for pt in points]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("points must be {t, p} numbers") from exc
        style = d.get("style") or {}
        if not isinstance(style, dict):
            raise ValueError("style must be an object")
        now = _now_ms()
        with self._db() as db:
            db.execute("""
                INSERT INTO drawings(id, symbol_key, tool, points, style, text, locked,
                                     hidden, created_ms, updated_ms)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET symbol_key = excluded.symbol_key,
                    tool = excluded.tool, points = excluded.points,
                    style = excluded.style, text = excluded.text,
                    locked = excluded.locked, hidden = excluded.hidden,
                    updated_ms = excluded.updated_ms""",
                (drawing_id, key, tool, json.dumps(points), json.dumps(style),
                 str(d.get("text", ""))[:2000], int(bool(d.get("locked"))),
                 int(bool(d.get("hidden"))), int(d.get("created_ms") or now), now))
        return self.drawing(drawing_id)

    def delete_drawing(self, drawing_id: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM drawings WHERE id = ?", (drawing_id,))

    def delete_drawings(self, key: str) -> int:
        with self._db() as db:
            return db.execute("DELETE FROM drawings WHERE symbol_key = ?", (key,)).rowcount
