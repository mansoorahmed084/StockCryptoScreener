"""SMC Sweep-Break (B_final) over one date window, with an account.

    python research/smc_window.py                  # the last 3 years on disk
    python research/smc_window.py 2024-01-01       # from a date to the data end
    python research/smc_window.py 2023-01-01 2024-01-01

Runs the unchanged strategy on all 279 coins (the 76 it was built on and the
203 never used) from 1h Binance candles, then keeps the trades ENTERED inside
the window. The structure needs no warm-up beyond the data before the window,
which the full run provides. The account starts at 1.0 on the window's first
day: risk per trade, at most 10 open, notional capped at 5x equity, profit
banked at exit (smc_account.py).
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smc           # noqa: E402
import smc_account   # noqa: E402
import smc_loop      # noqa: E402
import smc_oos       # noqa: E402

CFG = smc_oos.FINALISTS["B_final"]


def streak(rs: np.ndarray) -> int:
    worst = run = 0
    for r in rs:
        run = run + 1 if r <= 0 else 0
        worst = max(worst, run)
    return worst


def main(start: str | None, end: str | None) -> None:
    old = [c for c in smc.UNIVERSE if smc.have(c, "1h")]
    new = smc_oos.new_coins()
    stress = replace(CFG, cost=0.0010)
    tr = smc_loop.evaluate([CFG, stress], old + new, "1h", "window")
    data_end = max(t.exit_time.max() for t in tr.values())
    hi = pd.Timestamp(end, tz="UTC") if end else data_end
    lo = pd.Timestamp(start, tz="UTC") if start else hi - pd.DateOffset(years=3)
    pick = {k: t[(t.entry_time >= lo) & (t.entry_time < hi)].copy() for k, t in tr.items()}
    t = pick[0]
    t["set"] = np.where(t.coin.astype(str).isin(set(old)), "built on (76)", "never used (203)")

    print(f"\nSMC Sweep-Break, trades entered {lo:%Y-%m-%d} to {hi:%Y-%m-%d} "
          f"({(hi - lo).days / 365.25:.1f} years), {t.coin.nunique()} coins traded, "
          f"cost 0.06% per side\n")
    rows = {"all": t, "longs": t[t.dir > 0], "shorts": t[t.dir < 0],
            "built on (76)": t[t.set == "built on (76)"],
            "never used (203)": t[t.set == "never used (203)"],
            "all, cost 0.10%": pick[1]}
    out = []
    for name, x in rows.items():
        m = smc.metrics(x)
        r = x.r.to_numpy()
        out.append({"": name, "trades": m["n"], "win %": m["win"],
                    "hit 6R %": m["hit_tp"], "avg R": m["avg_r"],
                    "avg win": round(r[r > 0].mean(), 2) if (r > 0).any() else 0,
                    "avg loss": round(r[r <= 0].mean(), 2) if (r <= 0).any() else 0,
                    "PF": m["pf"], "total R": m["tot_r"], "per year": m["per_yr"]})
    pd.set_option("display.width", 200)
    print(pd.DataFrame(out).to_string(index=False))

    srt = t.sort_values("exit_time")
    print(f"\nExits: " + ", ".join(f"{k} {v:.0%}" for k, v in
                                  srt.why.value_counts(normalize=True).items()))
    print(f"Still open at the data end: {int((t.why == 'data_end').sum())} "
          f"(marked at the last close)")
    hold = (t.exit_time - t.entry_time).dt.total_seconds() / 86400
    print(f"Hold: median {hold.median():.1f} days. Stop distance: median "
          f"{100 * t.risk_pct.median():.1f}%. Worst losing streak: "
          f"{streak(srt.r.to_numpy())} trades in a row.")
    top = t.sort_values("r", ascending=False)
    print(f"Best 20 trades = {top.r.head(20).sum() / t.r.sum():.0%} of the total R.")

    print("\nBy 12-month period (avg R / trades / total R):")
    p = ((t.entry_time - lo).dt.days // 365).clip(upper=int((hi - lo).days // 365) - 1)
    for k, g in t.groupby(p):
        a = lo + pd.DateOffset(years=int(k))
        print(f"  {a:%b %Y} - {a + pd.DateOffset(years=1):%b %Y}: "
              f"{g.r.mean():+.2f}R / {len(g)} / {g.r.sum():+.1f}R, win {100 * (g.r > 0).mean():.0f}%")

    mon = srt.groupby(srt.exit_time.dt.to_period("M")).r.sum()
    print(f"\nMonths: {int((mon > 0).sum())} of {len(mon)} positive. "
          f"Best {mon.max():+.1f}R ({mon.idxmax()}), worst {mon.min():+.1f}R ({mon.idxmin()}).")

    print("\nAccount, starting at the window start (CAGR / max drawdown closed / "
          "worst case with every open trade stopped):")
    for risk in (0.005, 0.01):
        a = smc_account.account(t, risk=risk, slots=10, max_lev=5.0)
        yrs = ", ".join(f"{y}: {v:+.0f}%" for y, v in a["years"].items())
        print(f"  {risk:.1%} risk, 10 slots: x{a['final']} -> CAGR {a['cagr']}%, "
              f"DD {a['dd_closed']}% / {a['dd_worst']}%, trades {a['trades']} "
              f"(skipped {a['skipped']}). Calendar years: {yrs}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None,
         sys.argv[2] if len(sys.argv) > 2 else None)
