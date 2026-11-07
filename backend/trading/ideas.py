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
PROPOSED = "proposed"           # a setup given by hand (`trade propose`), not by the scan
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


def find_setups(svc, top: int, coins: list[str] | None = None) -> pd.DataFrame:
    """The scanner's buy setups that pass its fixed rules, best first: over the
    ``top`` coins by market cap, or over ``coins`` when given (e.g. a recovery ledger)."""
    from backend.screener import buy_setups as bs
    from backend.screener import pattern_scan as ps

    fut = svc.futures()
    if coins:
        perps = fut.perpetuals()
        universe = {c: perps[c] for c in coins if c in perps}
    else:
        universe = svc.liquidation_coins(top)
    scan = ps.scan(fut.klines, universe, ["15m", "1h", "4h", "1d"],
                   patterns=ps.BULLISH + ps.BEARISH)
    trends = {}
    for sym in scan["symbol"].unique():
        try:
            trends[sym] = (bs.trend(fut.klines(sym, "1d", 300)["close"]),
                           bs.trend(fut.klines(sym, "4h", 300)["close"]))
        except Exception:
            trends[sym] = ("?", "?")
    return bs.pick(bs.rank(scan, trends), n=10)


def rr_error(plan: risk.Plan) -> str | None:
    """Gold-standard rule for suggestions: reward at least 2x risk, at the live price
    with fees in. Not lifted by the override (that is for size only)."""
    if plan.rr is None or plan.rr < risk.MIN_SUGGEST_RR:
        got = "no target" if plan.rr is None else f"{plan.rr:.2f}R"
        return (f"reward is under {risk.MIN_SUGGEST_RR:g}x the risk at the current price "
                f"({got}, fees in)")
    return None


def request_for(idea: dict, free_inr: float, settings: Settings) -> risk.TradeRequest:
    """The trade a setup makes. A scan setup: LONG at market, sized at the 5% margin
    budget. A proposed one carries its own side, risk, leverage and limit price."""
    limit = idea.get("limit_price")
    return risk.TradeRequest(pair=idea["pair"], side=idea.get("side") or risk.LONG,
                             stop_loss=idea["stop"], take_profit=idea["target"],
                             risk_inr=idea.get("risk_inr") or 0.0,
                             leverage=idea.get("leverage") or settings.leverage,
                             entry_type=risk.LIMIT if limit else risk.MARKET,
                             limit_price=limit or None,
                             margin_inr=0.0 if idea.get("risk_inr")
                             else risk.margin_budget(free_inr))


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
    # An expired ready setup must not hide the same setup for recheck_hours: expire it,
    # so a scan that still finds it records it again as a fresh one.
    mgr.store.expire_ideas(SOURCE, now - settings.max_age_minutes * 60_000,
                           f"older than {settings.max_age_minutes} minutes")
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
            errors = plan.errors + ([rr] if (rr := rr_error(plan)) else [])
            status = BLOCKED if errors else READY
            reason = ("; ".join(errors) if errors else
                      f"{plan.qty:g} at ~{plan.entry:g}, lose ~Rs {plan.risk_inr:,.0f} at SL, "
                      f"make ~Rs {plan.reward_inr or 0:,.0f} at TP, margin Rs "
                      f"{plan.margin_inr:,.0f}")
        idea.update(status=status, reason=reason)
        idea["id"] = mgr.store.add_idea(**idea)
        new.append(idea)
        if status == READY:
            _offer(mgr, idea, f"setup ready: {r.coin} {r.timeframe} {r.pattern}, "
                              f"SL {idea['stop']:g} TP {idea['target']:g}")
    return new


def _offer(mgr: TradeManager, idea: dict, text: str) -> None:
    """Send a ready setup to Telegram with a Place button (plain message without one)."""
    from backend.trading import tgbot

    if not tgbot.offer(mgr, idea, text):
        mgr.notify(f"{text}. Tap Place on the Trade page.")


def propose(mgr: TradeManager, req: risk.TradeRequest, *, timeframe: str, why: str,
            settings: Settings, send: bool = True) -> dict:
    """Record a setup found by hand (or by Claude in chat) and offer it with a Place
    button. Places nothing: only the owner's tap or `trade take ID` places it.
    ``send=False`` records it without the Place message (the SMC auto mode, which
    the owner switched on, places it itself)."""
    req.pair = risk.to_pair(req.pair)
    now = int(time.time() * 1000)
    plan = mgr.preview(req)
    errors = plan.errors + ([rr] if (rr := rr_error(plan)) else [])
    gate = _gate(mgr, req.pair, timeframe, "", settings, now)
    errors += [gate] if gate else []
    idea = dict(source=PROPOSED, coin=req.pair.removeprefix("B-").removesuffix("_USDT"),
                pair=req.pair, timeframe=timeframe, pattern=f"{PROPOSED}-{now}",
                kind="now", price=plan.entry, stop=plan.stop_loss,
                target=plan.take_profit or 0.0, rr=plan.rr or 0.0, score=0.0,
                side=req.side, risk_inr=req.risk_inr or None, leverage=req.leverage,
                limit_price=req.limit_price if req.entry_type == risk.LIMIT else None,
                status=BLOCKED if errors else READY,
                reason="; ".join(errors) if errors else why)
    idea["id"] = mgr.store.add_idea(**idea)
    if not errors and send:
        entry = f"limit {plan.entry:g}" if idea["limit_price"] else f"market ~{plan.entry:g}"
        _offer(mgr, idea, f"{req.side.upper()} {idea['coin']} ({timeframe}) {entry}, "
                          f"SL {plan.stop_loss:g} TP {plan.take_profit:g}, {plan.rr:.1f}R, "
                          f"risk ~Rs {plan.risk_inr:,.0f}\nWhy: {why}")
    return idea


def place(mgr: TradeManager, idea_id: int, settings: Settings, *,
          margin_inr: float | None = None, override: bool = False) -> int:
    """Place one recorded setup, re-checked at the current price. Returns the trade id.
    ``margin_inr`` / ``override``: a bigger trade the owner explicitly asked for."""
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
    req = request_for(idea, free, settings)
    if margin_inr:
        req.margin_inr = margin_inr
    req.override = override
    rr = rr_error(mgr.preview(req))
    if rr:
        mgr.store.update_idea(idea_id, status=BLOCKED, reason=rr)
        raise TradeError(rr)
    try:
        _, trade_id = mgr.open(req, confirm=idea["pair"])
    except TradeError as exc:
        mgr.store.update_idea(idea_id, status=FAILED, reason=str(exc)[:300])
        raise
    if mgr.live:
        mgr.store.update_idea(idea_id, status=PLACED, trade_id=trade_id)
    return trade_id
