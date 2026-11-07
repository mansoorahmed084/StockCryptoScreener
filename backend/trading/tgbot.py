"""Place setups from Telegram: a Place button on each ready setup, then Confirm.

A ready setup (from the scan, or one given with `trade propose`) is sent to the
owner's Telegram chat with a **Place** button. Tapping it re-checks the trade at
the current price and shows the fresh plan with **Confirm** and **Skip**. Confirm
(within ``CONFIRM_S`` seconds) places it through ``ideas.place`` — the same path,
rules and checks as the Trade page and `trade take`. Nothing is placed without the
owner's two taps, and taps from any other chat are ignored.

The listener runs inside `trade bot`, long-polling Telegram for button taps and
the owner's text commands (tgcmd: /positions, /pnl, /close COIN, /help). A
/close closes nothing by itself: it answers with a **Close it** button, and
only that tap (within ``CONFIRM_S``) closes the position.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from backend.alerts.telegram import telegram_from_env
from backend.trading import ideas, tgcmd, tgfmt
from backend.trading.tgfmt import esc
from backend.trading.manager import TradeError, TradeManager

log = logging.getLogger(__name__)

CONFIRM_S = 120          # a Confirm (or Close) button older than this asks again
PLACE, CONFIRM, SKIP = "p", "c", "x"
CLOSE, KEEP = "k", "n"   # the buttons of the owner's /close command
UPDATES = ("callback_query", "message")


def offer(mgr: TradeManager, idea: dict, text: str) -> bool:
    """Send a ready setup with a Place button. False when Telegram is not set up."""
    tg = telegram_from_env()
    if tg is None:
        return False
    why = (idea.get("reason") if idea.get("source") == ideas.PROPOSED
           else f"{idea.get('pattern')} ({idea.get('timeframe')}, scanner)")
    mid = tg.send_buttons(tgfmt.idea_card(idea, mgr.account, why or ""),
                          [("Place", f"{PLACE}|{mgr.account}|{idea['id']}")], html=True)
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
        self._menu_set = False

    def poll(self, timeout: int = 20) -> list[str]:
        """Wait up to ``timeout`` s for taps and commands and handle them; what
        happened, for the log."""
        if not self._menu_set and hasattr(self.tg, "set_commands"):
            self._menu_set = True
            try:
                self.tg.set_commands(tgcmd.COMMANDS)
            except Exception as exc:              # the menu is a nicety
                log.warning("setting the command menu failed: %s", exc)
        out = []
        for u in self.tg.updates(self.offset, timeout, allowed=UPDATES):
            self.offset = u["update_id"] + 1
            cq, msg = u.get("callback_query"), u.get("message")
            try:
                if cq:
                    out.append(self.handle(cq))
                elif msg:
                    out.append(self.command(msg))
            except Exception as exc:              # one bad tap or command never stops the bot
                log.exception("telegram update failed")
                out.append(f"update failed: {exc}")
                if msg and self._owner(msg):
                    self.tg.send_text(f"⛔ That failed: {esc(exc)}", html=True)
        return out

    def _owner(self, msg: dict) -> bool:
        return str((msg.get("chat") or {}).get("id", "")) == str(self.tg.chat_id)

    def command(self, msg: dict) -> str:
        """A text command from the owner's chat (tgcmd). Other chats get no answer."""
        chat = str((msg.get("chat") or {}).get("id", ""))
        if not self._owner(msg):
            return f"ignored a message from chat {chat}"
        cmd, answer = tgcmd.reply_for(self.managers, msg.get("text") or "")
        if cmd == "close" and not isinstance(answer, str):
            mgr, pos = answer
            pair, now = pos["pair"], int(self.clock())
            self.tg.send_buttons(tgcmd.close_prompt(mgr, pos), html=True, buttons=[
                ("Close it", f"{CLOSE}|{mgr.account}|{pair}|{now}"),
                ("Cancel", f"{KEEP}|{mgr.account}|{pair}")])
            return f"/close {pair} on {mgr.account}: asked to confirm"
        self.tg.send_text(answer, html=True)
        return f"/{cmd} answered"

    def _close_tap(self, cq: dict, parts: list[str]) -> str:
        """The Close it / Cancel buttons of a /close command."""
        action, account, pair = parts[0], parts[1], parts[2]
        mid = (cq.get("message") or {}).get("message_id")
        mgr = self.managers.get(account)
        if mgr is None:
            self.tg.answer(cq["id"], f"account {account} is not watched by this bot")
            return f"close tap for unwatched account {account}"
        tag = f"[{account}] {tgcmd.coin(pair)}"
        c = esc(tgcmd.coin(pair))
        if action == KEEP:
            self.tg.answer(cq["id"], "kept")
            self.tg.edit(mid, f"↩️ <b>{c} kept open.</b> Nothing was sent.", html=True)
            return f"{tag}: close cancelled"
        if self.clock() - int(parts[3]) > CONFIRM_S:
            self.tg.answer(cq["id"], "too old")
            self.tg.edit(mid, f"⌛ <b>That Close button expired.</b>\nSend /close {c} again.",
                         html=True)
            return f"{tag}: close expired"
        self.tg.answer(cq["id"], "closing...")
        try:
            with mgr.lock:
                mgr.close(pair, confirm=pair)
        except TradeError as exc:
            self.tg.edit(mid, f"⛔ <b>{c} not closed</b>\n{esc(exc)}", html=True)
            return f"{tag}: close refused - {exc}"
        word = "closed at market" if mgr.live else "dry run, nothing sent"
        self.tg.edit(mid, f"✅ <b>{c} {word}.</b>\nIts stop and target orders were cancelled. "
                          "The CLOSED message with the result follows." if mgr.live else
                          f"🧪 <b>{c}: dry run, nothing sent.</b>", html=True)
        return f"{tag}: {word} (owner's /close)"

    def handle(self, cq: dict) -> str:
        msg = cq.get("message") or {}
        chat = str((msg.get("chat") or {}).get("id", ""))
        if chat != str(self.tg.chat_id):
            self.tg.answer(cq["id"], "not allowed")
            return f"ignored a tap from chat {chat}"
        parts = str(cq.get("data", "")).split("|")
        if parts[0] in (CLOSE, KEEP):
            return self._close_tap(cq, parts)
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
            self.tg.edit(mid, f"⏭️ <b>Skipped:</b> {esc(idea['coin'])} setup #{idea_id}",
                         html=True)
            return f"{tag}: skipped"

        if action == PLACE:
            text, buttons = self._fresh_plan(mgr, idea)
            self.tg.answer(cq["id"])
            self.tg.edit(mid, text, buttons, html=True)
            return f"{tag}: plan shown" + ("" if buttons else " (blocked)")

        if action == CONFIRM:
            sent = int(parts[3])
            if self.clock() - sent > CONFIRM_S:
                self.tg.answer(cq["id"], "too old: tap Place again")
                self.tg.edit(mid, "⌛ <b>The Confirm button expired.</b>\nTap Place for a "
                                  "fresh price.", [("Place", f"{PLACE}|{account}|{idea_id}")],
                             html=True)
                return f"{tag}: confirm expired"
            self.tg.answer(cq["id"], "placing...")
            try:
                with mgr.lock:
                    trade_id = ideas.place(mgr, idea_id, self.settings)
            except TradeError as exc:
                self.tg.edit(mid, f"⛔ <b>Not placed:</b> {esc(idea['coin'])} setup "
                                  f"#{idea_id}\n{esc(exc)}", html=True)
                return f"{tag}: refused - {exc}"
            word = "placed" if mgr.live else "dry run, nothing sent"
            c = esc(idea["coin"])
            self.tg.edit(mid, (f"✅ <b>Placed:</b> {c} setup #{idea_id} → trade #{trade_id}\n"
                               "Stop and target are on CoinDCX. The OPEN message follows.")
                         if mgr.live else
                         f"🧪 <b>Dry run:</b> {c} setup #{idea_id}, nothing sent "
                         f"(trade #{trade_id})", html=True)
            return f"{tag}: {word}, trade #{trade_id}"
        self.tg.answer(cq["id"], "unknown button")
        return f"{tag}: unknown button {action!r}"

    def _fresh_plan(self, mgr: TradeManager, idea: dict) -> tuple[str, list | None]:
        """The trade re-sized at the current price, and the Confirm/Skip buttons
        (None when it may not be placed now)."""
        if idea["status"] != ideas.READY:
            return (f"⛔ <b>This setup is {esc(idea['status'])}</b>\n"
                    f"{esc(idea['reason'])}"), None
        age_ms = self.clock() * 1000 - idea["ts_ms"]
        if age_ms > self.settings.max_age_minutes * 60_000:
            mgr.store.update_idea(idea["id"], status=ideas.EXPIRED,
                                  reason=f"older than {self.settings.max_age_minutes} minutes")
            return "⌛ <b>This setup is too old now.</b>", None
        free = mgr.free_inr()
        if free is None:
            return "⛔ <b>No API keys for this account.</b>", None
        plan = mgr.preview(ideas.request_for(idea, free, self.settings))
        rr = ideas.rr_error(plan)
        text = tgfmt.plan_card(plan, mgr.live, mgr.account)
        if not plan.ok or rr:
            return text + (f"\n⛔ BLOCKED: {esc(rr)}" if rr else ""), None
        a, i, now = mgr.account, idea["id"], int(self.clock())
        return (text + f"\n\nTap Confirm within {CONFIRM_S // 60} minutes.",
                [("Confirm", f"{CONFIRM}|{a}|{i}|{now}"), ("Skip", f"{SKIP}|{a}|{i}")])
