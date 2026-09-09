"""Account simulation that credits profit when the trade CLOSES, not when it opens.

`portfolio.py` walks trades in entry order and does `equity += equity * risk * r`
immediately, so a trade entered in January and closed in December funds the size
of a trade entered in February. That is compounding money the account does not
have yet. It barely matters for a strategy that holds for days. It matters a lot
here: winners average 74 days and some run the full 365-day time stop.

So this runs a proper event queue -- size on the equity that exists at entry,
credit the profit at exit -- and reports both numbers side by side, because the
gap IS the size of the flaw in every earlier result that used portfolio.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import portfolio    # noqa: E402
import campaign     # noqa: E402
from tl_campaign import available          # noqa: E402
from tl_portfolio import collect, CAPITAL  # noqa: E402
from tl_final import FINAL, TRAIL_R, TIME_STOP  # noqa: E402


def simulate_honest(trades: list, capital: float = CAPITAL,
                    risk: float = 0.01, max_open: int = 10,
                    max_exposure: float | None = None) -> pd.DataFrame:
    """Chronological event queue: size at entry, bank at exit.

    `max_exposure` caps the total NOTIONAL held at once, as a multiple of
    equity. This is not pedantry. Position size is `risk / stop_distance`, so a
    1% risk behind a 6% stop is a 17% position -- and ten of those is 167% of
    the account, which spot cannot do. Tightening the stop silently borrows
    money unless something says otherwise. Pass 1.0 for a spot account; leave
    it None to reproduce the older, unconstrained numbers.

    A trade that does not fit is sized down to the room left, and skipped
    entirely if less than a quarter of its intended size would fit.
    """
    events = []
    for i, (tr, coin) in enumerate(sorted(trades, key=lambda x: x[0].entry_time)):
        events.append((tr.entry_time, 0, i, tr, coin))     # 0 sorts entries...
    equity = capital
    open_trades: dict = {}
    rows = []
    pending = sorted(events)
    exposure = 0.0                                   # notional currently held

    while pending or open_trades:
        next_exit = min((t.exit_time for t, _ in open_trades.values()),
                        default=None)
        next_entry = pending[0][0] if pending else None
        # close everything that finishes before the next entry decision
        if next_exit is not None and (next_entry is None or next_exit <= next_entry):
            k = min(open_trades, key=lambda k: open_trades[k][0].exit_time)
            tr, coin = open_trades.pop(k)
            exposure -= tr.notional
            pnl = tr.stake_risk * tr.r
            equity += pnl
            rows.append({"entry": tr.entry_time, "exit": tr.exit_time,
                         "coin": coin, "r": tr.r, "pnl": pnl, "equity": equity})
            continue
        ts, _, i, tr, coin = pending.pop(0)
        if len(open_trades) >= max_open:
            continue                                  # no slot: signal skipped
        want = equity * risk                          # sized on money that exists
        stop_pct = (tr.entry - tr.stop) / tr.entry
        notional = want / stop_pct if stop_pct > 0 else 0.0
        if max_exposure is not None:
            room = max_exposure * equity - exposure
            if room < 0.25 * notional:
                continue                              # no capital: signal skipped
            if room < notional:
                want *= room / notional               # take what fits
                notional = room
        tr.stake_risk = want
        tr.notional = notional
        exposure += notional
        open_trades[i] = (tr, coin)

    out = pd.DataFrame(rows)
    return out.sort_values("exit").reset_index(drop=True) if not out.empty else out


def main() -> None:
    max_open = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    coins = available(campaign.UNIVERSE)
    fit, hold = campaign.split(coins)
    print("# Sizing on money that EXISTS vs money credited early\n")
    print(f"| coins | fills | **CAGR (honest)** | CAGR (portfolio.py) | "
          f"maxDD honest | maxDD portfolio.py |")
    print("|" + "---|" * 6)
    for name, cs in [("FIT coins", fit), ("HOLDOUT coins", hold),
                     ("WHOLE universe", coins)]:
        tr = collect(cs, trail_r=TRAIL_R, time_stop=TIME_STOP, **FINAL)
        a = simulate_honest(tr, CAPITAL, 0.01, max_open)
        b = portfolio.simulate_account(tr, CAPITAL, 0.01, max_open)
        if a.empty or b.empty:
            continue
        ya = (a["exit"].max() - a["entry"].min()).days / 365.25
        yb = (b["exit"].max() - b["entry"].min()).days / 365.25
        sa, sb = portfolio.summary(a, ya, CAPITAL), portfolio.summary(b, yb, CAPITAL)
        print(f"| {name} | {sa['n']} | **{sa['cagr%']:.1f}%** | {sb['cagr%']:.1f}% "
              f"| {sa['max_dd%']:.1f}% | {sb['max_dd%']:.1f}% |")

    tr = collect(coins, trail_r=TRAIL_R, time_stop=TIME_STOP, **FINAL)
    a = simulate_honest(tr, CAPITAL, 0.01, max_open)
    print(f"\n## Year by year, whole universe, honest sizing, max {max_open} open")
    print(portfolio.by_year(a.rename(columns={"exit": "_x"}).assign(exit=a["exit"]),
                            CAPITAL).to_string())


if __name__ == "__main__":
    main()
