"""TRADE: the paper trader and its hard risk layer. Paper only.

Every tick it replays each pending plan and each open paper trade on the
daily candles since the plan started, with the same fill and exit rules as
the backtest (sim.py). So a paper trade is exactly a backtest trade, played
live. The candle that is still forming counts for fills, stops and targets.

Risk layer, checked when a plan fills (any "no" skips the plan):
  - risk per trade = risk_pct of equity; size capped at max_position_pct
  - at most max_open trades, max_per_market per market, one per symbol
  - all open risk together at most max_total_risk_pct of equity
  - at most max_new_per_day new trades per IST day
"""
from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import dataclass, field

import numpy as np

from .data import DAY, DeskData
from .notify import Sender, closed_card, open_card, skip_card
from .settings import Settings
from .sim import find_fill, manage, r_multiple
from .store import DeskStore

log = logging.getLogger(__name__)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


@dataclass
class Event:
    kind: str                 # open | close | skip | expire | missed | alert
    symbol: str
    text: str = ""
    data: dict = field(default_factory=dict)


class RiskLayer:
    def __init__(self, cfg: dict, store: DeskStore):
        self.cfg = cfg
        self.store = store

    def equity(self) -> float:
        closed = self.store.trades("closed", limit=100000)
        return float(self.cfg["start_equity"]) + sum(t["pnl"] or 0 for t in closed)

    def check(self, plan: dict, fill_px: float, now: float) -> tuple[bool, str, float, float]:
        """(ok, why, risk amount, position size) for filling ``plan`` at ``fill_px``."""
        cfg = self.cfg
        eq = self.equity()
        if eq <= 0:
            return False, "paper account is empty", 0.0, 0.0
        stop_dist = fill_px - plan["stop"]
        if stop_dist <= 0:
            return False, "filled at or under the stop", 0.0, 0.0
        risk_amt = eq * cfg["risk_pct"] / 100
        notional = risk_amt * fill_px / stop_dist
        cap = eq * cfg["max_position_pct"] / 100
        if notional > cap:
            notional = cap
            risk_amt = cap * stop_dist / fill_px
        open_ = self.store.trades("open")
        if any(t["symbol"] == plan["symbol"] for t in open_):
            return False, "a paper trade is already open on this symbol", 0.0, 0.0
        if len(open_) >= cfg["max_open"]:
            return False, f"{cfg['max_open']} trades already open", 0.0, 0.0
        if sum(t["market"] == plan["market"] for t in open_) >= cfg["max_per_market"]:
            return False, f"{cfg['max_per_market']} trades already open in this market", 0.0, 0.0
        open_risk = sum(t["risk_amt"] for t in open_)
        if open_risk + risk_amt > eq * cfg["max_total_risk_pct"] / 100 + 1e-9:
            return False, f"open risk would pass {cfg['max_total_risk_pct']}% of equity", 0.0, 0.0
        today = dt.datetime.fromtimestamp(now, IST).date()
        opened_today = sum(1 for t in self.store.trades(limit=200)
                           if dt.datetime.fromtimestamp(t["opened_ts"], IST).date() == today)
        if opened_today >= cfg["max_new_per_day"]:
            return False, f"{cfg['max_new_per_day']} new trades already today", 0.0, 0.0
        return True, "", float(risk_amt), float(notional)


def _ohlc(bars: list[dict]):
    return (np.array([b["open"] for b in bars], dtype=float),
            np.array([b["high"] for b in bars], dtype=float),
            np.array([b["low"] for b in bars], dtype=float),
            np.array([b["close"] for b in bars], dtype=float))


def tick(settings: Settings, data: DeskData, store: DeskStore,
         sender: Sender | None = None, now: float | None = None) -> list[Event]:
    now = time.time() if now is None else now
    cfg = settings.backtest
    slip = settings.slippage
    risk = RiskLayer(settings.paper, store)
    events: list[Event] = []

    for p in sorted(store.plans("pending"), key=lambda p: -(p["score"] or 0)):
        try:
            bars = data.recent(p["symbol"], p["valid_from"], now)
        except Exception as exc:
            log.warning("paper: candles for %s failed: %s", p["symbol"], exc)
            continue
        if not bars:
            continue
        o, h, _, _ = _ohlc(bars)
        n_complete = sum(1 for b in bars if b["time"] + DAY <= now)
        state, fill = find_fill(o, h, 0, p["entry"], p["target"], p["order_bars"], slip,
                                n_complete)
        if state == "pending":
            continue
        if state in ("expired", "missed"):
            store.set_plan_status(p["id"], state, "price ran past the target first"
                                  if state == "missed" else "entry not reached in time")
            events.append(Event(state, p["symbol"], data={"plan": p}))
            continue
        ok, why, risk_amt, notional = risk.check(p, fill.price, now)
        if not ok:
            store.set_plan_status(p["id"], "skipped", why)
            ev = Event("skip", p["symbol"], skip_card(p, why), {"plan": p, "why": why})
            events.append(ev)
            if sender:
                sender.send(ev.text)
            continue
        trade = {"plan_id": p["id"], "symbol": p["symbol"], "market": p["market"],
                 "rule": p["rule"], "entry": fill.price, "stop": p["stop"],
                 "target": p["target"], "fill_time": int(bars[fill.idx]["time"]),
                 "risk_amt": risk_amt, "notional": notional}
        trade["id"] = store.add_trade(trade)
        store.set_plan_status(p["id"], "filled")
        risk_pct = risk_amt / risk.equity() * 100
        ev = Event("open", p["symbol"], open_card(trade, risk_pct), {"trade": trade})
        events.append(ev)
        if sender:
            sender.send(ev.text)

    for t in store.trades("open"):
        try:
            bars = data.recent(t["symbol"], t["fill_time"], now)
        except Exception as exc:
            log.warning("paper: candles for %s failed: %s", t["symbol"], exc)
            continue
        if not bars or bars[0]["time"] != t["fill_time"]:
            continue
        o, h, lo, c = _ohlc(bars)
        n_complete = sum(1 for b in bars if b["time"] + DAY <= now)
        ex = manage(o, h, lo, c, 0, t["stop"], t["target"], int(cfg["max_hold"]), slip,
                    n_complete)
        if ex is None:
            continue
        r = r_multiple(t["entry"], t["stop"], ex.price, settings.fee(t["market"]))
        pnl = t["risk_amt"] * r
        store.close_trade(t["id"], exit_px=ex.price, exit_time=int(bars[ex.idx]["time"]),
                          why=ex.why, r=r, pnl=pnl)
        ev = Event("close", t["symbol"], closed_card(t, ex.price, ex.why, r, pnl, risk.equity()),
                   {"trade": t, "r": r, "pnl": pnl, "why": ex.why})
        events.append(ev)
        if sender:
            sender.send(ev.text)
    return events


def account(settings: Settings, store: DeskStore) -> dict:
    """Equity, open risk and the closed-trade record."""
    closed = store.trades("closed", limit=100000)
    open_ = store.trades("open")
    rs = [t["r"] for t in closed if t["r"] is not None]
    start = float(settings.paper["start_equity"])
    equity = start + sum(t["pnl"] or 0 for t in closed)
    return {"start": start, "equity": equity, "return_pct": (equity / start - 1) * 100,
            "closed": len(closed), "open": len(open_),
            "open_risk_pct": sum(t["risk_amt"] for t in open_) / equity * 100 if equity else 0,
            "win_rate": sum(r > 0 for r in rs) / len(rs) * 100 if rs else 0.0,
            "avg_r": sum(rs) / len(rs) if rs else 0.0, "total_r": sum(rs)}
