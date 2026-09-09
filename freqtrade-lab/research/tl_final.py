"""Final validation of the chosen long-term trendline config.

    python research/tl_final.py

The grid ranks configs on POOLED R multiples, which quietly assume every signal
could be taken. They cannot be. The live scan shows almost every coin's line
anchored in the same month, so alts break their trendlines together and an
account with ten slots misses most of a cluster. This is the check that says
what the account actually gets:

  * the account simulation at several concurrency caps, so the cost of the
    clustering is visible rather than assumed away
  * a year-by-year table, because a strategy that made all its money in one
    year is one observation, not a track record
  * the same run on fit coins and on held-out coins, separately
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness      # noqa: E402
import portfolio    # noqa: E402
import campaign     # noqa: E402
from tl_campaign import available  # noqa: E402
from tl_portfolio import collect, CAPITAL  # noqa: E402

# Chosen from the grid MARGINALS, not from the top of the fit ranking: each
# value is the best or joint-best average over every setting of the other
# dials, which is far harder to reach by luck than one good cell.
FINAL = dict(lookback=200, min_span=60, vol_mult=1.5, atr_mult=1.5,
             min_touches=3, touch_tol=0.03, min_drop_pct=0.25,
             stop_lookback=20, max_risk_pct=0.25, cooldown=20)
TRAIL_R, TIME_STOP = 3.0, 365


def main() -> None:
    coins = available(campaign.UNIVERSE)
    fit, hold = campaign.split(coins)
    print("# FINAL CONFIG")
    print(f"# {FINAL}\n# trail {TRAIL_R}R, time stop {TIME_STOP}d, "
          f"risk 1% of equity\n")

    sets = [("FIT coins", fit), ("HOLDOUT coins", hold), ("WHOLE universe", coins)]
    trades = {name: collect(cs, trail_r=TRAIL_R, time_stop=TIME_STOP, **FINAL)
              for name, cs in sets}

    print("## Cost of the clustering: how many signals a slot limit throws away")
    print("| coins | signals | max 5 open | max 10 | max 20 | max 40 |")
    print("|" + "---|" * 6)
    for name, _ in sets:
        tr = trades[name]
        cells = []
        for mo in (5, 10, 20, 40):
            a = portfolio.simulate_account(tr, CAPITAL, 0.01, mo)
            cells.append(f"{len(a)} ({len(a) / len(tr):.0%})" if tr else "-")
        print(f"| {name} | {len(tr)} | " + " | ".join(cells) + " |")

    for mo in (5, 10, 20):
        print(f"\n\n{'=' * 72}\n## Account at max {mo} open positions, 1% risk")
        print("| coins | fills | win% | avgR | total% | **CAGR%** | PF | "
              "**maxDD%** | best year | losing years |")
        print("|" + "---|" * 10)
        for name, _ in sets:
            tr = trades[name]
            a = portfolio.simulate_account(tr, CAPITAL, 0.01, mo)
            if a.empty:
                continue
            yrs = (a["exit"].max() - a["entry"].min()).days / 365.25
            s = portfolio.summary(a, yrs, CAPITAL)
            by = portfolio.by_year(a, CAPITAL)
            share = by["total_R"].max() / by["total_R"].sum() if by["total_R"].sum() else 0
            losing = int((by["return%"] < 0).sum())
            print(f"| {name} | {s['n']} | {s['win%']} | {s['avg_r']:+.2f} | "
                  f"{s['total%']:.0f} | **{s['cagr%']:.1f}** | {s['pf']} | "
                  f"**{s['max_dd%']:.1f}** | {share:.0%} of R | "
                  f"{losing}/{len(by)} |")

    print(f"\n\n{'=' * 72}\n## Year by year, whole universe, max 10 open")
    a = portfolio.simulate_account(trades["WHOLE universe"], CAPITAL, 0.01, 10)
    print(portfolio.by_year(a, CAPITAL).to_string())

    print(f"\n## Where the money came from (whole universe, max 10 open)")
    top = a.groupby("coin")["r"].agg(["count", "sum"]).sort_values("sum",
                                                                  ascending=False)
    print(f"coins traded: {len(top)}, total R {a['r'].sum():.1f}")
    print(f"best coin contributes {top['sum'].iloc[0]:.1f}R "
          f"({top['sum'].iloc[0] / a['r'].sum():.0%} of the total)")
    print(f"top 3 coins contribute {top['sum'].head(3).sum() / a['r'].sum():.0%}")
    print(top.head(8).to_string())

    print(f"\n## Single best trade")
    b = a.loc[a["r"].idxmax()]
    print(f"{b['coin']} {b['entry'].date()} -> {b['exit'].date()}: "
          f"{b['r']:.1f}R, {b['r'] / a['r'].sum():.0%} of all R")


if __name__ == "__main__":
    main()
