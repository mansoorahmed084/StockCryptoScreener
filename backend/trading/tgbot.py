"""Place setups from Telegram: a Place button on each ready setup, then Confirm.

A ready setup (from the scan, or one given with `trade propose`) is sent to the
owner's Telegram chat with a **Place** button. Tapping it re-checks the trade at
the current price and shows the fresh plan with **Confirm** and **Skip**. Confirm
(within ``CONFIRM_S`` seconds) places it through ``ideas.place`` — the same path,
rules and checks as the Trade page and `trade take`. Nothing is placed without the
owner's two taps, and taps from any other chat are ignored.

The listener runs inside `trade bot`, long-polling Telegram for button taps.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from backend.alerts.telegram import telegram_from_env
from backend.trading import ideas
from backend.trading.manager import TradeError, TradeManager

log = logging.getLogger(__name__)

CONFIRM_S = 120          # a Confirm button older than this asks for a fresh Place
PLACE, CONFIRM, SKIP = "p", "c", "x"


def offer(mgr: TradeManager, idea: dict, text: str) -> bool:
    """Send a ready setup with a Place button. False when Telegram is not set up."""
    tg = telegram_from_env()
    if tg is None:
        return False
    mid = tg.send_buttons(f"[{mgr.account}] {text}\nsetup #{idea['id']}",
                          [("Place", f"{PLACE}|{mgr.account}|{idea['id']}")])
    if mid:
        mgr.store.update_idea(idea["id"], tg_message_id=mid)
    return bool(mid)


class Listener:
    """Handles the owner's button taps for every account it is given."""

    def __init__(self, managers: dict[str, TradeManager], settings: ideas.Settings,
                 tg: Any = None, clock=time.time):
        self.managers = managers
        self.settings = settings
        self.tg = tg or telegram_from_env()
        self.clock = clock
        self.offset: int | None = None

    def poll(self, timeout: int = 20) -> list[str]:
        """Wait up to ``timeout`` s for taps and handle them; what happened, for the log."""
        out = []
        for u in self.tg.updates(self.offset, timeout):
            self.offset = u["update_id"] + 1
            cq = u.get("callback_query")
            if cq:
                try:
                    out.append(self.handle(cq))
                except Exception as exc:          # one bad tap never stops the bot
                    log.exception("button tap failed")
                    out.append(f"tap failed: {exc}")
        return out

    def handle(self, cq: dict) -> str:
        msg = cq.get("message") or {}
        chat = str((msg.get("chat") or {}).get("id", ""))
        if chat != str(self.tg.chat_id):
            self.tg.answer(cq["id"], "not allowed")
            return f"ignored a tap from chat {chat}"
        parts = str(cq.get("data", "")).split("|")
        action, account, idea_id = parts[0], parts[1], int(parts[2])
        mgr = self.managers.get(account)
        mid = msg.get("message_id")
        if mgr is None:
            self.tg.answer(cq["id"], f"account {account} is not watched by this bot")
            return f"tap for unwatched account {account}"
        idea = mgr.store.idea(idea_id)
        if idea is None:
            self.tg.answer(cq["id"], "unknown setup")
            return f"unknown setup #{idea_id}"
        tag = f"[{account}] #{idea_id} {idea['coin']}"

        if action == SKIP:
            mgr.store.update_idea(idea_id, status=ideas.EXPIRED, reason="skipped by you")
            self.tg.answer(cq["id"], "skipped")
            self.tg.edit(mid, f"{tag}: skipped.")
            return f"{tag}: skipped"

        if action == PLACE:
            text, buttons = self._fresh_plan(mgr, idea)
            self.tg.answer(cq["id"])
            self.tg.edit(mid, f"{tag}\n{text}", buttons)
            return f"{tag}: plan shown" + ("" if buttons else " (blocked)")

        if action == CONFIRM:
            sent = int(parts[3])
            if self.clock() - sent > CONFIRM_S:
                self.tg.answer(cq["id"], "too old: tap Place again")
                self.tg.edit(mid, f"{tag}: the confirm button expired. Tap Place for a "
                                  "fresh price.", [("Place", f"{PLACE}|{account}|{idea_id}")])
                return f"{tag}: confirm expired"
            self.tg.answer(cq["id"], "placing...")
            try:
                with mgr.lock:
                    trade_id = ideas.place(mgr, idea_id, self.settings)
            except TradeError as exc:
                self.tg.edit(mid, f"{tag}: refused - {exc}")
                return f"{tag}: refused - {exc}"
            word = "placed" if mgr.live else "dry run, nothing sent"
            self.tg.edit(mid, f"{tag}: {word}, trade #{trade_id}. Stop and target are on "
                              "the exchange; the bot trails the stop.")
            return f"{tag}: {word}, trade #{trade_id}"
        self.tg.answer(cq["id"], "unknown button")
        return f"{tag}: unknown button {action!r}"

    def _fresh_plan(self, mgr: TradeManager, idea: dict) -> tuple[str, list | None]:
        """The trade re-sized at the current price, and the Confirm/Skip buttons
        (None when it may not be placed now)."""
        if idea["status"] != ideas.READY:
            return f"this setup is {idea['status']}: {idea['reason']}", None
        age_ms = self.clock() * 1000 - idea["ts_ms"]
        if age_ms > self.settings.max_age_minutes * 60_000:
            mgr.store.update_idea(idea["id"], status=ideas.EXPIRED,
                                  reason=f"older than {self.settings.max_age_minutes} minutes")
            return "this setup is too old now.", None
        free = mgr.free_inr()
        if free is None:
            return "no API keys for this account.", None
        plan = mgr.preview(ideas.request_for(idea, free, self.settings))
        rr = ideas.rr_error(plan)
        text = f"{'LIVE' if mgr.live else 'DRY RUN'}\n{plan.summary()}"
        if not plan.ok or rr:
            return text + (f"\n  BLOCKED: {rr}" if rr else ""), None
        a, i, now = mgr.account, idea["id"], int(self.clock())
        return (text + f"\nConfirm within {CONFIRM_S // 60} minutes.",
                [("Confirm", f"{CONFIRM}|{a}|{i}|{now}"), ("Skip", f"{SKIP}|{a}|{i}")])
