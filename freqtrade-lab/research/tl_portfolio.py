"""What would an ACCOUNT have done on the long-term trendline breakout?

    python research/tl_portfolio.py [max_open]

Pooled R-multiples answer "is there an edge". They do not answer "what would
the account have made", because the trades overlap. Alt coins break their
trendlines together, so a pooled average quietly assumes you could hold twenty
positions at once. This walks the trades in date order, caps concurrency,
sizes each at 1% of CURRENT equity and compounds -- which is also the only
place the year-by-year concentration shows up.

Fit and holdout coins are reported separately, and then the whole universe,
because the account would have traded all of them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness      # noqa: E402
import trendline    # noqa: E402
import portfolio    # noqa: E402
import campaign     # noqa: E402
from tl_campaign import BASE, START, TF, DETAIL, BAR, available  # noqa: E402

CAPITAL = 100_000.0


def collect(coins: list[str], trail_r: float = 3.0, time_stop: int = 365,
            **kw) -> list:
    plan = harness.ExitPlan(legs=[(100.0, 1.0)], trail_r=trail_r,
                            time_stop_bars=time_stop)
    out = []
    for c in coins:
        pair = f"{c}/USDT"
        try:
            base, det = harness.load(pair, TF), harness.load(pair, DETAIL)
        except FileNotFoundError:
            continue
        if len(base) < kw.get("lookback", 260) + 5:
            continue
        sig = trendline.trendline_breakout(base, **kw)
        sig = sig[sig.index >= START] if not sig.empty else sig
        if sig.empty:
            continue
        for tr in harness.simulate(sig, base, det, plan, base_bar=BAR):
            out.append((tr, c))
    return out


def report(name: str, trades: list, max_open: int) -> None:
    if not trades:
        print(f"\n### {name}: no trades\n")
        return
    acct = portfolio.simulate_account(trades, CAPITAL, 0.01, max_open)
    if acct.empty:
        print(f"\n### {name}: no fills\n")
        return
    years = (acct["exit"].max() - acct["entry"].min()).days / 365.25
    print(f"\n### {name}  (max {max_open} open, 1% risk, {years:.1f} years)")
    print(portfolio.summary(acct, years, CAPITAL))
    print(portfolio.by_year(acct, CAPITAL).to_string())


def main() -> None:
    max_open = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    coins = available(campaign.UNIVERSE)
    fit, hold = campaign.split(coins)

    for label, kw in [("no volume filter", dict(BASE, min_span=120)),
                      ("volume 1.5x", dict(BASE, min_span=120, vol_mult=1.5))]:
        print(f"\n{'=' * 70}\n## {label}")
        report(f"{label} - FIT coins", collect(fit, **kw), max_open)
        report(f"{label} - HOLDOUT coins", collect(hold, **kw), max_open)
        report(f"{label} - WHOLE universe", collect(coins, **kw), max_open)


if __name__ == "__main__":
    main()
