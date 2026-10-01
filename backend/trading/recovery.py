"""Spot-loss recovery ledger: futures on a coin win back what its spot holding lost.

One CSV per account (``data_cache/recovery_<account>.csv``, never committed) lists
the spot coins being recovered:

    coin, qty, paid_inr, since, status, note

``paid_inr`` is what the ``qty`` coins cost. ``recovery-init`` fills it from the
full spot trade history (average cost of the coins still held, USDT buys priced at
that day's USDT/INR rate); edit it by hand for coins bought elsewhere. ``since`` is
the day futures profit on the coin starts to count. ``status`` is ``active``,
``skip`` (cost unknown, not counted) or ``done`` (both legs closed).

A coin's ledger = (spot value now - paid) + futures P&L on its pair since ``since``
(closed trades, funding and fees, plus the open position if closed now). Once it
is at or above the cushion (TDS + spot fee on the final spot sell), close both.
Reads only: nothing here places or closes anything.
"""
from __future__ import annotations

import csv
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from backend.trading.client import MAIN, FuturesClient

ACTIVE, SKIP, DONE = "active", "skip", "done"
FIELDS = ("coin", "qty", "paid_inr", "since", "status", "note")
QUOTES = ("USDT", "INR", "BTC", "ETH", "USDC")
STABLES = ("USDT", "USDC")
CANDLES_URL = "https://public.coindcx.com/market_data/candles"
# CoinDCX gives only the last 1000 daily USDT/INR candles; older trades use a rough
# yearly rate. Only seeding uses these; the CSV is the record after that.
OLD_USDT_INR = {2019: 72.0, 2020: 76.0, 2021: 79.0, 2022: 84.0, 2023: 88.0}


