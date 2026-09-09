"""Re-score the grid's leading configs with the checks the ranking cannot make.

The grid ranks on pooled metrics built by concatenating each coin's trades in
turn. Any path-dependent statistic computed that way -- max_dd_r above all --
describes the order the coins were looped in, not the order the trades happened.
This re-pools chronologically and adds the per-year and per-coin views that
decide whether a headline number is an edge or an accident.

    python research/verify_grid.py [n_configs]
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness      # noqa: E402
import breakout     # noqa: E402
import campaign     # noqa: E402
import optimize     # noqa: E402

# The proven book, as documented in STRATEGY_DailyDivBreakout.md, expressed in
# the grid's own dials so the comparison is like for like.
BASELINE = {"side": "long", "wt2_max": -30.0, "trigger": "slope", "wait_bars": 8,
            "atr_mult": 1.0, "mfi_min": None, "gate": "none", "target": "3R",
            "require_hold": True}


def collect(coins: list[str], cfg: dict) -> tuple[list, dict, float]:
    """Every trade with the coin it came from, plus the span in years."""
    detail, bar, tstop = optimize.TFS["1d"]
    legs, be = optimize.PLANS[cfg["target"]]
    plan = harness.ExitPlan(legs=[tuple(x) for x in legs], be_after_leg=be,
                            time_stop_bars=tstop)
    rows, per_coin, span = [], {}, 0.0
    for c in coins:
        pair = f"{c}/USDT"
        try:
            base, det = harness.load(pair, "1d"), harness.load(pair, detail)
        except FileNotFoundError:
            continue
        gate, allow = optimize.gate_for(cfg["gate"], base, pair, cfg["side"])
        kw = dict(side=cfg["side"], wt2_max=cfg["wt2_max"], trigger=cfg["trigger"],
                  wait_bars=cfg["wait_bars"], atr_mult=cfg["atr_mult"],
                  mfi_min=cfg["mfi_min"], require_hold=cfg["require_hold"],
                  max_risk_pct=0.15)
        if gate is not None:
            kw["gate"], kw["gate_allow"] = gate, allow
        sig = breakout.divergence_breakout(base, **kw)
        if sig.empty:
            continue
        sig = sig[sig.index >= pd.Timestamp("2020-01-01", tz="UTC")]
        if sig.empty:
            continue
        tr = harness.simulate(sig, base, det, plan, base_bar=bar)
        if not tr:
            continue
        rows += [(c, t) for t in tr]
        per_coin[c] = tr
        span = max(span, (base.index[-1] - max(base.index[0],
                   pd.Timestamp("2020-01-01", tz="UTC"))).days / 365.25)
    return rows, per_coin, span


def dd(rs: np.ndarray) -> float:
    eq = np.cumsum(rs)
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    return float((peak - eq).max())


def report(name: str, cfg: dict, coins: list[str]) -> None:
    rows, per_coin, span = collect(coins, cfg)
    if not rows:
        print(f"\n### {name}: no trades")
        return
    by_coin_order = np.array([t.r for _, t in rows])
    chrono = sorted(rows, key=lambda x: x[1].exit_time)
    by_time = np.array([t.r for _, t in chrono])

    total = by_time.sum()
    annual = total / span
    print(f"\n### {name}")
    print(f"  cfg           {cfg}")
    print(f"  trades {len(rows)} over {span:.1f}y  ({len(rows)/span:.1f}/yr)"
          f"  avg_r {by_time.mean():+.3f}  total {total:+.1f}R  annual {annual:+.2f}R")
    print(f"  maxDD_R  coin-order {dd(by_coin_order):.1f}"
          f"   CHRONOLOGICAL {dd(by_time):.1f}")
    print(f"  ratio annual/maxDD   coin-order {annual/max(dd(by_coin_order),1e-9):.2f}"
          f"   CHRONOLOGICAL {annual/max(dd(by_time),1e-9):.2f}")

    years = defaultdict(float)
    for _, t in rows:
        years[t.exit_time.year] += t.r
    ys = sorted(years)
    print("  per year      " + "  ".join(f"{y}:{years[y]:+.1f}" for y in ys))
    best = max(years.values())
    print(f"  best year is {100*best/total:.0f}% of all profit"
          f"   losing years {sum(1 for y in ys if years[y] < 0)}/{len(ys)}")

    sizes = sorted((len(v) for v in per_coin.values()), reverse=True)
    pos = sum(1 for v in per_coin.values() if sum(t.r for t in v) > 0)
    top3 = sum(sorted((sum(t.r for t in v) for v in per_coin.values()),
                      reverse=True)[:3])
    print(f"  coins with trades {len(per_coin)}   positive {pos}/{len(per_coin)}"
          f"   biggest 3 coins are {100*top3/total:.0f}% of all profit")
    print(f"  trades per coin  max {sizes[0]}  median {int(np.median(sizes))}")


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    coins = [c for c in campaign.UNIVERSE
             if (harness.DATA_DIR / f"{c}_USDT-1d.feather").exists()
             and (harness.DATA_DIR / f"{c}_USDT-1h.feather").exists()]
    fit, hold = campaign.split(coins)
    print(f"universe {len(coins)}  fit {len(fit)}  holdout {len(hold)}")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import opt_report
    rows = opt_report.load("1d")
    top = sorted(rows, key=lambda r: -r["hold"].get("annual_r", 0))[:n]

    print("\n" + "=" * 70 + "\nBASELINE: DailyDivBreakout, the proven book\n" + "=" * 70)
    report("baseline / HOLDOUT", BASELINE, hold)
    report("baseline / FIT", BASELINE, fit)

    for i, r in enumerate(top, 1):
        print("\n" + "=" * 70 + f"\nGRID WINNER #{i}\n" + "=" * 70)
        report(f"winner {i} / HOLDOUT", r["cfg"], hold)
        report(f"winner {i} / FIT", r["cfg"], fit)


if __name__ == "__main__":
    main()
