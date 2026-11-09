"""Price alerts for any desk symbol: crypto (live) and stocks (~15 min delayed).

An alert fires once, when the last price is at or past its level. It is
checked on each tick, so a quick wick between two ticks can be missed.
"""
from __future__ import annotations

import logging

from backend.chart.symbols import parse

from .data import DeskData
from .notify import Sender, alert_card
from .paper import Event
from .store import DeskStore

log = logging.getLogger(__name__)


def add(store: DeskStore, symbol: str, op: str, price: float, note: str = "") -> int:
    return store.add_alert(parse(symbol).full, op, price, note)


def check(store: DeskStore, data: DeskData, sender: Sender | None = None) -> list[Event]:
    active = store.alerts(active=True)
    if not active:
        return []
    try:
        quotes = data.quotes(sorted({a["symbol"] for a in active}))
    except Exception as exc:
        log.warning("alert quotes failed: %s", exc)
        return []
    events = []
    for a in active:
        q = quotes.get(a["symbol"])
        if not q:
            continue
        last = float(q["last"])
        if (a["op"] == "above" and last >= a["price"]) or \
                (a["op"] == "below" and last <= a["price"]):
            store.fire_alert(a["id"], last)
            ev = Event("alert", a["symbol"], alert_card(a, last), {"alert": a, "last": last})
            events.append(ev)
            if sender:
                sender.send(ev.text)
    return events