def _f(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def ledger_path(data_dir: str, account: str = MAIN) -> Path:
    return Path(data_dir) / f"recovery_{account}.csv"


def coin_pair(coin: str) -> str:
    return f"B-{coin}_USDT"


@dataclass
class Row:
    coin: str
    qty: float
    paid_inr: float
    since: str            # YYYY-MM-DD
    status: str = ACTIVE
    note: str = ""


def load(path: Path) -> list[Row]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [Row(coin=r["coin"].strip().upper(), qty=_f(r["qty"]),
                    paid_inr=_f(r["paid_inr"]), since=r["since"].strip(),
                    status=(r.get("status") or ACTIVE).strip().lower(),
                    note=r.get("note") or "")
                for r in csv.DictReader(fh) if (r.get("coin") or "").strip()]


def save(path: Path, rows: list[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for r in rows:
            w.writerow([r.coin, f"{r.qty:.10g}", f"{r.paid_inr:.2f}", r.since, r.status, r.note])


# -- market data -----------------------------------------------------------------------
def spot_ticker(client: FuturesClient) -> dict[str, float]:
    return {t["market"]: _f(t.get("last_price"))
            for t in client._read("GET", "/exchange/ticker", signed=False)
            if _f(t.get("last_price"))}


def inr_price(coin: str, ticker: dict[str, float]) -> float | None:
    usdt = ticker.get("USDTINR", 0.0)
    if coin == "INR":
        return 1.0
    if coin in STABLES:
        return usdt or None
    if coin + "INR" in ticker:
        return ticker[coin + "INR"]
    if coin + "USDT" in ticker and usdt:
        return ticker[coin + "USDT"] * usdt
    return None


def spot_balances(client: FuturesClient) -> dict[str, float]:
    """coin -> free + locked spot quantity (coins with none left out)."""
    out = {}
    for b in client._read("POST", "/exchange/v1/users/balances", {}):
        q = _f(b.get("balance")) + _f(b.get("locked_balance"))
        if q > 0:
            out[b["currency"]] = q
    return out


def spot_trades(client: FuturesClient) -> list[dict]:
    """Every spot trade of the account, oldest first (CoinDCX pages by trade id)."""
    out: dict[int, dict] = {}
    from_id = 1                                  # CoinDCX wants a positive id
    while True:
        page = [t for t in client._read("POST", "/exchange/v1/orders/trade_history",
                                        {"limit": 500, "sort": "asc", "from_id": from_id})
                if int(t["id"]) not in out]
        if not page:
            return sorted(out.values(), key=lambda t: (t["timestamp"], int(t["id"])))
        out.update((int(t["id"]), t) for t in page)
        from_id = max(out)


def usdt_inr_history() -> dict[dt.date, float]:
    rows = httpx.get(CANDLES_URL, params={"pair": "I-USDT_INR", "interval": "1d",
                                          "limit": 1000}, timeout=30).json()
    return {dt.datetime.fromtimestamp(r["time"] / 1000, dt.timezone.utc).date(): _f(r["close"])
            for r in rows}


def rate_on(day: dt.date, history: dict[dt.date, float]) -> float:
    if history and day >= min(history):
        while day not in history:
            day -= dt.timedelta(days=1)
        return history[day]
    return OLD_USDT_INR.get(day.year, 88.0)


def split_symbol(symbol: str) -> tuple[str, str] | None:
    for q in QUOTES:
        if symbol.endswith(q) and len(symbol) > len(q):
            return symbol[: -len(q)], q
    return None


def cost_basis(trades: list[dict], usdt_hist: dict[dt.date, float],
               ticker: dict[str, float]) -> dict[str, tuple[float, float]]:
    """coin -> (quantity bought and still held, its INR cost). Average cost: a sell
    takes away its share of the cost. BTC/ETH-quoted trades use today's USDT price
    of the quote at that day's USDT/INR rate (rough; there are few)."""
    qty: dict[str, float] = defaultdict(float)
    cost: dict[str, float] = defaultdict(float)
    for t in trades:
        s = split_symbol(t["symbol"])
        if not s:
            continue
        base, quote = s
        if base in QUOTES:                       # USDTINR and the like: a currency swap
            continue
        day = dt.datetime.fromtimestamp(t["timestamp"] / 1000, dt.timezone.utc).date()
        rate = rate_on(day, usdt_hist)
        q_inr = (1.0 if quote == "INR" else rate if quote in STABLES
                 else ticker.get(quote + "USDT", 0.0) * rate)
        q = _f(t["quantity"])
        if t["side"] == "buy":
            qty[base] += q
            cost[base] += q * _f(t["price"]) * q_inr
        elif qty[base] > 0:
            cost[base] *= max(0.0, 1 - min(q, qty[base]) / qty[base])
            qty[base] = max(0.0, qty[base] - q)
    return {c: (qty[c], cost[c]) for c in qty if qty[c] > 0}


def seed(client: FuturesClient, *, min_paid_usd: float = 50.0, min_value_inr: float = 500.0,
         since: dt.date | None = None) -> list[Row]:
    """Ledger rows for the spot coins held now. A coin whose cost is under
    ``min_paid_usd`` is left out. Coins with no buy in the history (deposited) come in
    as ``skip`` when worth ``min_value_inr`` or more: set their cost to count them."""
    ticker = spot_ticker(client)
    usdt_now = ticker["USDTINR"]
    basis = cost_basis(spot_trades(client), usdt_inr_history(), ticker)
    day = (since or dt.date.today()).isoformat()
    rows = []
    for coin, held in sorted(spot_balances(client).items()):
        if coin == "INR" or coin in STABLES:
            continue
        price = inr_price(coin, ticker) or 0.0
        bought, cost = basis.get(coin, (0.0, 0.0))
        bought = min(bought, held)
        paid = cost * (bought / basis[coin][0]) if bought else 0.0
        if bought <= 0:
            if held * price >= min_value_inr:
                rows.append(Row(coin, held, held * price, day, SKIP,
                                "no buy in CoinDCX history: set paid_inr, then status active"))
            continue
        extra = held - bought
        note = ""
        if extra * price >= 1:
            paid += extra * price
            note = (f"{extra:.6g} of {held:.6g} have no buy in CoinDCX history; "
                    "costed at today's value - raise paid_inr if they cost more")
        if paid < min_paid_usd * usdt_now:
            continue
        rows.append(Row(coin, held, paid, day, ACTIVE, note))
    return rows


# -- the ledger --------------------------------------------------------------------------
@dataclass
class Line:
    coin: str
    status: str
    qty: float
    paid_inr: float
    spot_now_inr: float
    futures_closed_inr: float        # closed trades + funding - fees since `since`
    futures_open_inr: float          # open position, if closed at the mark price now
    cushion_inr: float
    has_futures: bool
    note: str = ""

    @property
    def spot_pnl_inr(self) -> float:
        return self.spot_now_inr - self.paid_inr

    @property
    def total_inr(self) -> float:
        return self.spot_pnl_inr + self.futures_closed_inr + self.futures_open_inr

    @property
    def to_go_inr(self) -> float:
        """Futures profit still needed before both legs can be closed."""
        return max(0.0, self.cushion_inr - self.total_inr)

    @property
    def ready(self) -> bool:
        return self.status == ACTIVE and self.total_inr >= self.cushion_inr


def transactions_since(client: FuturesClient, since_ms: float,
                       max_pages: int = 50) -> list[dict]:
    """Futures transactions (closes, funding, fees) at or after ``since_ms``."""
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        rows = client.transactions(page)
        out += [t for t in rows if _f(t.get("created_at")) >= since_ms]
        if len(rows) < 100 or min(_f(t.get("created_at")) for t in rows) < since_ms:
            break
    return out


def pnl_by_pair(txs: list[dict], since_ms: float) -> dict[str, float]:
    """pair -> INR P&L (amount - fee) of the transactions at or after ``since_ms``."""
    out: dict[str, float] = defaultdict(float)
    for t in txs:
        if _f(t.get("created_at")) >= since_ms:
            out[t.get("pair", "")] += _f(t.get("amount")) - _f(t.get("fee_amount"))
    return dict(out)


def open_pnl_inr(pos: dict) -> float:
    """Unrealised P&L of a position at its mark price, in INR at its settlement rate."""
    qty, avg, mark = _f(pos.get("active_pos")), _f(pos.get("avg_price")), _f(pos.get("mark_price"))
    rate = _f(pos.get("settlement_currency_avg_price"))
    return (mark - avg) * qty * rate if mark and avg and rate else 0.0


def day_ms(day: str) -> float:
    d = dt.date.fromisoformat(day)
    return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp() * 1000


def build(rows: list[Row], *, ticker: dict[str, float], held: dict[str, float],
          futures_pnl: dict[str, dict[str, float]], positions: list[dict],
          active_pairs: set[str], cushion_pct: float = 1.5) -> list[Line]:
    """Pure: ledger lines from the CSV rows and what the exchange shows now.
    ``futures_pnl`` maps a ``since`` day to the per-pair P&L from that day."""
    by_pair = {p["pair"]: p for p in positions if _f(p.get("active_pos"))}
    out = []
    for r in rows:
        pair = coin_pair(r.coin)
        qty = min(r.qty, held.get(r.coin, 0.0)) if r.status != DONE else r.qty
        # Fewer coins held than the ledger lists: count only their share of the cost.
        paid = r.paid_inr * qty / r.qty if r.qty else r.paid_inr
        price = inr_price(r.coin, ticker) or 0.0
        spot_now = qty * price
        closed = futures_pnl.get(r.since, {}).get(pair, 0.0)
        opened = open_pnl_inr(by_pair[pair]) if pair in by_pair else 0.0
        note = r.note
        if r.status != DONE and held.get(r.coin, 0.0) < r.qty * 0.999:
            note = (f"spot holds {held.get(r.coin, 0.0):.6g}, ledger says {r.qty:.6g}; "
                    + note).rstrip("; ")
        out.append(Line(r.coin, r.status, qty, paid, spot_now, closed, opened,
                        spot_now * cushion_pct / 100.0, pair in active_pairs, note))
    return out


def ledger(client: FuturesClient, rows: list[Row], cushion_pct: float = 1.5) -> list[Line]:
    """Read the exchange and build the ledger (reads only)."""
    days = sorted({r.since for r in rows if r.status != SKIP})
    txs = transactions_since(client, day_ms(days[0])) if days else []
    futures_pnl = {d: pnl_by_pair(txs, day_ms(d)) for d in days}
    return build(rows, ticker=spot_ticker(client), held=spot_balances(client),
                 futures_pnl=futures_pnl, positions=client.positions(),
                 active_pairs=set(client.active_pairs()), cushion_pct=cushion_pct)
