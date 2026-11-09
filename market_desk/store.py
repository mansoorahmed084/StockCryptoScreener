"""The desk's own SQLite file: data_cache/market_desk.db.

Times are UTC epoch seconds.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS verdicts (
  run_ts INTEGER, market TEXT, rule TEXT, keep INTEGER, why TEXT,
  w_trades INTEGER, w_win REAL, w_exp REAL, w_pf REAL, w_dd REAL, w_total REAL,
  c_trades INTEGER, c_win REAL, c_exp REAL, c_pf REAL,
  recent_trades INTEGER, recent_exp REAL);
CREATE TABLE IF NOT EXISTS bt_symbols (
  run_ts INTEGER, symbol TEXT, market TEXT, scope TEXT, rule TEXT,
  trades INTEGER, win_rate REAL, exp_r REAL, pf REAL, total_r REAL, max_dd_r REAL);
CREATE TABLE IF NOT EXISTS screens (
  run_ts INTEGER, symbol TEXT, market TEXT, score REAL, close REAL,
  chg_1d REAL, chg_1w REAL, chg_1m REAL, rsi REAL, trend TEXT,
  vol_ratio REAL, setups TEXT, notes TEXT, bar_time INTEGER);
CREATE TABLE IF NOT EXISTS plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_ts INTEGER, symbol TEXT,
  market TEXT, rule TEXT, entry REAL, stop REAL, target REAL,
  valid_from INTEGER, order_bars INTEGER, score REAL, status TEXT,
  note TEXT, done_ts INTEGER);
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER, symbol TEXT,
  market TEXT, rule TEXT, entry REAL, stop REAL, target REAL,
  fill_time INTEGER, opened_ts INTEGER, risk_amt REAL, notional REAL,
  status TEXT, exit REAL, exit_time INTEGER, closed_ts INTEGER, why TEXT,
  r REAL, pnl REAL);
CREATE TABLE IF NOT EXISTS news (
  link TEXT, symbol TEXT, ts INTEGER, source TEXT, title TEXT, tone REAL,
  PRIMARY KEY (link, symbol));
CREATE TABLE IF NOT EXISTS sentiment (
  run_ts INTEGER, symbol TEXT, market TEXT, headlines_24h INTEGER,
  headlines_7d INTEGER, buzz REAL, tone REAL, label TEXT, funding REAL,
  spike INTEGER);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, op TEXT, price REAL,
  note TEXT, created_ts INTEGER, fired_ts INTEGER, fired_px REAL);
"""


def now_s() -> int:
    return int(time.time())


class DeskStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def rows(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._db() as db:
            return [dict(r) for r in db.execute(sql, params).fetchall()]

    def _insert(self, table: str, row: dict) -> int:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._db() as db:
            cur = db.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})",
                             tuple(row.values()))
            return int(cur.lastrowid)

    def _insert_many(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        cols = list(rows[0])
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        with self._db() as db:
            db.executemany(sql, [tuple(r[c] for c in cols) for r in rows])

    # --- meta ----------------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        rows = self.rows("SELECT value FROM meta WHERE key = ?", (key,))
        return rows[0]["value"] if rows else default

    def set_meta(self, key: str, value: str) -> None:
        with self._db() as db:
            db.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # --- backtests -----------------------------------------------------------
    def save_backtest(self, run_ts: int, verdicts: list[dict], symbols: list[dict]) -> None:
        self._insert_many("verdicts", [{"run_ts": run_ts, **v} for v in verdicts])
        self._insert_many("bt_symbols", [{"run_ts": run_ts, **s} for s in symbols])
        with self._db() as db:   # keep the last 30 runs
            for table in ("verdicts", "bt_symbols"):
                db.execute(f"DELETE FROM {table} WHERE run_ts NOT IN (SELECT DISTINCT run_ts "
                           f"FROM {table} ORDER BY run_ts DESC LIMIT 30)")

    def _latest(self, table: str) -> list[dict]:
        return self.rows(f"SELECT * FROM {table} WHERE run_ts = "
                         f"(SELECT MAX(run_ts) FROM {table})")

    def latest_verdicts(self) -> list[dict]:
        return self._latest("verdicts")

    def latest_bt_symbols(self) -> list[dict]:
        return self._latest("bt_symbols")

    # --- screen --------------------------------------------------------------
    def save_screen(self, run_ts: int, rows: list[dict]) -> None:
        self._insert_many("screens", [{"run_ts": run_ts, **r} for r in rows])
        with self._db() as db:
            db.execute("DELETE FROM screens WHERE run_ts NOT IN (SELECT DISTINCT run_ts "
                       "FROM screens ORDER BY run_ts DESC LIMIT 60)")

    def latest_screen(self) -> list[dict]:
        return sorted(self._latest("screens"), key=lambda r: -r["score"])

    # --- plans and paper trades ----------------------------------------------
    def add_plan(self, plan: dict) -> int:
        return self._insert("plans", {"created_ts": now_s(), "status": "pending", **plan})

    def plans(self, status: str | None = None, limit: int = 500) -> list[dict]:
        if status:
            return self.rows("SELECT * FROM plans WHERE status = ? ORDER BY id DESC LIMIT ?",
                             (status, limit))
        return self.rows("SELECT * FROM plans ORDER BY id DESC LIMIT ?", (limit,))

    def set_plan_status(self, plan_id: int, status: str, note: str | None = None) -> None:
        with self._db() as db:
            db.execute("UPDATE plans SET status = ?, note = COALESCE(?, note), done_ts = ? "
                       "WHERE id = ?", (status, note, now_s(), plan_id))

    def add_trade(self, trade: dict) -> int:
        return self._insert("trades", {"opened_ts": now_s(), "status": "open", **trade})

    def trades(self, status: str | None = None, limit: int = 1000) -> list[dict]:
        if status:
            return self.rows("SELECT * FROM trades WHERE status = ? ORDER BY id DESC LIMIT ?",
                             (status, limit))
        return self.rows("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))

    def close_trade(self, trade_id: int, *, exit_px: float, exit_time: int, why: str,
                    r: float, pnl: float) -> None:
        with self._db() as db:
            db.execute("UPDATE trades SET status = 'closed', exit = ?, exit_time = ?, "
                       "closed_ts = ?, why = ?, r = ?, pnl = ? WHERE id = ?",
                       (exit_px, exit_time, now_s(), why, r, pnl, trade_id))

    # --- news ----------------------------------------------------------------
    def add_news(self, rows: list[dict]) -> int:
        """New headlines only (same link + symbol is skipped). Returns how many."""
        added = 0
        with self._db() as db:
            for r in rows:
                cur = db.execute("INSERT OR IGNORE INTO news (link, symbol, ts, source, title, "
                                 "tone) VALUES (?, ?, ?, ?, ?, ?)",
                                 (r["link"], r["symbol"], r["ts"], r["source"], r["title"],
                                  r["tone"]))
                added += cur.rowcount
            db.execute("DELETE FROM news WHERE ts < ?", (now_s() - 60 * 86400,))
        return added

    def news(self, symbol: str | None = None, since: int = 0, limit: int = 200) -> list[dict]:
        if symbol:
            return self.rows("SELECT * FROM news WHERE symbol = ? AND ts >= ? "
                             "ORDER BY ts DESC LIMIT ?", (symbol, since, limit))
        return self.rows("SELECT * FROM news WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
                         (since, limit))

    def save_sentiment(self, run_ts: int, rows: list[dict]) -> None:
        self._insert_many("sentiment", [{"run_ts": run_ts, **r} for r in rows])

    def latest_sentiment(self) -> list[dict]:
        return self._latest("sentiment")

    def daily_counts(self, symbol: str, before: int, days: int = 14) -> list[int]:
        """24-hour headline counts of earlier nights: the last run of each UTC
        day, at least 20 hours before ``before``, newest ``days`` days."""
        rows = self.rows("SELECT run_ts, headlines_24h FROM sentiment WHERE symbol = ? "
                         "AND run_ts <= ? ORDER BY run_ts DESC LIMIT 200",
                         (symbol, before - 20 * 3600))
        by_day: dict[int, int] = {}
        for r in rows:
            by_day.setdefault(r["run_ts"] // 86400, r["headlines_24h"])
        return list(by_day.values())[:days]

    # --- alerts --------------------------------------------------------------
    def add_alert(self, symbol: str, op: str, price: float, note: str = "") -> int:
        if op not in ("above", "below"):
            raise ValueError("op must be 'above' or 'below'")
        return self._insert("alerts", {"symbol": symbol, "op": op, "price": float(price),
                                       "note": note, "created_ts": now_s()})

    def alerts(self, active: bool | None = None) -> list[dict]:
        if active is True:
            return self.rows("SELECT * FROM alerts WHERE fired_ts IS NULL ORDER BY id")
        if active is False:
            return self.rows("SELECT * FROM alerts WHERE fired_ts IS NOT NULL "
                             "ORDER BY fired_ts DESC")
        return self.rows("SELECT * FROM alerts ORDER BY id DESC")

    def fire_alert(self, alert_id: int, price: float) -> None:
        with self._db() as db:
            db.execute("UPDATE alerts SET fired_ts = ?, fired_px = ? WHERE id = ?",
                       (now_s(), price, alert_id))

    def delete_alert(self, alert_id: int) -> None:
        with self._db() as db:
            db.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
