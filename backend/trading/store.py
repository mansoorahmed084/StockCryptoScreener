"""Trade records and an append-only log of every exchange write.

``trades``  one row per trade you open: the plan (entry, SL, TP, size) and
            where it stands (pending, open, closed, failed).
``events``  every write sent to CoinDCX (or skipped in dry run) with the
            body and the answer. API keys are sent in headers, never in a
            body, so nothing secret is stored here.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_DB = "data_cache/trading.db"

PENDING, OPEN, CLOSED, FAILED = "pending", "open", "closed", "failed"


class TradeStore:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_ms INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    entry REAL, qty REAL, leverage INTEGER,
                    stop_loss REAL, take_profit REAL,
                    risk_inr REAL, margin_inr REAL,
                    order_id TEXT, position_id TEXT,
                    status TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    updated_ms INTEGER
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_ms INTEGER NOT NULL,
                    trade_id INTEGER,
                    action TEXT NOT NULL,
                    request TEXT, response TEXT,
                    ok INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS flags (
                    name TEXT PRIMARY KEY, value TEXT, updated_ms INTEGER
                );
            """)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # -- trades ----------------------------------------------------------------
    def add_trade(self, **fields: Any) -> int:
        now = int(time.time() * 1000)
        fields = {"created_ms": now, "updated_ms": now, **fields}
        cols = ",".join(fields)
        marks = ",".join("?" * len(fields))
        with self._db() as db:
            return int(db.execute(f"INSERT INTO trades ({cols}) VALUES ({marks})",
                                  list(fields.values())).lastrowid)

    def update_trade(self, trade_id: int, **fields: Any) -> None:
        fields["updated_ms"] = int(time.time() * 1000)
        sets = ",".join(f"{k}=?" for k in fields)
        with self._db() as db:
            db.execute(f"UPDATE trades SET {sets} WHERE id=?", [*fields.values(), trade_id])

    def trades(self, status: str | None = None, limit: int = 200) -> list[dict]:
        sql, args = "SELECT * FROM trades", []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        with self._db() as db:
            return [dict(r) for r in db.execute(sql, [*args, limit])]

    def latest_for_pair(self, pair: str, statuses: tuple[str, ...] = (PENDING, OPEN)) -> dict | None:
        marks = ",".join("?" * len(statuses))
        with self._db() as db:
            row = db.execute(f"SELECT * FROM trades WHERE pair=? AND status IN ({marks}) "
                             "AND mode='live' ORDER BY id DESC LIMIT 1",
                             [pair, *statuses]).fetchone()
        return dict(row) if row else None

    # -- events ----------------------------------------------------------------
    def log(self, action: str, request: Any, response: Any, ok: bool,
            trade_id: int | None = None) -> None:
        with self._db() as db:
            db.execute("INSERT INTO events (ts_ms, trade_id, action, request, response, ok) "
                       "VALUES (?,?,?,?,?,?)",
                       (int(time.time() * 1000), trade_id, action,
                        json.dumps(request, default=str), json.dumps(response, default=str),
                        int(ok)))

    def events(self, limit: int = 100) -> list[dict]:
        with self._db() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]

    # -- flags -----------------------------------------------------------------
    def set_flag(self, name: str, value: str) -> None:
        with self._db() as db:
            db.execute("INSERT INTO flags (name, value, updated_ms) VALUES (?,?,?) "
                       "ON CONFLICT(name) DO UPDATE SET value=excluded.value, "
                       "updated_ms=excluded.updated_ms",
                       (name, value, int(time.time() * 1000)))

    def flag(self, name: str) -> str | None:
        with self._db() as db:
            row = db.execute("SELECT value FROM flags WHERE name=?", (name,)).fetchone()
        return row["value"] if row else None
