"""Telegram cards for the desk, in the bot's one layout (backend/trading/tgfmt.py):
title, time, a blank line, the main lines, a blank line, the details.
Every desk card is tagged "· desk" so it never reads like a real trade.
"""
from __future__ import annotations

import logging
import math

from backend.trading.tgfmt import card, esc, head, pct, px, signed

from .rules import TEXT
from .settings import MARKET_NAMES, Settings, short

log = logging.getLogger(__name__)
TAG = "desk"


def _risk(entry: float, stop: float, risk_pct: float | None = None) -> str:
    share = f"{risk_pct:.1f}% of the paper account " if risk_pct else ""
    return f"<b>Risk:</b> {share}(stop {px(stop)}, {pct(entry, stop)})"


def _reward(entry: float, stop: float, target: float) -> str:
    rr = (target - entry) / (entry - stop) if entry > stop else 0
    return f"<b>Reward:</b> (target {px(target)}, {pct(entry, target)}) · {rr:.1f}R"


def open_card(t: dict, risk_pct: float | None) -> str:
    c = short(t["symbol"])
    return card(head("🧪", f"PAPER OPEN LONG {c}", TAG), None, [
        _risk(t["entry"], t["stop"], risk_pct),
        _reward(t["entry"], t["stop"], t["target"]),
    ], [
        f"Filled {px(t['entry'])} · rule {esc(t['rule'])} · {esc(t['symbol'])}",
        f"Plan #{t['plan_id']} · trade #{t['id']} · paper only, no real order",
    ])


def closed_card(t: dict, exit_px: float, why: str, r: float, pnl: float,
                equity: float) -> str:
    icon, word = ("✅", "Gained") if r >= 0 else ("🔴", "Loss")
    share = pnl / equity * 100 if equity else 0
    return card(head(icon, f"PAPER CLOSED LONG {short(t['symbol'])}", TAG), None, [
        f"<b>{word}:</b> {signed(r, '.2f', 'R')} ({signed(share, '.2f', '%')} of the account)",
    ], [
        f"Entry {px(t['entry'])} → exit {px(exit_px)} ({pct(t['entry'], exit_px)})",
        f"Why: {esc({'stop': 'stop hit', 'target': 'target hit', 'time': 'time exit'}.get(why, why))}",
        f"Trade #{t['id']} · rule {esc(t['rule'])}",
    ])


def skip_card(plan: dict, why: str) -> str:
    return card(head("⏭️", f"PAPER SKIPPED LONG {short(plan['symbol'])}", TAG), None, [
        f"<b>Risk layer:</b> {esc(why)}",
        _reward(plan["entry"], plan["stop"], plan["target"]),
    ], [f"Plan #{plan['id']} · rule {esc(plan['rule'])}"])


def alert_card(a: dict, last: float) -> str:
    word = "ABOVE" if a["op"] == "above" else "BELOW"
    return card(head("🔔", f"ALERT {short(a['symbol'])} {word} {px(a['price'])}", TAG), None, [
        f"<b>Price:</b> {px(last)} ({esc(a['symbol'])})",
    ], [f"Note: {esc(a['note'])}" if a.get("note") else "", f"Alert #{a['id']}"])


def morning_card(screen_rows: list[dict], plans: list[dict], kept: dict[str, list[str]]) -> str:
    top = [f"{short(r['symbol'])} {r['score']:.0f} · {r['trend']}"
           + (f" · 1m {signed(r['chg_1m'], '.1f', '%')}" if not math.isnan(r["chg_1m"]) else "")
           for r in screen_rows[:5]]
    plan_lines = [f"{short(p['symbol'])}: buy above {px(p['entry'])}, stop {px(p['stop'])}, "
                  f"target {px(p['target'])} ({esc(p['rule'])})" for p in plans]
    rules = ", ".join(f"{MARKET_NAMES[m]}: {', '.join(rs)}" for m, rs in kept.items()) \
        or "none (no rule passed the backtest)"
    return card(head("☀️", "MORNING SCREEN", TAG), None, [
        "<b>Strongest:</b> " + esc("; ".join(top) or "no data"),
        f"<b>New plans:</b> {len(plans)}",
    ], [esc(x) for x in plan_lines] + [f"Rules in use: {esc(rules)}"])


def night_card(verdicts: list[dict], spikes: list[str], fng: dict | None) -> str:
    kept = [f"{MARKET_NAMES[v['market']]} {v['rule']} ({v['w_exp']:+.2f}R)"
            for v in verdicts if v["keep"]]
    lines = [f"<b>Rules kept:</b> {esc(', '.join(kept) or 'none')}",
             f"<b>Rules killed:</b> {sum(1 for v in verdicts if not v['keep'])}"]
    details = []
    if fng:
        details.append(f"Crypto Fear &amp; Greed: {fng['value']} ({esc(fng['label'])})")
    if spikes:
        details.append("News spike: " + esc(", ".join(spikes)))
    return card(head("🌙", "NIGHT RESEARCH", TAG), None, lines, details)


def rule_text(rule: str) -> str:
    return TEXT.get(rule, rule)


class Sender:
    """Sends cards to Telegram when desk.yaml allows it and .env has a bot."""

    def __init__(self, settings: Settings, notifier=None):
        self.enabled = bool(settings.section("notify").get("telegram", True))
        self._notifier = notifier
        self._loaded = notifier is not None

    def _get(self):
        if not self._loaded:
            from backend.alerts.telegram import telegram_from_env
            self._notifier = telegram_from_env()
            self._loaded = True
        return self._notifier

    def send(self, html: str) -> bool:
        if not self.enabled:
            return False
        n = self._get()
        if n is None:
            return False
        try:
            return bool(n.send_html(html))
        except Exception as exc:   # a Telegram hiccup must not stop the desk
            log.warning("desk Telegram send failed: %s", exc)
            return False
