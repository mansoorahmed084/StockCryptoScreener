"""SMC Sweep-Break -> the CoinDCX trade bot (backend/trading).

The scan finds calls on Binance futures candles; trades happen on CoinDCX INR
futures. For every NEW on-time call the paper journal logs:

  paper    --dcx-check: the call is sized and checked on CoinDCX by a DRY-RUN
           trade manager -- the real rules, the real instrument and price,
           nothing sent. The journal's `dcx` column records the plan, or why
           CoinDCX would refuse it. This is the 3-4 week paper phase.
  one-tap  --offer: the call is recorded as a proposed setup in the live bot's
           store and sent to Telegram with a Place button (ideas.propose).
           Only the owner's Place + Confirm taps, handled by `trade bot`,
           place it. The stop and the 6R target go on the exchange.

  auto     --auto (switched on by the owner, 2026-11-07): the call is placed
           at once with no tap, through the same rules (TradeManager.open):
           risk-sized, or sized down to the margin limit when a tight stop
           would need more margin. Fixed stop and 6R target on the exchange,
           no trailing stop (breakeven moves failed in the backtest).

When a logged trade ends on the 4h CHoCH or the 28-day limit, and the bot
holds that position from an SMC setup, the owner gets a message to close it
(the exchange stop and target do not know about the CHoCH exit). In auto
mode the bot closes it itself.

Owner's rules for auto mode:
  * never trade, and never close, the coins in PROTECTED: the owner's own
    positions, closed only when the owner asks
  * only positions the bot opened from an SMC setup are ever closed by it
  * spot is never touched: the client refuses any non-futures write

Two guards on top of the bot's own rules:
  * the coin must be an INR future on CoinDCX
  * CoinDCX's price must be within 1.5% of the Binance price the levels came
    from -- otherwise a 1000x-multiplier contract or a stale book would turn
    the Binance stop into nonsense
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402,F401  (puts the repo root on sys.path)

from backend.trading import ideas, risk  # noqa: E402
from backend.trading.manager import TradeError, TradeManager  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
MAX_GAP = 0.015          # CoinDCX vs Binance price
TIMEFRAME = "4h"
# The owner's own positions (2026-11-07): the auto mode never opens a trade
# on these coins and never closes them. Only the owner closes them.
PROTECTED = risk.OWNER_COINS
AUTO_EXITS = ("choch", "time")   # exits the exchange orders cannot see


def managers(dry_only: bool) -> tuple[TradeManager, TradeManager | None, ideas.Settings]:
    """A dry-run manager for checks and, unless dry_only, the configured one
    (live or dry run, per trading.mode) for offers."""
    from backend.config import load_config

    cfg = load_config()
    # the store path in config.yaml is relative to the repo root; the scan
    # runs from freqtrade-lab/, where it would open a second, empty database
    # the trade bot never reads
    t = cfg.raw.setdefault("trading", {})
    db = Path(t.get("db", "data_cache/trading.db"))
    t["db"] = str(db if db.is_absolute() else REPO / db)
    dry = TradeManager.from_config(cfg, force_dry_run=True)
    live = None if dry_only else TradeManager.from_config(cfg)
    return dry, live, ideas.Settings.from_config(cfg.trading.get("setups"))


def request(row, risk_inr: float, leverage: int) -> risk.TradeRequest:
    return risk.TradeRequest(pair=risk.to_pair(row.coin), side=row.side,
                             stop_loss=float(row.stop), take_profit=float(row.target),
                             risk_inr=risk_inr, leverage=leverage)


def gap_error(mgr: TradeManager, row, pair: str) -> str | None:
    """Why the Binance levels cannot be used on CoinDCX (None = they can)."""
    if pair not in set(mgr.client.active_pairs()):
        return f"{pair} is not an INR future on CoinDCX"
    dcx = mgr.last_price(pair)
    ref = float(row.last_px or row.seen_px or row.entry)
    if not dcx or not ref:
        return "no CoinDCX price"
    if abs(dcx / ref - 1) > MAX_GAP:
        return (f"CoinDCX price {dcx:g} is {100 * (dcx / ref - 1):+.1f}% from Binance "
                f"{ref:g}; the levels do not carry over")
    return None


def check(mgr: TradeManager, row, risk_inr: float, leverage: int) -> str:
    """One line for the journal: the dry-run plan, or why it is refused."""
    pair = risk.to_pair(row.coin)
    why = gap_error(mgr, row, pair)
    if why:
        return f"refused: {why}"
    plan = mgr.preview(request(row, risk_inr, leverage))
    rr = ideas.rr_error(plan)
    errors = plan.errors + ([rr] if rr else [])
    if errors:
        return "refused: " + "; ".join(errors)
    return (f"ok: {plan.qty:g} {pair} at ~{plan.entry:g}, risk Rs {plan.risk_inr:,.0f}, "
            f"margin Rs {plan.margin_inr:,.0f} at {leverage}x, {plan.rr:.1f}R to target")


def offer(mgr: TradeManager, settings: ideas.Settings, row, risk_inr: float,
          leverage: int) -> tuple[int | None, str]:
    """Record the call as a proposed setup and send it with a Place button."""
    pair = risk.to_pair(row.coin)
    why = gap_error(mgr, row, pair)
    if why:
        return None, f"not offered: {why}"
    exit_txt = (f"; exit on a 4h close {'below' if row.side == 'long' else 'above'} "
                f"{float(row.exit_level):g}" if row.exit_level else "")
    idea = ideas.propose(mgr, request(row, risk_inr, leverage), timeframe=TIMEFRAME,
                         why=f"SMC Sweep-Break #{row.id} (daily trend, 4h sweep + break)"
                             f"{exit_txt}", settings=settings)
    if idea["status"] == ideas.READY:
        return idea["id"], f"offered as setup #{idea['id']} (Place button)"
    return idea["id"], f"not offered: {idea['reason']}"


def protected(pair_or_coin: str) -> bool:
    return risk.to_pair(pair_or_coin).removeprefix("B-").removesuffix("_USDT") in PROTECTED


def sized_request(mgr: TradeManager, row, risk_inr: float,
                  leverage: int) -> tuple[risk.TradeRequest, str]:
    """The call sized to ``risk_inr``; if a tight stop makes that need more
    margin than the limits allow, the biggest trade they allow instead (same
    stop and target, so the same R; fewer rupees at risk)."""
    req = request(row, risk_inr, leverage)
    if not any("margin" in e for e in mgr.preview(req).errors):
        return req, ""
    free = mgr.free_inr() or 0.0
    cap = min(mgr.limits.max_margin_inr, risk.margin_budget(free)) * 0.98
    small = risk.TradeRequest(pair=req.pair, side=req.side, stop_loss=req.stop_loss,
                              take_profit=req.take_profit, risk_inr=0.0,
                              leverage=leverage, margin_inr=round(cap, 2))
    return small, f"sized down to margin Rs {cap:,.0f}"


def auto_open(mgr: TradeManager, settings: ideas.Settings, row, risk_inr: float,
              leverage: int) -> tuple[int | None, int | None, str]:
    """Place a fresh on-time call with no tap (the owner's auto mode).
    Returns (setup id, trade id, one line for the journal)."""
    pair = risk.to_pair(row.coin)
    if protected(pair):
        return None, None, f"not traded: {pair} is the owner's (protected)"
    why = gap_error(mgr, row, pair)
    if why:
        return None, None, f"not traded: {why}"
    req, sized = sized_request(mgr, row, risk_inr, leverage)
    exit_txt = (f"; exit on a 4h close {'below' if row.side == 'long' else 'above'} "
                f"{float(row.exit_level):g}" if row.exit_level else "")
    idea = ideas.propose(mgr, req, timeframe=TIMEFRAME, send=False, settings=settings,
                         why=f"SMC Sweep-Break #{row.id} AUTO (daily trend, 4h sweep "
                             f"+ break){exit_txt}")
    if idea["status"] != ideas.READY:
        return idea["id"], None, f"not traded: {idea['reason']}"
    # open() re-checks every rule at the live price. The trade bot's watcher
    # may attach the same stop/target if it runs during the fill: harmless.
    try:
        plan, trade_id = mgr.open(req, confirm=pair)
    except TradeError as exc:
        mgr.store.update_idea(idea["id"], status=ideas.FAILED, reason=str(exc)[:300])
        return idea["id"], None, f"not traded: {exc}"
    mgr.store.update_trade(trade_id, trail=0, note="SMC auto: fixed stop, no trail")
    if mgr.live:
        mgr.store.update_idea(idea["id"], status=ideas.PLACED, trade_id=trade_id)
    word = "traded" if mgr.live else "dry run (nothing sent)"
    return idea["id"], trade_id, (
        f"{word}: trade #{trade_id}, {plan.qty:g} {pair} at ~{plan.entry:g}, risk Rs "
        f"{plan.risk_inr:,.0f}, margin Rs {plan.margin_inr:,.0f}"
        + (f" ({sized})" if sized else ""))


def auto_close(mgr: TradeManager, row) -> str | None:
    """Close the bot's position from this call when the strategy exits on the
    4h CHoCH or the 28-day limit. Touches nothing else: not the owner's
    positions, not a protected coin, not a call the bot did not trade."""
    if row.why not in AUTO_EXITS or not row.idea or row.idea == "-":
        return None
    held = held_from_idea(mgr, row.idea)
    if held is None or protected(held["pair"]):
        return None
    mgr.close(held["pair"], confirm=held["pair"])
    mgr.store.update_trade(held["id"], note=f"SMC auto: closed on the strategy exit ({row.why})")
    return f"auto-closed trade #{held['id']} ({held['pair']})"


def held_from_idea(mgr: TradeManager, idea_id: int) -> dict | None:
    """The bot's OPEN trade placed from this setup, if it is still held."""
    idea = mgr.store.idea(int(idea_id))
    if not idea or not idea.get("trade_id"):
        return None
    t = next((x for x in mgr.store.trades("open") if x["id"] == idea["trade_id"]), None)
    if t is None or mgr.position(t["pair"]) is None:
        return None
    return t
