"""Step 3: stack TrendlineBreakout with DailyDivBreakout and measure the result.

    python research/stack.py [max_open]

Two books, one universe, different triggers, both positive on held-out coins.
Nothing has measured their correlation. The question is not "do they both make
money" -- that is already known -- but whether they make it at the SAME TIMES.

The metric that decides it is the ratio annual_R / maxDD_R. Stacking helps only
if pooling the two raises that ratio above the better of the two alone. If the
books are correlated, the drawdowns land together, the ratio does not move, and
running both is just the same bet at double size.

Both books are collected at their best known settings:

  trendline   tl_final.FINAL, 3R trailing stop, 365-day time stop
  divergence  the grid's finding -- 2xATR stop and a 4R target, which the
              handover records as ratio 0.52 against 0.36 for the shipped
              1xATR/3R. Section 5 of the handover, not yet shipped to the
              freqtrade strategy file.

Sizing uses tl_account.simulate_honest, which credits profit at EXIT. The older
portfolio.py credits at entry and overstated a 74-day-hold book by 4.6 CAGR
points; the trendline book holds that long, so the distinction matters here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness      # noqa: E402
import breakout     # noqa: E402
import campaign     # noqa: E402
import portfolio    # noqa: E402
from tl_campaign import available            # noqa: E402
from tl_portfolio import collect as tl_collect, CAPITAL  # noqa: E402
from tl_final import FINAL, TRAIL_R, TIME_STOP           # noqa: E402
from tl_account import simulate_honest                   # noqa: E402

START = pd.Timestamp("2020-01-01", tz="UTC")
BAR = pd.Timedelta("1D")

# The divergence book at the grid's improved dials -- copied verbatim from
# GRID WINNER #1 in results/VERIFY_1d.txt. The handover calls this cell
# "2xATR + 4R", which is incomplete: it also moves wt2_max from -30 to -20,
# wait_bars from 8 to 16, and require_hold from True to False. Using only the
# stop and target changes leaves 15 fit signals instead of 84.
DIV = dict(trigger="slope", wt2_max=-20.0, wait_bars=16, atr_mult=2.0,
           require_hold=False, max_risk_pct=0.15)
DIV_TARGET_R = 4.0
DIV_TIME_STOP = 60


def div_collect(coins: list[str]) -> list:
    plan = harness.ExitPlan(legs=[(DIV_TARGET_R, 1.0)],
                            time_stop_bars=DIV_TIME_STOP)
    out = []
    for c in coins:
        pair = f"{c}/USDT"
        try:
            base, det = harness.load(pair, "1d"), harness.load(pair, "1h")
        except FileNotFoundError:
            continue
        sig = breakout.divergence_breakout(base, side="long", **DIV)
        if sig.empty:
            continue
        sig = sig[sig.index >= START]
        if sig.empty:
            continue
        for tr in harness.simulate(sig, base, det, plan, base_bar=BAR):
            out.append((tr, c))
    return out


def pooled_stats(trades: list) -> dict:
    """Order-independent edge, plus date-ordered drawdown, plus the ratio."""
    if not trades:
        return {"n": 0}
    tr = [t for t, _ in trades]
    m = harness.metrics(tr)
    lo = min(t.entry_time for t in tr)
    hi = max(t.exit_time for t in tr)
    years = (hi - lo).days / 365.25
    m["years"] = round(years, 2)
    m["per_year"] = round(m["n"] / years, 1)
    m["annual_r"] = round(m["n"] * m["avg_r"] / years, 2)
    m["ratio"] = (round(m["annual_r"] / m["max_dd_r"], 2)
                  if m["max_dd_r"] > 0 else float("inf"))
    return m


def monthly_r(trades: list) -> pd.Series:
    """R booked per calendar month, dated at EXIT -- when the money lands."""
    if not trades:
        return pd.Series(dtype=float)
    df = pd.DataFrame([{"exit": t.exit_time, "r": t.r} for t, _ in trades])
    return df.set_index("exit")["r"].resample("MS").sum()


def main() -> None:
    max_open = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    coins = available(campaign.UNIVERSE)
    fit, hold = campaign.split(coins)

    print(f"# Stacking two books — {len(coins)} coins, "
          f"FIT {len(fit)} / HOLDOUT {len(hold)}, max {max_open} open\n")

    books = {}
    for name, cs in (("FIT", fit), ("HOLDOUT", hold), ("ALL", coins)):
        tl = tl_collect(cs, trail_r=TRAIL_R, time_stop=TIME_STOP, **FINAL)
        dv = div_collect(cs)
        books[name] = {"trendline": tl, "divergence": dv, "stacked": tl + dv}

    # ---------------------------------------------------------------- pooled
    print("## Pooled edge and the ratio that decides it\n")
    print("| coins | book | signals | /yr | win% | avgR | annual_R | maxDD_R "
          "| **ratio** | PF |")
    print("|" + "---|" * 10)
    for name in ("FIT", "HOLDOUT", "ALL"):
        for b in ("trendline", "divergence", "stacked"):
            s = pooled_stats(books[name][b])
            if not s.get("n"):
                print(f"| {name} | {b} | 0 |" + " — |" * 7)
                continue
            print(f"| {name} | {'**' + b + '**' if b == 'stacked' else b} | "
                  f"{s['n']} | {s['per_year']} | {s['win_net_pct']} | "
                  f"{s['avg_r']:+.3f} | {s['annual_r']:+.2f} | {s['max_dd_r']} | "
                  f"**{s['ratio']}** | {s['pf']} |")

    # ----------------------------------------------------------- correlation
    print("\n## Do they make money at the same times?\n")
    a = monthly_r(books["ALL"]["trendline"])
    b = monthly_r(books["ALL"]["divergence"])
    j = pd.concat([a.rename("trendline"), b.rename("divergence")],
                  axis=1).fillna(0.0)
    j = j.loc[(j != 0).any(axis=1)]
    corr = j["trendline"].corr(j["divergence"])
    both_up = int(((j["trendline"] > 0) & (j["divergence"] > 0)).sum())
    both_dn = int(((j["trendline"] < 0) & (j["divergence"] < 0)).sum())
    split = int(((j["trendline"] > 0) != (j["divergence"] > 0)).sum())
    print(f"- months with activity in either book: **{len(j)}**")
    print(f"- monthly R correlation: **{corr:+.3f}**")
    print(f"- both up {both_up} months · both down {both_dn} · "
          f"one up one down {split}")
    print(f"- trendline monthly R: mean {j['trendline'].mean():+.2f}, "
          f"sd {j['trendline'].std():.2f}")
    print(f"- divergence monthly R: mean {j['divergence'].mean():+.2f}, "
          f"sd {j['divergence'].std():.2f}")
    print(f"- stacked monthly R: mean {(j.sum(axis=1)).mean():+.2f}, "
          f"sd {(j.sum(axis=1)).std():.2f}")
    ideal = np.sqrt(j["trendline"].var() + j["divergence"].var())
    print(f"- stacked sd if perfectly uncorrelated would be {ideal:.2f}; "
          f"if perfectly correlated {j['trendline'].std() + j['divergence'].std():.2f}")

    # --------------------------------------------------------------- account
    print(f"\n## The account, honest sizing, max {max_open} open\n")
    print("| coins | book | fills | CAGR | max DD | **CAGR/DD** | ends at |")
    print("|" + "---|" * 7)
    accounts = {}
    for name in ("FIT", "HOLDOUT", "ALL"):
        for bk in ("trendline", "divergence", "stacked"):
            tr = books[name][bk]
            if not tr:
                continue
            acct = simulate_honest(tr, CAPITAL, 0.01, max_open)
            if acct.empty:
                continue
            yrs = (acct["exit"].max() - acct["entry"].min()).days / 365.25
            s = portfolio.summary(acct, yrs, CAPITAL)
            accounts[(name, bk)] = acct
            r = s["cagr%"] / s["max_dd%"] if s["max_dd%"] > 0 else float("inf")
            print(f"| {name} | {'**' + bk + '**' if bk == 'stacked' else bk} | "
                  f"{s['n']} | {s['cagr%']:.2f}% | {s['max_dd%']:.2f}% | "
                  f"**{r:.2f}** | {s['end']:,} |")

    # ------------------------------------------------------------- per year
    print(f"\n## Year by year, whole universe, rupees on 1 lac\n")
    print("| year | trendline | divergence | **stacked** | stacked return |")
    print("|" + "---|" * 5)
    tabs = {bk: portfolio.by_year(accounts[("ALL", bk)], CAPITAL)
            for bk in ("trendline", "divergence", "stacked")
            if ("ALL", bk) in accounts}
    years = sorted(set().union(*[set(t.index) for t in tabs.values()]))
    for y in years:
        cells = []
        for bk in ("trendline", "divergence", "stacked"):
            t = tabs.get(bk)
            if t is not None and y in t.index:
                v = f"{t.loc[y, 'pnl']:+,.0f}"
                cells.append(f"**{v}**" if bk == "stacked" else v)
            else:
                cells.append("—")
        t = tabs.get("stacked")
        ret = (f"{t.loc[y, 'return%']:+.1f}%"
               if t is not None and y in t.index else "—")
        print(f"| {y} | " + " | ".join(cells) + f" | {ret} |")


if __name__ == "__main__":
    main()
