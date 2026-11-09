"""The desk's database: SQLite on the laptop, or Postgres on Supabase.

  DeskStore("data_cache/market_desk.db")        a local SQLite file
  DeskStore("postgresql://desk_writer...")      the Supabase project; its
                                                tables are made once by
                                                market_desk/sql/setup.py

The same SQL runs on both (written with ``?`` marks; Postgres gets ``%s``).
Times are UTC epoch seconds.
"""
from __future__ import annotations

import logging
import math
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

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
CREATE TABLE IF NOT EXISTS heatmap (
  ts INTEGER, market TEXT, grp TEXT, label TEXT, symbol TEXT, last REAL,
  chg_1d REAL, chg_1w REAL, chg_1m REAL);
CREATE TABLE IF NOT EXISTS quotes (
  symbol TEXT PRIMARY KEY, last REAL, change_pct REAL, ts INTEGER);
"""


def now_s() -> int:
    return int(time.time())


def _clean(v):
    """numpy scalars -> Python; NaN -> NULL (as SQLite stores it)."""
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


class _Conn:
    """One connection, either kind, taking ``?`` SQL."""

    def __init__(self, raw, pg: bool):
        self.raw, self.pg = raw, pg

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.pg else sql

    def execute(self, sql: str, params: tuple = ()):
        return self.raw.execute(self._sql(sql), tuple(_clean(p) for p in params))

    def executemany(self, sql: str, seq: list[tuple]) -> None:
        seq = [tuple(_clean(p) for p in row) for row in seq]
        if self.pg:
            with self.raw.cursor() as cur:
                cur.executemany(self._sql(sql), seq)
        else:
            self.raw.executemany(sql, seq)


class DeskStore:
    def __init__(self, target: str | Path):
        self.pg = isinstance(target, str) and target.startswith(("postgres://", "postgresql://"))
        self._lock = threading.Lock()
        self._pg_raw = None
        self._pg_used = 0.0
        if self.pg:
            self.url = target
            self.path = None
            self.where = "Supabase"
        else:
            self.path = Path(target)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.where = str(self.path)
            with self._db() as db:
                db.raw.executescript(SCHEMA)

    # --- connections ---------------------------------------------------------
    def _pg_conn(self):
        import psycopg
        from psycopg.rows import dict_row
        c = self._pg_raw
        if c is not None and (c.closed or c.broken):
            c = None
        if c is not None and time.time() - self._pg_used > 60:
            try:                       # the pooler drops idle connections
                c.execute("SELECT 1")
                c.commit()
            except psycopg.Error:
                c = None
        if c is None:
            # The desk logins have search_path = desk (set by sql/setup.py).
            c = psycopg.connect(self.url, row_factory=dict_row, connect_timeout=15)
            self._pg_raw = c
        self._pg_used = time.time()
        return c

    @contextmanager
    def _db(self) -> Iterator[_Conn]:
        if self.pg:
            with self._lock:
                raw = self._pg_conn()
                try:
                    yield _Conn(raw, True)
                    raw.commit()
                except BaseException:
                    try:
                        raw.rollback()
                    except Exception:          # a dead connection: reconnect next time
                        self._pg_raw = None
                    raise
            return
        raw = sqlite3.connect(self.path, timeout=30)
        raw.row_factory = sqlite3.Row
        try:
            yield _Conn(raw, False)
            raw.commit()
        finally:
            raw.close()

    def rows(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._db() as db:
            return [dict(r) for r in db.execute(sql, params).fetchall()]

    def _insert(self, table: str, row: dict) -> int:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._db() as db:
            cur = db.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks}) RETURNING id",
                             tuple(row.values()))
            got = cur.fetchone()
            return int(got["id"] if isinstance(got, dict) else got[0])

    def _insert_many(self, table: str, rows: list[dict], db: _Conn | None = None) -> None:
        if not rows:
            return
        cols = list(rows[0])
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        if db is not None:
            db.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
            return
        with self._db() as db2:
            db2.executemany(sql, [tuple(r[c] for c in cols) for r in rows])

    # --- meta ----------------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        rows = self.rows("SELECT value FROM meta WHERE key = ?", (key,))
        return rows[0]["value"] if rows else default

    def set_meta(self, key: str, value: str) -> None:
        with self._db() as db:
            db.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # --- backtests -----------------------------------------------------------
    def _trim(self, db: _Conn, table: str, keep: int) -> None:
        db.execute(f"DELETE FROM {table} WHERE run_ts NOT IN (SELECT DISTINCT run_ts "
                   f"FROM {table} ORDER BY run_ts DESC LIMIT {int(keep)})")

    def save_backtest(self, run_ts: int, verdicts: list[dict], symbols: list[dict]) -> None:
        with self._db() as db:
            self._insert_many("verdicts", [{"run_ts": run_ts, **v} for v in verdicts], db)
            self._insert_many("bt_symbols", [{"run_ts": run_ts, **s} for s in symbols], db)
            for table in ("verdicts", "bt_symbols"):   # keep the last 30 runs
                self._trim(db, table, 30)

    def _latest(self, table: str) -> list[dict]:
        return self.rows(f"SELECT * FROM {table} WHERE run_ts = "
                         f"(SELECT MAX(run_ts) FROM {table})")

    def latest_verdicts(self) -> list[dict]:
        return self._latest("verdicts")

    def latest_bt_symbols(self) -> list[dict]:
        return self._latest("bt_symbols")

    # --- screen --------------------------------------------------------------
    def save_screen(self, run_ts: int, rows: list[dict]) -> None:
        with self._db() as db:
            self._insert_many("screens", [{"run_ts": run_ts, **r} for r in rows], db)
            self._trim(db, "screens", 60)

    def latest_screen(self) -> list[dict]:
        return sorted(self._latest("screens"), key=lambda r: -r["score"])

    # --- plans and paper trades ----------------------------------------------
    def add_plan(self, plan: dict) -> int:
        plan = {k: v for k, v in plan.items() if k != "id"}
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
        trade = {k: v for k, v in trade.items() if k != "id"}
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
                cur = db.execute("INSERT INTO news (link, symbol, ts, source, title, tone) "
                                 "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                                 (r["link"], r["symbol"], r["ts"], r["source"], r["title"],
                                  r["tone"]))
                added += max(cur.rowcount, 0)
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

    # --- heatmap and quotes (written by the server, read by the cloud page) --
    def save_heatmap(self, ts: int, rows: list[dict]) -> None:
        with self._db() as db:
            db.execute("DELETE FROM heatmap")
            self._insert_many("heatmap", [
                {"ts": ts, "market": r["market"], "grp": r["group"], "label": r["label"],
                 "symbol": r["symbol"], "last": r["last"], "chg_1d": r["chg_1d"],
                 "chg_1w": r["chg_1w"], "chg_1m": r["chg_1m"]} for r in rows], db)

    def heatmap(self, market: str | None = None) -> list[dict]:
        sql = "SELECT ts, market, grp AS \"group\", label, symbol, last, chg_1d, chg_1w, " \
              "chg_1m FROM heatmap"
        return self.rows(sql + " WHERE market = ?", (market,)) if market else self.rows(sql)

    def save_quotes(self, quotes: dict[str, dict], ts: int | None = None) -> None:
        ts = now_s() if ts is None else ts
        with self._db() as db:
            for sym, q in quotes.items():
                db.execute("INSERT INTO quotes (symbol, last, change_pct, ts) VALUES (?, ?, ?, ?) "
                           "ON CONFLICT(symbol) DO UPDATE SET last = excluded.last, "
                           "change_pct = excluded.change_pct, ts = excluded.ts",
                           (sym, q.get("last"), q.get("change_pct"), ts))

    def quotes(self) -> dict[str, dict]:
        return {r["symbol"]: r for r in self.rows("SELECT * FROM quotes")}

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
