"""Setups from the scan, ready to place with one tap.

``scan`` runs the scanner's fixed buy-setup rules (backend/screener/
buy_setups.py) and records every setup it finds in data_cache/trading.db,
with the trade it would make and every rule checked. It never places an
order. ``place`` places one recorded setup; only the owner's click (Trade
page) or command (`trade take ID`) calls it.

A setup is:
  ready    a fresh breakout ("buy now") that passes every rule right now
  waiting  near its line; it becomes ready when a later scan sees the break
  blocked  a rule fails (stop over 10%, margin, not on CoinDCX, ...)
  placed   you placed it; the same setup (coin, timeframe, pattern) is never
           offered again, and the coin rests ``cooldown_hours`` after any
           trade on it, including one you closed by hand
  expired  older than ``max_age_minutes``: the breakout is no longer fresh
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.trading import risk
from backend.trading.manager import TradeError, TradeManager

SOURCE = "scan"
READY, WAITING, BLOCKED, PLACED, EXPIRED, FAILED = (
    "ready", "waiting", "blocked", "placed", "expired", "failed")
HOUR_MS = 3_600_000


@dataclass(frozen=True)
class Settings:
    top: int = 50                  # coins scanned, by market cap
    leverage: int = risk.MAX_LEVERAGE
    cooldown_hours: float = 24.0   # rest a coin this long after any trade on it
    recheck_hours: float = 6.0     # record the same setup again after this long
    max_age_minutes: int = 120     # a ready setup older than this cannot be placed

    @classmethod
    def from_config(cls, raw: dict[str, Any] | None) -> "Settings":
        raw = raw or {}
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})


def find_setups(svc, top: int) -> pd.DataFrame:
    """The scanner's buy setups that pass its fixed rules, best first."""
    from backend.screener import buy_setups as bs
    from backend.screener import pattern_scan as ps

    fut = svc.futures()
    scan = ps.scan(fut.klines, svc.liquidation_coins(top), ["15m", "1h", "4h", "1d"],
                   patterns=ps.BULLISH + ps.BEARISH)
    trends = {}
    for sym in scan["symbol"].unique():
        try:
            trends[sym] = (bs.trend(fut.klines(sym, "1d", 300)["close"]),
                           bs.trend(fut.klines(sym, "4h", 300)["close"]))
        except Exception:
            trends[sym] = ("?", "?")
    return bs.pick(bs.rank(scan, trends), n=10)


def request_for(idea: dict, free_inr: float, settings: Settings) -> risk.TradeRequest:
    return risk.TradeRequest(pair=idea["pair"], side=risk.LONG, stop_loss=idea["stop"],
                             take_profit=idea["target"], risk_inr=0.0,
                             leverage=settings.leverage,
                             margin_inr=risk.margin_budget(free_inr))


def _gate(mgr: TradeManager, pair: str, timeframe: str, pattern: str,
          settings: Settings, now: int) -> str | None:
    """Why this setup may not be traded now (None = it may)."""
    if mgr.store.setup_placed(pair, timeframe, pattern):
        return "this setup was already traded"
    last = mgr.store.last_trade_ms(pair)
    if last and now - last < settings.cooldown_hours * HOUR_MS:
        return (f"{pair} had a trade in the last {settings.cooldown_hours:g}h "
                "(including one closed by hand)")
    return None


def scan(mgr: TradeManager, setups: pd.DataFrame, settings: Settings) -> list[dict]:
    """Record the setups and check each against every rule. Places nothing."""
    mgr.reconcile()                      # learn about stops, targets and hand closes first
    active = set(mgr.client.active_pairs())
    free = mgr.free_inr()
    now = int(time.time() * 1000)
    new: list[dict] = []
    for r in setups.itertuples(index=False):
        pair = risk.to_pair(r.coin)
        if mgr.store.idea_seen(SOURCE, pair, r.timeframe, r.pattern, r.kind,
                               now - int(settings.recheck_hours * HOUR_MS)):
            continue
        idea = dict(source=SOURCE, coin=r.coin, pair=pair, timeframe=r.timeframe,
                    pattern=r.pattern, kind=r.kind, price=float(r.price),
                    stop=float(r.down_level), target=float(r.target_up), rr=float(r.rr),
                    score=float(r.score))
        why = None if pair in active else "not an INR future on CoinDCX"
        why = why or _gate(mgr, pair, r.timeframe, r.pattern, settings, now)
        if why:
            status, reason = BLOCKED, why
        elif r.kind != "now":
            status, reason = WAITING, f"buy on a {r.timeframe} close above {r.up_level:g}"
        elif free is None:
            status, reason = BLOCKED, "no API keys"
        else:
            plan = mgr.preview(request_for(idea, free, settings))
            status = READY if plan.ok else BLOCKED
            reason = ("; ".join(plan.errors) if plan.errors else
                      f"{plan.qty:g} at ~{plan.entry:g}, lose ~Rs {plan.risk_inr:,.0f} at SL, "
                      f"make ~Rs {plan.reward_inr or 0:,.0f} at TP, margin Rs "
                      f"{plan.margin_inr:,.0f}")
        idea.update(status=status, reason=reason)
        idea["id"] = mgr.store.add_idea(**idea)
        new.append(idea)
        if status == READY:
            mgr.notify(f"setup ready: {r.coin} {r.timeframe} {r.pattern}, SL {idea['stop']:g}"
                       f" TP {idea['target']:g}. Tap Place on the Trade page.")
    return new


def place(mgr: TradeManager, idea_id: int, settings: Settings) -> int:
    """Place one recorded setup, re-checked at the current price. Returns the trade id."""
    idea = mgr.store.idea(idea_id)
    if idea is None:
        raise TradeError(f"no setup #{idea_id}")
    if idea["status"] != READY:
        raise TradeError(f"setup #{idea_id} is {idea['status']}, not ready")
    now = int(time.time() * 1000)
    if now - idea["ts_ms"] > settings.max_age_minutes * 60_000:
        mgr.store.update_idea(idea_id, status=EXPIRED,
                              reason=f"older than {settings.max_age_minutes} minutes")
        raise TradeError("this setup is too old; run a new scan")
    mgr.reconcile()
    why = _gate(mgr, idea["pair"], idea["timeframe"], idea["pattern"], settings, now)
    if why:
        mgr.store.update_idea(idea_id, status=BLOCKED, reason=why)
        raise TradeError(why)
    free = mgr.free_inr()
    if free is None:
        raise TradeError("no API keys")
    try:
        _, trade_id = mgr.open(request_for(idea, free, settings), confirm=idea["pair"])
    except TradeError as exc:
        mgr.store.update_idea(idea_id, status=FAILED, reason=str(exc)[:300])
        raise
    if mgr.live:
        mgr.store.update_idea(idea_id, status=PLACED, trade_id=trade_id)
    return trade_id
