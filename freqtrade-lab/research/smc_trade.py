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

When a logged trade ends on the 4h CHoCH or the 28-day limit, and the bot
holds that position from an SMC setup, the owner gets a message to close it
(the exchange stop and target do not know about the CHoCH exit).

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
from backend.trading.manager import TradeManager  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
MAX_GAP = 0.015          # CoinDCX vs Binance price
TIMEFRAME = "4h"


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


def held_from_idea(mgr: TradeManager, idea_id: int) -> dict | None:
    """The bot's OPEN trade placed from this setup, if it is still held."""
    idea = mgr.store.idea(int(idea_id))
    if not idea or not idea.get("trade_id"):
        return None
    t = next((x for x in mgr.store.trades("open") if x["id"] == idea["trade_id"]), None)
    if t is None or mgr.position(t["pair"]) is None:
        return None
    return t
