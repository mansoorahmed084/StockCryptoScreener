"""How the trade bot's Telegram messages look (HTML, sent with parse_mode HTML).

Every trade message reads the same way (the owner's layout, 2026-11-08):

    🟢 OPEN LONG SOL
    08 Nov 2026, 01:35 IST

    Risk: ₹500 (stop 85.2, -3.0%)
    Reward: ₹3,000 (target 104.1, +18.0%) · 6.0R

    details...

    ✅ CLOSED LONG SOL / 🔴 CLOSED LONG SOL
    08 Nov 2026, 13:35 IST

    Gained: +₹1,240 (+2.5R)  /  Loss: -₹480 (-1.0R)

Text from outside (pair names, exchange errors) is always escaped.
"""
from __future__ import annotations

import datetime as dt
import html
import math
import re
from typing import Any

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MINUS = "−"                      # a real minus sign reads better than "-"


def esc(x: Any) -> str:
    return html.escape(str(x), quote=False)


def strip(text: str) -> str:
    """The plain-text version of a card (when Telegram refuses the HTML)."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def px(x: Any) -> str:
    """A price, short: 89.84, 0.06399, 0.00001234 (never 1.2e-05)."""
    x = float(x or 0)
    if x == 0:
        return "0"
    digits = max(2, 5 - int(math.floor(math.log10(abs(x)))))
    s = f"{x:,.{min(digits, 10)}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def rs(x: float, sign: bool = False) -> str:
    """Rupees, Indian grouping: ₹1,00,359. ``sign`` adds + or −."""
    n = str(round(abs(x)))
    if len(n) > 3:
        n = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", n[:-3]) + "," + n[-3:]
    pre = ("+" if x >= 0 else MINUS) if sign else ("" if x >= 0 else MINUS)
    return f"{pre}₹{n}"


def signed(x: float, fmt: str = ".1f", unit: str = "") -> str:
    return f"{'+' if x >= 0 else MINUS}{abs(x):{fmt}}{unit}"


def pct(frm: float, to: float) -> str:
    return signed((to / frm - 1) * 100, unit="%") if frm else "?"


def when(ts: Any = None) -> str:
    """'08 Nov 2026, 01:35 IST' from None (now), epoch ms, a datetime or a
    UTC time string such as '2026-11-07 16:00'."""
    if ts is None or ts == "":
        t = dt.datetime.now(dt.timezone.utc)
    elif isinstance(ts, (int, float)):
        t = dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc)
    elif isinstance(ts, dt.datetime):
        t = ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)
    else:
        t = dt.datetime.fromisoformat(str(ts).replace("Z", "")).replace(tzinfo=dt.timezone.utc)
    return t.astimezone(IST).strftime("%d %b %Y, %H:%M IST")


def coin(pair: str) -> str:
    return str(pair).removeprefix("B-").removesuffix("_USDT")


def head(icon: str, words: str, account: str = "main") -> str:
    tag = "" if account in ("", "main") else f" · {esc(account)}"
    return f"<b>{icon} {esc(words)}</b>{tag}"


def card(title: str, ts: Any, main: list[str], details: list[str] = ()) -> str:
    """Title, time, a blank line, the main lines, a blank line, the details."""
    out = [title, when(ts), ""] + [m for m in main if m]
    details = [d for d in details if d]
    if details:
        out += [""] + details
    return "\n".join(out)


def risk_line(risk_inr: float | None, stop: float, entry: float) -> str:
    money = f"{rs(risk_inr)} " if risk_inr else ""
    return f"<b>Risk:</b> {money}(stop {px(stop)}, {pct(entry, stop)})"


def reward_line(reward_inr: float | None, target: float | None, entry: float,
                rr: float | None) -> str:
    if not target:
        return "<b>Reward:</b> no target set"
    money = f"{rs(reward_inr)} " if reward_inr else ""
    r = f" · {rr:.1f}R" if rr else ""
    return f"<b>Reward:</b> {money}(target {px(target)}, {pct(entry, target)}){r}"


def result_line(pnl_inr: float | None, r: float | None = None) -> str:
    rr = f" ({signed(r, '.2f', 'R')})" if r is not None else ""
    if pnl_inr is None:
        return f"<b>Result:</b> not booked yet{rr}. Send /pnl in a minute."
    word = "Gained" if pnl_inr >= 0 else "Loss"
    return f"<b>{word}:</b> {rs(pnl_inr, sign=True)}{rr}"


# ------------------------------------------------------------------ trade events
def open_card(t: dict, account: str = "main", live: bool = True, ts: Any = None,
              reward_inr: float | None = None, rr: float | None = None) -> str:
    """A trade the bot opened (a row of the trades table, entry = fill price)."""
    side, c, entry = t["side"].upper(), coin(t["pair"]), float(t["entry"] or 0)
    icon, word = ("🟢", "OPEN") if live else ("🧪", "DRY RUN OPEN")
    return card(head(icon, f"{word} {side} {c}", account), ts, [
        risk_line(t.get("risk_inr"), t["stop_loss"], entry),
        reward_line(reward_inr, t.get("take_profit"), entry, rr),
    ], [
        f"Size {float(t['qty'] or 0):g} {esc(c)} at {px(entry)} · {t.get('leverage') or '?'}x"
        f" · margin {rs(t.get('margin_inr') or 0)}",
        f"Trade #{t['id']}" + (f" · {esc(t['note'])}" if t.get("note") else ""),
    ])


def closed_card(*, side: str, pair: str, entry: float, exit_px: float | None,
                pnl_inr: float | None, risk_inr: float | None, why: str,
                trade_id: int | None = None, account: str = "main", ts: Any = None) -> str:
    r = pnl_inr / risk_inr if (pnl_inr is not None and risk_inr) else None
    icon = "⚪" if pnl_inr is None else ("✅" if pnl_inr >= 0 else "🔴")
    move = (f" ({pct(entry, exit_px) if side.lower() == 'long' else pct(exit_px, entry)})"
            if exit_px and entry else "")
    return card(head(icon, f"CLOSED {side.upper()} {coin(pair)}", account), ts, [
        result_line(pnl_inr, r),
    ], [
        f"Entry {px(entry)} → exit {px(exit_px) if exit_px else '?'}{move}",
        f"Why: {esc(why)}",
        f"Trade #{trade_id}" if trade_id else "",
    ])


def stop_moved_card(*, side: str, pair: str, old: float | None, new: float, entry: float,
                    account: str = "main", live: bool = True) -> str:
    locked = (new / entry - 1) * 100 * (1 if side.lower() == "long" else -1) if entry else 0
    return card(head("🔒", f"STOP MOVED {side.upper()} {coin(pair)}", account), None, [
        f"<b>New stop:</b> {px(new)} (locks {signed(locked, unit='%')} vs entry {px(entry)})",
        f"Old stop: {px(old) if old else 'none'}",
    ], [] if live else ["Dry run: not sent"])


def warn_card(title: str, lines: list[str], account: str = "main") -> str:
    return card(head("⚠️", title, account), None, [esc(x) for x in lines])


def notice(text: str, account: str = "main") -> str:
    """Any other bot message: a small header and the escaped text."""
    tag = "" if account in ("", "main") else f" · {esc(account)}"
    return f"<b>ℹ️ CoinDCX bot</b>{tag}\n{esc(text)}"


# ------------------------------------------------------------------ setups and plans
def idea_card(idea: dict, account: str = "main", why: str = "") -> str:
    """A setup offered with a Place button."""
    side = (idea.get("side") or "long").upper()
    c, entry = idea["coin"], float(idea.get("price") or 0)
    kind = f"limit {px(idea['limit_price'])}" if idea.get("limit_price") else \
        f"market ~{px(entry)}"
    return card(head("🔔", f"TRADE IDEA {side} {c}", account), idea.get("ts_ms"), [
        risk_line(idea.get("risk_inr"), idea["stop"], entry),
        reward_line(None, idea.get("target"), entry, idea.get("rr")),
    ], [
        f"Entry {kind} · {esc(idea.get('timeframe') or '')}",
        f"Why: {esc(why)}" if why else "",
        f"Setup #{idea['id']} · tap Place to see the live plan",
    ])


def plan_card(plan, live: bool, account: str = "main") -> str:
    """The live plan shown after Place (risk.Plan)."""
    r = plan.request
    side, c = r.side.upper(), coin(r.pair)
    lines = [risk_line(plan.risk_inr, plan.stop_loss, plan.entry),
             reward_line(plan.reward_inr, plan.take_profit, plan.entry, plan.rr)]
    details = [f"Size {plan.qty:g} {esc(c)} at {px(plan.entry)} ({esc(r.entry_type)}) · "
               f"{r.leverage}x · margin {rs(plan.margin_inr)}",
               f"Liquidation near {px(plan.liq_price)}" if plan.liq_price else ""]
    details += [f"⚠️ {esc(w)}" for w in plan.warnings]
    details += [f"⛔ BLOCKED: {esc(e)}" for e in plan.errors]
    word = "PLAN" if live else "DRY RUN PLAN"
    return card(head("📝", f"{word} {side} {c}", account), None, lines, details)
