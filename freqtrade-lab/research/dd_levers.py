"""Where TrendlineBreakoutLTF's drawdown comes from, and what cheap levers do.

    python research/dd_levers.py

Phase B: cut the ~40% real drawdown without killing the return. Before
tuning anything, this answers two questions from the cached basket trades.

1. **Anatomy of every drawdown over 15%.** How much was open profit given back
   versus money lost on trades opened during the fall? How invested was the
   account at the top? What were BTC and the median coin doing? The answer
   decides which lever can work at all: a tighter trail attacks give-back, a
   market-trend gate attacks bad new entries, fewer slots or a lower capital
   cap attacks concentration.
2. **A first map of levers that need no new price walk.** They only change
   which cached trades the account takes, and how big: slots, risk per trade,
   the capital cap, and a BTC trend gate on entries.

Every lever is scored on all coins AND on the fit and held-out halves. A lever
that helps only one half is noise, not a lever.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness      # noqa: E402
import baskets      # noqa: E402
import campaign     # noqa: E402
import rf_final     # noqa: E402
import tl_account   # noqa: E402
from tl_portfolio import CAPITAL  # noqa: E402

M = baskets.MARKS
YEARS = baskets.YEARS
RES = Path(__file__).resolve().parent / "results"


# ------------------------------------------------------------------ account
def account(trades: list, paths: dict, max_open: int = 10, risk: float = 0.01,
            cap: float = 1.0):
    """Run the account and rebuild its daily equity with open trades valued."""
    acct = tl_account.simulate_honest(trades, CAPITAL, risk, max_open,
                                      max_exposure=cap)
    if acct.empty:
        return None
    ex = pd.DatetimeIndex(acct["exit"])
    order = np.argsort(ex.asi8)
    exits = ex[order]
    cum = np.concatenate([[0.0], np.cumsum(acct["pnl"].to_numpy()[order])])
    realised = CAPITAL + cum[exits.searchsorted(M, side="right")]
    byk = {(t.entry_time, c): t for t, c in trades}
    unreal = np.zeros(len(M))
    pos = []
    for e, c, pnl in zip(acct["entry"], acct["coin"], acct["pnl"]):
        t = byk[(e, c)]
        u = t.notional * paths[(e, c)]
        unreal += u
        pos.append({"entry": e, "coin": c, "exit": t.exit_time,
                    "notional": t.notional, "r": t.r, "pnl": pnl, "u": u})
    return {"acct": acct, "realised": realised, "unreal": unreal,
            "mtm": realised + unreal, "pos": pos}


def stats(run: dict | None) -> dict:
    if run is None:
        return {"fills": 0}
    mtm = run["mtm"]
    cagr = 100 * ((mtm[-1] / CAPITAL) ** (1 / YEARS) - 1) if mtm[-1] > 0 else -100.0
    dd = baskets.mdd(mtm)
    return {"fills": len(run["acct"]), "CAGR": cagr, "DD": dd,
            "closedDD": baskets.mdd(run["realised"]),
            "ratio": cagr / dd if dd > 0 else float("nan")}


# ---------------------------------------------------------------- anatomy
def episodes(mtm: np.ndarray, min_dd: float = 0.15) -> list[tuple]:
    out, p, worst, q = [], 0, 0.0, None
    for i, v in enumerate(mtm):
        if v >= mtm[p]:
            if worst >= min_dd:
                out.append((p, q, i, worst))
            p, worst, q = i, 0.0, None
        else:
            d = (mtm[p] - v) / mtm[p]
            if d > worst:
                worst, q = d, i
    if worst >= min_dd:
        out.append((p, q, None, worst))
    return out


def anatomy(run: dict, coins: list[str]) -> list[str]:
    mtm, realised, unreal = run["mtm"], run["realised"], run["unreal"]
    btc = harness.load("BTC/USDT", "1d")["close"]
    sma = btc.rolling(200).mean()
    closes = {c: harness.load(f"{c}/USDT", "1d")["close"] for c in coins}

    def px(series, i):
        bar = M[i] - pd.Timedelta("1D")          # the bar that closed at mark i
        return float(series.get(bar, np.nan))

    lines = ["| drop | high | low | recovered | invested at high | open trades at high | "
             "open profit at high | **given back by trades open at high** | "
             "**lost on trades opened during the fall** | trades opened in fall (stopped) | "
             "BTC over the fall | median coin | BTC above 200d avg at high |",
             "|" + "---|" * 13]
    for p, q, r, worst in episodes(mtm):
        tp, tq = M[p], M[q]
        at_high = [x for x in run["pos"] if x["entry"] < tp < x["exit"]]
        during = [x for x in run["pos"] if tp <= x["entry"] < tq]

        def value_change(x, start_u):
            end = x["u"][q] if x["exit"] > tq else x["pnl"]
            return end - start_u

        # Both counted as LOSSES over the fall: positive when the group lost money.
        give_back = -sum(value_change(x, x["u"][p]) for x in at_high)
        fall_new = -sum(value_change(x, 0.0) for x in during)
        stopped = sum(1 for x in during if x["exit"] <= tq and x["r"] < 0)
        invested = sum(x["notional"] for x in at_high) / mtm[p]
        coin_moves = [px(closes[c], q) / px(closes[c], p) - 1 for c in coins
                      if np.isfinite(px(closes[c], p)) and np.isfinite(px(closes[c], q))]
        drop_usd = mtm[p] - mtm[q]
        lines.append(
            f"| {100*worst:.1f}% | {tp.date()} | {tq.date()} | "
            f"{M[r].date() if r is not None else 'not yet'} | {100*invested:.0f}% | "
            f"{len(at_high)} | {100*sum(x['u'][p] for x in at_high)/mtm[p]:+.1f}% of account | "
            f"**{100*give_back/drop_usd:.0f}% of the drop** | "
            f"**{100*fall_new/drop_usd:.0f}% of the drop** | {len(during)} ({stopped}) | "
            f"{100*(px(btc, q)/px(btc, p)-1):+.0f}% | {100*np.median(coin_moves):+.0f}% | "
            f"{'yes' if px(btc, p) > px(sma, p) else 'no'} |")
    lines += ["", "Both shares are losses as a percent of the drop. Every position "
              "that moved the account between the high and the low is in one of the "
              "two groups, so the shares add up to about 100%. A share below 0% "
              "would mean that group made money during the fall."]
    return lines


# ----------------------------------------------------------------- levers
def btc_gate(trades: list, length: int) -> list:
    """Keep only entries made while BTC closed above its N-day average.

    The entry fills at 00:00 on day D+1; the last closed daily bar then is D,
    so the gate reads BTC's close and average through D -- nothing later.
    """
    btc = harness.load("BTC/USDT", "1d")["close"]
    up = btc > btc.rolling(length).mean()
    keep = []
    for t, c in trades:
        bar = t.entry_time.floor("D") - pd.Timedelta("1D")
        if bool(up.get(bar, False)):
            keep.append((t, c))
    return keep


def main() -> None:
    coins = rf_final.coins_available()
    fit, hold = campaign.split(coins)
    tbc = baskets.all_trades(coins)
    paths = baskets.return_paths(tbc)

    def trades_of(cs):
        return [(t, c) for c in cs for t in tbc[c]]

    md = ["# Phase B, step 1: where the drawdown comes from", "",
          "Research engine, cached 15m trades, 10 slots, 1% risk, capital cap 100%, "
          "open trades valued at every daily close. Same numbers as the all-coins "
          "row in `baskets.md`.", ""]

    base = account(trades_of(coins), paths)
    s = stats(base)
    md += [f"Baseline, all coins: CAGR {s['CAGR']:.1f}%, real drawdown {s['DD']:.1f}%, "
           f"closed-trade drawdown {s['closedDD']:.1f}%, {s['fills']} trades.", "",
           "## Every drawdown over 15%", ""]
    md += anatomy(base, coins)

    variants = [
        ("baseline: 10 slots, 1% risk, cap 100%", dict(), None),
        ("risk 0.75%", dict(risk=0.0075), None),
        ("risk 0.5%", dict(risk=0.005), None),
        ("5 slots", dict(max_open=5), None),
        ("8 slots", dict(max_open=8), None),
        ("15 slots", dict(max_open=15), None),
        ("cap 75% of account", dict(cap=0.75), None),
        ("cap 50% of account", dict(cap=0.5), None),
        ("BTC above 200-day average only", dict(), 200),
        ("BTC above 100-day average only", dict(), 100),
        ("BTC above 50-day average only", dict(), 50),
    ]
    md += ["", "## Cheap levers — no new price walk", "",
           "`ratio` is CAGR divided by real drawdown. A lever is worth pursuing "
           "only if it raises the ratio on BOTH halves, not just on all coins.", "",
           "| lever | ALL CAGR | ALL real DD | **ALL ratio** | FIT CAGR | FIT DD | "
           "**FIT ratio** | HOLD CAGR | HOLD DD | **HOLD ratio** | ALL trades |",
           "|" + "---|" * 11]
    for name, kw, gate in variants:
        cells = []
        for cs in (coins, fit, hold):
            tr = trades_of(cs)
            if gate:
                tr = btc_gate(tr, gate)
            cells.append(stats(account(tr, paths, **kw)))
        a, f, h = cells
        md.append(f"| {name} | {a['CAGR']:.1f}% | {a['DD']:.1f}% | **{a['ratio']:.2f}** | "
                  f"{f['CAGR']:.1f}% | {f['DD']:.1f}% | **{f['ratio']:.2f}** | "
                  f"{h['CAGR']:.1f}% | {h['DD']:.1f}% | **{h['ratio']:.2f}** | "
                  f"{a['fills']} |")
        print(f"  {name}: done", file=sys.stderr, flush=True)

    out = RES / "dd_levers.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
