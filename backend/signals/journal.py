"""Signal history / journal (plan sec 4.13).

Persists every fired signal to a small SQLite database (stdlib, no extra deps) so
you can review what happened after each setup and compute per-preset hit rates
over time. Also used by the alert dispatcher for de-dupe / cooldown.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DEFAULT_DB = "data_cache/signals.db"


@dataclass(frozen=True)
class SignalEntry:
    coin: str
    base: str
    timeframe: str
    preset: str
    direction: str
    strength: float
    fired_at: float  # unix seconds

    def dedup_key(self) -> str:
        return f"{self.preset}|{self.coin}|{self.base}|{self.timeframe}|{self.direction}"


class SignalJournal:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coin TEXT, base TEXT, timeframe TEXT, preset TEXT,
                direction TEXT, strength REAL, fired_at REAL, dedup_key TEXT
            )
            """
        )
        # Which coins matched each preset on the LAST scan — lets the dispatcher
        # alert on state changes (new matches) instead of re-firing steady states.
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS preset_state (
                preset TEXT NOT NULL,
                coin TEXT NOT NULL,
                updated REAL,
                PRIMARY KEY (preset, coin)
            )
            """
        )
        self._conn.commit()

    def log(self, entry: SignalEntry) -> None:
        self._conn.execute(
            "INSERT INTO signals(coin, base, timeframe, preset, direction, strength,"
            " fired_at, dedup_key) VALUES (?,?,?,?,?,?,?,?)",
            (entry.coin, entry.base, entry.timeframe, entry.preset, entry.direction,
             entry.strength, entry.fired_at, entry.dedup_key()),
        )
        self._conn.commit()

    def last_fired(self, dedup_key: str) -> float | None:
        cur = self._conn.execute(
            "SELECT MAX(fired_at) FROM signals WHERE dedup_key = ?", (dedup_key,))
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else None

    def recently_fired(self, dedup_key: str, cooldown_s: float,
                       now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        last = self.last_fired(dedup_key)
        return last is not None and (now - last) < cooldown_s

    def matched_coins(self, preset: str) -> set[str]:
        """Coins that matched ``preset`` on the previous scan."""
        cur = self._conn.execute(
            "SELECT coin FROM preset_state WHERE preset = ?", (preset,))
        return {row[0] for row in cur.fetchall()}

    def record_matches(self, preset: str, coins: set[str],
                       now: float | None = None) -> None:
        """Replace the stored match set for ``preset`` with ``coins``."""
        now = now if now is not None else time.time()
        self._conn.execute("DELETE FROM preset_state WHERE preset = ?", (preset,))
        self._conn.executemany(
            "INSERT INTO preset_state(preset, coin, updated) VALUES (?,?,?)",
            [(preset, coin, now) for coin in coins])
        self._conn.commit()

    def to_frame(self, limit: int | None = None) -> pd.DataFrame:
        q = "SELECT coin, base, timeframe, preset, direction, strength, fired_at" \
            " FROM signals ORDER BY fired_at DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        return pd.read_sql_query(q, self._conn)

    def preset_counts(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT preset, COUNT(*) AS fires FROM signals GROUP BY preset"
            " ORDER BY fires DESC", self._conn)

    def close(self) -> None:
        self._conn.close()
