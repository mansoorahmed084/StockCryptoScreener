"""The owner's Telegram commands for the trade bot (two-way chat).

  /positions            open positions on every watched account, profit/loss now
  /pnl                  profit and loss: today (IST), 7 days, 30 days, open now
  /close COIN [account] close one position, after a Close button (2 minutes)
  /help                 this list

Only the owner's chat is answered (tgbot.Listener checks it). Reading needs no
lock. A close is never done on the command alone: the bot shows the position
with a **Close** button, and only that tap (within ``CONFIRM_S``) closes it,
through TradeManager.close under the account's lock. The owner's protected
coins (risk.OWNER_COINS) are never closed by any automatic path; the owner may
close them here, because this is the owner asking.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from backend.trading import risk
from backend.trading.manager import TradeManager, _f

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
COMMANDS = [("positions", "open positions and profit/loss now"),
            ("pnl", "profit and loss: today, 7 days, 30 days"),
            ("close", "close one position, e.g. /close SOL"),
            ("help", "what this bot can do")]
ALIASES = {"pos": "positions", "open": "positions", "p": "positions",
           "pl": "pnl", "profit": "pnl", "start": "help"}
HELP = ("Commands:\n"
        "/positions - open positions and profit/loss now\n"
        "/pnl - profit and loss: today, 7 days, 30 days\n"
        "/close SOL - close one position (you confirm with a button)\n"
        "/help - this list\n"
        "SMC trades are placed by the scan; this chat never opens a trade.")


def parse(text: str) -> tuple[str, list[str]]:
    """'/close sol main' -> ('close', ['sol', 'main']); '/pnl@MyBot' -> ('pnl', [])."""
    words = (text or "").strip().split()
    if not words:
        return "", []
    cmd = words[0].lstrip("/").split("@")[0].lower()
    return ALIASES.get(cmd, cmd), words[1:]


def coin(pair: str) -> str:
    return pair.removeprefix("B-").removesuffix("_USDT")


def inr(x: float) -> str:
    return f"{'+' if x >= 0 else '-'}Rs {abs(x):,.0f}"


def unrealized_inr(pos: dict, rate: float) -> float:
    """Profit/loss of an open position at the mark price, in rupees."""
    q = _f(pos.get("active_pos"))
    return q * (_f(pos.get("mark_price")) - _f(pos.get("avg_price"))) * rate


def position_line(p: dict, rate: float, who: str) -> str:
    q, avg, mark = _f(p.get("active_pos")), _f(p.get("avg_price")), _f(p.get("mark_price"))
    pct = (mark / avg - 1) * 100 * (1 if q > 0 else -1) if avg else 0.0
    sl, tp = _f(p.get("stop_loss_trigger")), _f(p.get("take_profit_trigger"))
    return (f"{coin(p['pair'])} {'LONG' if q > 0 else 'SHORT'} {abs(q):g} @ {avg:.6g}, "
            f"now {mark:.6g} ({pct:+.1f}%): {inr(unrealized_inr(p, rate))}\n"
            f"   SL {f'{sl:g}' if sl else 'NONE'}, TP {f'{tp:g}' if tp else 'none'}, "
            f"{_f(p.get('leverage')):g}x, liq {_f(p.get('liquidation_price')):g} [{who}]")


def whose(m: TradeManager, pair: str) -> str:
    bot = {t["pair"]: t["id"] for t in m.store.trades("open")}
    who = f"bot trade #{bot[pair]}" if pair in bot else "yours"
    return who + (", protected" if risk.owner_coin(pair) else "")


def positions_text(mgrs: dict[str, TradeManager]) -> str:
    out: list[str] = []
    for name, m in mgrs.items():
        if not m.client.has_keys:
            out.append(f"[{name}] no API keys")
            continue
        pos = m.positions()
        rate, _ = m.rate()
        total = sum(unrealized_inr(p, rate) for p in pos)
        free = m.free_inr() or 0.0
        out.append(f"[{name}] {len(pos)} open, {inr(total)} now. Free Rs {free:,.0f}")
        for p in sorted(pos, key=lambda p: unrealized_inr(p, rate)):
            out.append(position_line(p, rate, whose(m, p["pair"])))
    return "\n".join(out) or "No account is watched."


def ledger(m: TradeManager, since_ms: float, max_pages: int = 30) -> list[dict]:
    """Futures wallet entries (newest first) back to ``since_ms``."""
    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        got = m.client.transactions(page)
        rows += [t for t in got if _f(t.get("created_at")) >= since_ms]
        if len(got) < 100 or min(_f(t.get("created_at")) for t in got) < since_ms:
            break
    return rows


def pnl_text(mgrs: dict[str, TradeManager], now: dt.datetime | None = None) -> str:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(IST)
    windows = [("Today (IST)", now.replace(hour=0, minute=0, second=0, microsecond=0)),
               ("7 days", now - dt.timedelta(days=7)),
               ("30 days", now - dt.timedelta(days=30))]
    out: list[str] = []
    for name, m in mgrs.items():
        if not m.client.has_keys:
            out.append(f"[{name}] no API keys")
            continue
        rows = ledger(m, windows[-1][1].timestamp() * 1000)
        out.append(f"[{name}] profit and loss, closed (rupees):")
        for label, start in windows:
            sel = [t for t in rows if _f(t.get("created_at")) >= start.timestamp() * 1000]
            trades = sum(_f(t.get("amount")) for t in sel if t.get("stage") != "funding")
            funding = sum(_f(t.get("amount")) for t in sel if t.get("stage") == "funding")
            fees = -sum(_f(t.get("fee_amount")) for t in sel)
            out.append(f"{label}: net {inr(trades + funding + fees)} (trades {inr(trades)}, "
                       f"funding {inr(funding)}, fees {inr(fees)})")
        pos = m.positions()
        rate, _ = m.rate()
        out.append(f"Open now: {inr(sum(unrealized_inr(p, rate) for p in pos))} "
                   f"on {len(pos)} position(s), not yet closed")
    return "\n".join(out) or "No account is watched."


def find_position(mgrs: dict[str, TradeManager], what: str,
                  account: str | None) -> tuple[TradeManager | None, dict | None, str]:
    """The account and position that '/close WHAT [account]' means, or why not."""
    pair = risk.to_pair(what)
    if account:
        m = mgrs.get(account.lower())
        if m is None:
            return None, None, f"no account {account!r} here ({', '.join(mgrs)})"
        pos = m.position(pair)
        return (m, pos, "") if pos else (None, None, f"no open {coin(pair)} position on {account}")
    held = [(m, p) for m in mgrs.values() if (p := m.position(pair))]
    if not held:
        return None, None, f"no open {coin(pair)} position"
    if len(held) > 1:
        names = " and ".join(m.account for m, _ in held)
        return None, None, (f"{coin(pair)} is open on {names}: send /close {coin(pair)} "
                            f"{held[0][0].account}")
    return held[0][0], held[0][1], ""


def close_prompt(m: TradeManager, pos: dict) -> str:
    rate, _ = m.rate()
    lines = [f"[{m.account}] Close this position at market?",
             position_line(pos, rate, whose(m, pos["pair"]))]
    if risk.owner_coin(pos["pair"]):
        lines.append("This is one of your protected coins. The bot never closes it by "
                     "itself; tap Close only if you mean it.")
    if not m.live:
        lines.append("DRY RUN: nothing will be sent.")
    return "\n".join(lines)


def reply_for(mgrs: dict[str, TradeManager], text: str) -> tuple[str, Any]:
    """(command, what to answer). For 'close' the answer is (manager, position)
    or an error string; everything else is text."""
    cmd, args = parse(text)
    if cmd == "positions":
        return cmd, positions_text(mgrs)
    if cmd == "pnl":
        return cmd, pnl_text(mgrs)
    if cmd == "close":
        if not args:
            return cmd, "Which one? Send /close SOL (or /close SOL sehe)."
        m, pos, why = find_position(mgrs, args[0], args[1] if len(args) > 1 else None)
        return cmd, (m, pos) if m else why
    return "help", HELP
