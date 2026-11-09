"""PLAN: for every watchlist symbol where a *kept* rule fires on the last
closed daily candle, write a plan: buy-stop entry, stop and target. The
paper trader (paper.py) takes it from there.

One plan per symbol at a time: a symbol with a pending plan or an open
paper trade gets no new plan. Higher screen scores go first.
"""
from __future__ import annotations

import logging

from .data import DAY, DeskData, complete
from .rules import arrays, setup_at, with_indicators
from .settings import Settings
from .store import DeskStore

log = logging.getLogger(__name__)


def kept_rules(verdicts: list[dict]) -> dict[str, list[str]]:
    """market -> kept rules, best average R first."""
    out: dict[str, list[tuple[float, str]]] = {}
    for v in verdicts:
        if v["keep"]:
            out.setdefault(v["market"], []).append((v["w_exp"], v["rule"]))
    return {m: [r for _, r in sorted(rs, reverse=True)] for m, rs in out.items()}


def make_plans(settings: Settings, data: DeskData, store: DeskStore,
               screen_rows: list[dict], verdicts: list[dict],
               now: float | None = None) -> list[dict]:
    kept = kept_rules(verdicts)
    if not kept:
        return []
    busy = {p["symbol"] for p in store.plans("pending")} | \
           {t["symbol"] for t in store.trades("open")}
    limit = int(settings.paper["max_new_plans"])
    order_bars = int(settings.backtest["order_bars"])
    years = settings.backtest["years"] + 1
    new: list[dict] = []
    for row in sorted(screen_rows, key=lambda r: -r["score"]):
        if len(new) >= limit:
            break
        sym, market = row["symbol"], row["market"]
        if sym in busy or market not in kept:
            continue
        try:
            d = with_indicators(complete(data.history(sym, years), now))
        except Exception as exc:
            log.warning("plan: %s failed: %s", sym, exc)
            continue
        if d.empty:
            continue
        a = arrays(d)
        i = len(d) - 1
        for rule in kept[market]:
            s = setup_at(rule, a, i, float(settings.rules.get(rule, {}).get("target_r", 2)))
            if s is None:
                continue
            plan = {"symbol": sym, "market": market, "rule": rule, "entry": s.entry,
                    "stop": s.stop, "target": s.target,
                    "valid_from": int(a["time"][i]) + DAY, "order_bars": order_bars,
                    "score": row["score"], "note": ""}
            plan["id"] = store.add_plan(plan)
            busy.add(sym)
            new.append(plan)
            break
    return new
