"""User-set price, trendline and zone alerts.

An alert watches one Binance USDT perpetual and fires once, the first time
its condition is met on a 1-minute candle after it was set (wicks count, so a
quick spike through a level is not missed between checks):

  price  above   the high reaches the level
         below   the low reaches the level
         touch   the candle trades through the level, from either side
         close_above / close_below   a CLOSED candle of the alert's timeframe
                 (1m .. 1d, e.g. a 15m close) closes above / below the level
  line   touch   the candle trades through the line (a straight line through
                 two (time, price) points, extended in time)
         break_up / break_down   a CLOSED candle closes above / below the line
  zone   enter   the candle trades inside [low, high]

Alerts live in SQLite so the dashboard and a background watcher can share
them; claiming a fired alert is a single UPDATE, so two checkers never send
the same alert twice.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

DEFAULT_DB = "data_cache/alerts.db"
PRICE, LINE, ZONE = "price", "line", "zone"
CONDITIONS = {
    PRICE: ("above", "below", "touch", "close_above", "close_below"),
    LINE: ("touch", "break_up", "break_down"),
    ZONE: ("enter",),
}
CONDITION_TEXT = {"above": "goes above", "below": "goes below", "touch": "touches",
                  "close_above": "closes above", "close_below": "closes below",
                  "break_up": "closes above", "break_down": "closes below",
                  "enter": "enters"}
# Conditions that wait for a candle to close; their candle size is the alert's
# timeframe. Wicks and zones always use 1-minute candles.
CLOSES = ("close_above", "close_below", "break_up", "break_down")
TIMEFRAMES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
ACTIVE, TRIGGERED = "active", "triggered"
MINUTE_MS = 60_000


@dataclass
class Alert:
    coin: str
    symbol: str
    kind: str                         # price | line | zone
    condition: str
    level: float | None = None        # price alerts
    t1: int | None = None             # line: first point (epoch ms, price)
    p1: float | None = None
    t2: int | None = None             # line: second point
    p2: float | None = None
    low: float | None = None          # zone
    high: float | None = None
    note: str = ""
    timeframe: str = "1m"             # candle whose close counts (CLOSES only)
    created_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    last_checked_ms: int | None = None
    status: str = ACTIVE
    triggered_ms: int | None = None
    trigger_price: float | None = None
    id: int | None = None

    def __post_init__(self):
        if self.kind not in CONDITIONS or self.condition not in CONDITIONS[self.kind]:
            raise ValueError(f"{self.kind!r} alerts take {CONDITIONS.get(self.kind)}")
        if self.kind == PRICE and self.level is None:
            raise ValueError("a price alert needs a level")
        if self.kind == LINE and None in (self.t1, self.p1, self.t2, self.p2):
            raise ValueError("a line alert needs two points")
        if self.kind == LINE and self.t1 == self.t2:
            raise ValueError("a line needs two different times")
        if self.kind == ZONE and (self.low is None or self.high is None):
            raise ValueError("a zone alert needs low and high")
        if self.timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {list(TIMEFRAMES)}")
        if self.condition not in CLOSES:
            self.timeframe = "1m"

    @property
    def bar_ms(self) -> int:
        return TIMEFRAMES[self.timeframe] * MINUTE_MS

    def line_at(self, t_ms: float) -> float:
        return self.p1 + (self.p2 - self.p1) * (t_ms - self.t1) / (self.t2 - self.t1)

    def target_now(self, now_ms: float | None = None) -> float:
        """The price the alert is waiting for right now (a zone: its middle)."""
        now_ms = now_ms if now_ms is not None else time.time() * 1000
        if self.kind == PRICE:
            return float(self.level)
        if self.kind == LINE:
            return float(self.line_at(now_ms))
        return (float(self.low) + float(self.high)) / 2

    def describe(self) -> str:
        what = {PRICE: f"price {_fmt(self.level)}",
                LINE: f"line (now {_fmt(self.target_now())})",
                ZONE: f"zone {_fmt(self.low)}–{_fmt(self.high)}"}[self.kind]
        text = f"{self.coin} {CONDITION_TEXT[self.condition]} {what}"
        if self.condition in CLOSES:
            text += f" on a {self.timeframe} close"
        return f"{text} · {self.note}" if self.note else text


def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}" if abs(v) >= 100 else f"{v:.6g}"


def evaluate(alert: Alert, candles: pd.DataFrame,
             now_ms: int | None = None) -> tuple[pd.Timestamp, float] | None:
    """First candle (of the alert's timeframe) at or after the alert's last
    check (or creation) that meets the condition: (candle time, price at the
    trigger). None if not.

    ``candles`` are oldest first, indexed by open time (UTC). The last one may
    still be forming: it counts for touches, never for closes.
    """
    if candles.empty:
        return None
    since = alert.last_checked_ms or alert.created_ms
    bar = alert.bar_ms
    start = pd.Timestamp(since - since % bar, unit="ms", tz="UTC")   # the candle it sat in
    df = candles[candles.index >= start]
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    for ts, c in df.iterrows():
        t = ts.value // 1_000_000                              # open time, ms
        closed = t + bar <= now_ms
        hi, lo, cl = float(c["high"]), float(c["low"]), float(c["close"])
        if alert.kind == PRICE:
            lv = float(alert.level)
            if alert.condition == "above" and hi >= lv:
                return ts, lv
            if alert.condition == "below" and lo <= lv:
                return ts, lv
            if alert.condition == "touch" and lo <= lv <= hi:
                return ts, lv
            if alert.condition == "close_above" and closed and cl > lv:
                return ts, cl
            if alert.condition == "close_below" and closed and cl < lv:
                return ts, cl
        elif alert.kind == LINE:
            lv = alert.line_at(t + bar / 2)
            if alert.condition == "touch" and lo <= lv <= hi:
                return ts, lv
            if alert.condition == "break_up" and closed and cl > lv:
                return ts, cl
            if alert.condition == "break_down" and closed and cl < lv:
                return ts, cl
        elif alert.kind == ZONE:
            if hi >= alert.low and lo <= alert.high:
                return ts, min(max(cl, alert.low), alert.high)
    return None


def already_met(alert: Alert, price: float) -> bool:
    """True if the alert would fire at once at ``price`` (warn when setting it)."""
    target = alert.target_now()
    if alert.kind == ZONE:
        return alert.low <= price <= alert.high
    return (alert.condition in ("above", "close_above", "break_up") and price >= target) or \
           (alert.condition in ("below", "close_below", "break_down") and price <= target)


# -- storage --------------------------------------------------------------------
_COLUMNS = [f for f in Alert.__dataclass_fields__ if f != "id"]
_TEXT = ("coin", "symbol", "kind", "condition", "note", "timeframe", "status")


def _sql_type(column: str) -> str:
    return "TEXT" if column in _TEXT else "REAL"


class AlertStore:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            cols = ", ".join(f"{c} {_sql_type(c)}" for c in _COLUMNS)
            con.execute(f"CREATE TABLE IF NOT EXISTS alerts "
                        f"(id INTEGER PRIMARY KEY AUTOINCREMENT, {cols})")
            have = {r["name"] for r in con.execute("PRAGMA table_info(alerts)")}
            for c in _COLUMNS:                  # alerts.db from an older version
                if c not in have:
                    default = " DEFAULT '1m'" if c == "timeframe" else ""
                    con.execute(f"ALTER TABLE alerts ADD COLUMN {c} {_sql_type(c)}{default}")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        # One short connection per call, committed and closed: the dashboard's
        # threads and a background watcher all use the same file.
        con = sqlite3.connect(str(self.path), timeout=10)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    @staticmethod
    def _to_alert(row: sqlite3.Row) -> Alert:
        d = dict(row)
        for k in ("t1", "t2", "created_ms", "last_checked_ms", "triggered_ms"):
            if d.get(k) is not None:
                d[k] = int(d[k])
        d["timeframe"] = d.get("timeframe") or "1m"
        return Alert(**d)

    def add(self, alert: Alert) -> int:
        d = asdict(alert)
        d.pop("id")
        with self._conn() as con:
            cur = con.execute(f"INSERT INTO alerts ({', '.join(_COLUMNS)}) VALUES "
                              f"({', '.join('?' for _ in _COLUMNS)})",
                              [d[c] for c in _COLUMNS])
            return int(cur.lastrowid)

    def list(self, status: str | None = None) -> list[Alert]:
        sql = "SELECT * FROM alerts" + (" WHERE status = ?" if status else "")
        sql += " ORDER BY id DESC"
        with self._conn() as con:
            rows = con.execute(sql, (status,) if status else ()).fetchall()
        return [self._to_alert(r) for r in rows]

    def delete(self, alert_id: int) -> None:
        with self._conn() as con:
            con.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))

    def rearm(self, alert_id: int) -> None:
        now = int(time.time() * 1000)
        with self._conn() as con:
            con.execute("UPDATE alerts SET status = ?, triggered_ms = NULL, "
                        "trigger_price = NULL, last_checked_ms = ? WHERE id = ?",
                        (ACTIVE, now, alert_id))

    def mark_checked(self, alert_id: int, now_ms: int) -> None:
        with self._conn() as con:
            con.execute("UPDATE alerts SET last_checked_ms = ? WHERE id = ? AND "
                        "status = ?", (now_ms, alert_id, ACTIVE))

    def claim(self, alert_id: int, when_ms: int, price: float) -> bool:
        """Mark fired. True only for the one caller that flipped it, so an alert
        seen by two checkers at once is still sent once."""
        with self._conn() as con:
            cur = con.execute("UPDATE alerts SET status = ?, triggered_ms = ?, "
                              "trigger_price = ? WHERE id = ? AND status = ?",
                              (TRIGGERED, when_ms, price, alert_id, ACTIVE))
            return cur.rowcount == 1

    def fired_since(self, since_ms: int) -> list[Alert]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM alerts WHERE status = ? AND "
                               "triggered_ms >= ? ORDER BY triggered_ms DESC",
                               (TRIGGERED, since_ms)).fetchall()
        return [self._to_alert(r) for r in rows]


# -- checking -------------------------------------------------------------------
def check_all(store: AlertStore, fetch: Callable[[str, str, int], pd.DataFrame],
              notify: Callable[[Alert], None] | None = None,
              now_ms: int | None = None) -> list[Alert]:
    """Check every active alert once; returns the ones that fired now.

    ``fetch(symbol, timeframe, limit)`` returns candles, oldest first; one
    call per symbol and timeframe in use (usually just "1m").
    """
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    active = store.list(ACTIVE)
    groups: dict[tuple[str, str], list[Alert]] = {}
    for a in active:
        groups.setdefault((a.symbol, a.timeframe), []).append(a)
    fired: list[Alert] = []
    for (symbol, tf), alerts in groups.items():
        oldest = min(a.last_checked_ms or a.created_ms for a in alerts)
        limit = int(min(1000, max(3, (now_ms - oldest) // alerts[0].bar_ms + 3)))
        try:
            candles = fetch(symbol, tf, limit)
        except Exception:
            continue                          # try again next round
        for a in alerts:
            hit = evaluate(a, candles, now_ms)
            if hit is None:
                store.mark_checked(a.id, now_ms)
                continue
            ts, price = hit
            when = ts.value // 1_000_000
            if store.claim(a.id, when, price):
                a.status, a.triggered_ms, a.trigger_price = TRIGGERED, when, price
                fired.append(a)
                if notify:
                    try:
                        notify(a)
                    except Exception:
                        pass                  # a failed message must not stop checks
    return fired


def message(a: Alert) -> str:
    when = pd.Timestamp(a.triggered_ms, unit="ms", tz="UTC").strftime("%b %d %H:%M UTC") \
        if a.triggered_ms else ""
    return f"🔔 {a.describe()} — hit {_fmt(a.trigger_price)} at {when}"
