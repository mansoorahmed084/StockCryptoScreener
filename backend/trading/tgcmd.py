"""The owner's Telegram commands for the trade bot (two-way chat).

  /positions            open positions on every watched account, profit/loss now
  /pnl                  profit and loss: today (IST), 7 days, 30 days, open now
  /close COIN [account] close one position, after a Close button (2 minutes)
  /help                 this list

Answers are tgfmt cards (HTML). Only the owner's chat is answered
(tgbot.Listener checks it). Reading needs no lock. A close is never done on
the command alone: the bot shows the position with a **Close it** button, and
only that tap (within ``CONFIRM_S``) closes it, through TradeManager.close
under the account's lock. The owner's protected coins (risk.OWNER_COINS) are
never closed by any automatic path; the owner may close them here, because
this is the owner asking.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from backend.trading import risk, tgfmt
from backend.trading.manager import TradeManager, _f, position_side
from backend.trading.tgfmt import IST, esc, px, rs

COMMANDS = [("positions", "open positions and profit/loss now"),
            ("pnl", "profit and loss: today, 7 days, 30 days"),
            ("close", "close one position, e.g. /close SOL"),
            ("help", "what this bot can do")]
ALIASES = {"pos": "positions", "open": "positions", "p": "positions",
           "pl": "pnl", "profit": "pnl", "start": "help"}
HELP = ("<b>🤖 TRADE BOT COMMANDS</b>\n\n"
        "/positions · open positions and profit/loss now\n"
        "/pnl · profit and loss: today, 7 days, 30 days\n"
        "/close SOL · close one position (you confirm with a button)\n"
        "/help · this list\n\n"
        "SMC trades are placed by the scan. This chat never opens a trade.")


def parse(text: str) -> tuple[str, list[str]]:
    """'/close sol main' -> ('close', ['sol', 'main']); '/pnl@MyBot' -> ('pnl', [])."""
    words = (text or "").strip().split()
    if not words:
        return "", []
    cmd = words[0].lstrip("/").split("@")[0].lower()
    return ALIASES.get(cmd, cmd), words[1:]


coin = tgfmt.coin


def inr(x: float) -> str:
    return rs(x, sign=True)


def unrealized_inr(pos: dict, rate: float) -> float:
    """Profit/loss of an open position at the mark price, in rupees."""
    q = _f(pos.get("active_pos"))
    return q * (_f(pos.get("mark_price")) - _f(pos.get("avg_price"))) * rate


def whose(m: TradeManager, pair: str) -> str:
    bot = {t["pair"]: t["id"] for t in m.store.trades("open")}
    who = f"bot trade #{bot[pair]}" if pair in bot else "yours"
    return who + (" 🔒" if risk.owner_coin(pair) else "")


def position_block(p: dict, rate: float, who: str) -> str:
    """One position: side and coin, prices, profit/loss now, SL/TP."""
    q, avg, mark = _f(p.get("active_pos")), _f(p.get("avg_price")), _f(p.get("mark_price"))
    u = unrealized_inr(p, rate)
    move = tgfmt.pct(avg, mark) if q > 0 else tgfmt.pct(mark, avg)
    sl, tp = _f(p.get("stop_loss_trigger")), _f(p.get("take_profit_trigger"))
    return "\n".join([
        f"{'✅' if u >= 0 else '🔴'} <b>{position_side(p).upper()} {esc(coin(p['pair']))}</b>"
        f" · {esc(who)}",
        f"{abs(q):,g} @ {px(avg)} → {px(mark)} ({move})",
        f"<b>{'Gain' if u >= 0 else 'Loss'} now:</b> {inr(u)}",
        f"SL {px(sl) if sl else '<b>NONE</b>'} · TP {px(tp) if tp else 'none'} · "
        f"{_f(p.get('leverage')):g}x · liq {px(_f(p.get('liquidation_price')))}",
    ])


def positions_text(mgrs: dict[str, TradeManager]) -> str:
    out: list[str] = []
    for name, m in mgrs.items():
        if not m.client.has_keys:
            out.append(tgfmt.head("📊", "OPEN POSITIONS", name) + "\nNo API keys.")
            continue
        pos = m.positions()
        rate, _ = m.rate()
        total = sum(unrealized_inr(p, rate) for p in pos)
        blocks = [position_block(p, rate, whose(m, p["pair"]))
                  for p in sorted(pos, key=lambda p: unrealized_inr(p, rate))]
        out.append(tgfmt.card(tgfmt.head("📊", "OPEN POSITIONS", name), None, [
            f"<b>Open profit/loss:</b> {inr(total)} on {len(pos)}",
            f"<b>Free balance:</b> {rs(m.free_inr() or 0.0)}",
        ]) + ("\n\n" + "\n\n".join(blocks) if blocks else "\n\nNo open position."))
    return "\n\n".join(out) or "No account is watched."


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
    windows = [("Today", now.replace(hour=0, minute=0, second=0, microsecond=0)),
               ("7 days", now - dt.timedelta(days=7)),
               ("30 days", now - dt.timedelta(days=30))]
    out: list[str] = []
    for name, m in mgrs.items():
        if not m.client.has_keys:
            out.append(tgfmt.head("💰", "PROFIT AND LOSS", name) + "\nNo API keys.")
            continue
        rows = ledger(m, windows[-1][1].timestamp() * 1000)
        lines = []
        for label, start in windows:
            sel = [t for t in rows if _f(t.get("created_at")) >= start.timestamp() * 1000]
            trades = sum(_f(t.get("amount")) for t in sel if t.get("stage") != "funding")
            funding = sum(_f(t.get("amount")) for t in sel if t.get("stage") == "funding")
            fees = -sum(_f(t.get("fee_amount")) for t in sel)
            lines += [f"<b>{label}:</b> {inr(trades + funding + fees)}",
                      f"   trades {inr(trades)} · funding {inr(funding)} · fees {inr(fees)}"]
        pos = m.positions()
        rate, _ = m.rate()
        out.append(tgfmt.card(tgfmt.head("💰", "PROFIT AND LOSS", name), now, [
            "<i>Booked (closed) profit and loss</i>", *lines,
        ], [
            f"<b>Open now:</b> {inr(sum(unrealized_inr(p, rate) for p in pos))} on "
            f"{len(pos)} position(s), not booked yet",
        ]))
    return "\n\n".join(out) or "No account is watched."


def find_position(mgrs: dict[str, TradeManager], what: str,
                  account: str | None) -> tuple[TradeManager | None, dict | None, str]:
    """The account and position that '/close WHAT [account]' means, or why not."""
    pair = risk.to_pair(what)
    if account:
        m = mgrs.get(account.lower())
        if m is None:
            return None, None, f"No account {esc(account)} here ({esc(', '.join(mgrs))})."
        pos = m.position(pair)
        return (m, pos, "") if pos else (None, None,
                                         f"No open {esc(coin(pair))} position on {esc(account)}.")
    held = [(m, p) for m in mgrs.values() if (p := m.position(pair))]
    if not held:
        return None, None, f"No open {esc(coin(pair))} position."
    if len(held) > 1:
        names = " and ".join(m.account for m, _ in held)
        return None, None, (f"{esc(coin(pair))} is open on {esc(names)}. Send "
                            f"/close {esc(coin(pair))} {esc(held[0][0].account)}")
    return held[0][0], held[0][1], ""


def close_prompt(m: TradeManager, pos: dict) -> str:
    rate, _ = m.rate()
    main = [position_block(pos, rate, whose(m, pos["pair"]))]
    details = ["Closes at market. The button works for 2 minutes."]
    if risk.owner_coin(pos["pair"]):
        details.insert(0, "⚠️ Protected coin: the bot never closes it by itself. "
                          "Tap Close it only if you mean it.")
    if not m.live:
        details.append("🧪 Dry run: nothing will be sent.")
    title = tgfmt.head("❓", f"CLOSE {position_side(pos).upper()} {coin(pos['pair'])}?",
                       m.account)
    return tgfmt.card(title, None, main, details)


def reply_for(mgrs: dict[str, TradeManager], text: str) -> tuple[str, Any]:
    """(command, what to answer). For 'close' the answer is (manager, position)
    or a message; everything else is an HTML message."""
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
