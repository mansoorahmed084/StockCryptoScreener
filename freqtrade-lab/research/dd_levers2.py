"""Phase B, step 2: tighter trails after a big gain, and risk throttles.

    python research/dd_levers2.py

dd_levers.py showed that each large drawdown splits roughly evenly between two
causes: open profit handed back by trades already running at the high, and a
run of stop-outs on trades opened while alts fell. The cheap levers (slots,
risk, capital cap, BTC trend) did not raise CAGR / drawdown on both halves.
This tries the two levers aimed at those causes directly:

  give-back   tighten the 25% trail once a trade is far in profit
              (harness.ExitPlan.tighten_at / trail_pct_tight -- a new price walk)
  stop-outs   cut risk after a losing streak, or while the account is in a
              closed-trade drawdown (throttles -- no new price walk)

The scoring is stricter than a single number. Each lever runs on all coins, on
the fit and held-out halves, and on 100 random 38-coin baskets that are paired
with the baseline on the SAME coins. A lever passes only if it raises
CAGR / drawdown on both halves AND on at least 60% of the random baskets.
Drawdown always values open trades at every daily close.
"""
from __future__ import annotations

import hashlib
import pickle
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness      # noqa: E402
import baskets      # noqa: E402
import campaign     # noqa: E402
import refine       # noqa: E402
import rf_final     # noqa: E402
from tl_final import FINAL        # noqa: E402
from tl_portfolio import CAPITAL  # noqa: E402

RES = Path(__file__).resolve().parent / "results"
M, YEARS = baskets.MARKS, baskets.YEARS
HOUR = pd.Timedelta("1h")

EXITS = {
    "baseline: trail 25%": dict(trail_pct=0.25),
    "tighten to 15% after +50%": dict(trail_pct=0.25, tighten_at=0.5, trail_pct_tight=0.15),
    "tighten to 15% after +100%": dict(trail_pct=0.25, tighten_at=1.0, trail_pct_tight=0.15),
    "tighten to 10% after +100%": dict(trail_pct=0.25, tighten_at=1.0, trail_pct_tight=0.10),
    "tighten to 10% after +200%": dict(trail_pct=0.25, tighten_at=2.0, trail_pct_tight=0.10),
}
THROTTLES = {
    "halve risk after 3 losses in a row": ("streak", 3, 0.5),
    "halve risk after 5 losses in a row": ("streak", 5, 0.5),
    "halve risk while 10% below the high": ("dd", 0.10, 0.5),
    "halve risk while 20% below the high": ("dd", 0.20, 0.5),
}


# ------------------------------------------------------------------- walks
def walk(coins: list[str], plan_kw: dict) -> dict[str, list]:
    """Every coin's trades under one exit plan, 15m fills, cached."""
    key = repr((sorted(FINAL.items()), sorted(rf_final.REFINED.items()),
                sorted(plan_kw.items()), rf_final.TIME_STOP_H, "15m"))
    p = RES / f"ddl2_trades_{hashlib.md5(key.encode()).hexdigest()[:10]}.pkl"
    if p.exists():
        return pickle.loads(p.read_bytes())
    plan = harness.ExitPlan(legs=[(100.0, 1.0)], time_stop_bars=rf_final.TIME_STOP_H,
                            **plan_kw)
    out = {}
    for c in coins:
        out[c] = []
        ds = rf_final.daily_sig(c)
        if ds.empty:
            continue
        h = harness.load(f"{c}/USDT", "1h")
        sig = refine.refined_signals(ds, h, **rf_final.REFINED)
        if sig.empty:
            continue
        out[c] = harness.simulate(sig, h, harness.load(f"{c}/USDT", "15m"), plan,
                                  base_bar=HOUR)
    p.write_bytes(pickle.dumps(out))
    return out


# ----------------------------------------------------------------- account
def simulate(trades: list, risk: float = 0.01, max_open: int = 10,
             cap: float = 1.0, throttle: tuple | None = None) -> pd.DataFrame:
    """tl_account.simulate_honest, plus an optional risk throttle.

    throttle = ("streak", n, k): after n losing closes in a row, risk x k until
               a winner closes.
    throttle = ("dd", x, k):     while closed-trade equity is at least x below
               its high, risk x k.
    Only CLOSED trades feed the throttle, so it never uses anything the account
    could not know at the moment of entry.
    """
    idx = sorted(range(len(trades)), key=lambda i: trades[i][0].entry_time)
    equity = peak = CAPITAL
    streak, exposure, j = 0, 0.0, 0
    open_: dict[int, tuple[float, float]] = {}
    rows = []
    while j < len(idx) or open_:
        nxt_exit = min((trades[i][0].exit_time for i in open_), default=None)
        nxt_entry = trades[idx[j]][0].entry_time if j < len(idx) else None
        if nxt_exit is not None and (nxt_entry is None or nxt_exit <= nxt_entry):
            i = min(open_, key=lambda i: trades[i][0].exit_time)
            stake, notional = open_.pop(i)
            t, c = trades[i]
            exposure -= notional
            pnl = stake * t.r
            equity += pnl
            peak = max(peak, equity)
            streak = streak + 1 if t.r < 0 else 0
            rows.append({"i": i, "entry": t.entry_time, "exit": t.exit_time,
                         "coin": c, "r": t.r, "pnl": pnl, "notional": notional})
            continue
        i = idx[j]
        j += 1
        if len(open_) >= max_open:
            continue
        t, c = trades[i]
        r = risk
        if throttle is not None:
            kind, x, k = throttle
            if (kind == "streak" and streak >= x) or \
                    (kind == "dd" and equity <= peak * (1 - x)):
                r = risk * k
        want = equity * r
        stop_pct = (t.entry - t.stop) / t.entry
        notional = want / stop_pct if stop_pct > 0 else 0.0
        room = cap * equity - exposure
        if room < 0.25 * notional:
            continue
        if room < notional:
            want *= room / notional
            notional = room
        open_[i] = (want, notional)
        exposure += notional
    return (pd.DataFrame(rows).sort_values("exit").reset_index(drop=True)
            if rows else pd.DataFrame())


def score(tbc: dict, paths: dict, coins: list[str],
          throttle: tuple | None = None) -> dict | None:
    trades = [(t, c) for c in coins for t in tbc.get(c, [])]
    if not trades:
        return None
    acct = simulate(trades, throttle=throttle)
    if acct.empty:
        return None
    ex = pd.DatetimeIndex(acct["exit"])
    order = np.argsort(ex.asi8)
    cum = np.concatenate([[0.0], np.cumsum(acct["pnl"].to_numpy()[order])])
    realised = CAPITAL + cum[ex[order].searchsorted(M, side="right")]
    unreal = np.zeros(len(M))
    for i, n in zip(acct["i"], acct["notional"]):
        t, c = trades[i]
        unreal += n * paths[(t.entry_time, c)]
    mtm = realised + unreal
    cagr = 100 * ((mtm[-1] / CAPITAL) ** (1 / YEARS) - 1) if mtm[-1] > 0 else -100.0
    dd = baskets.mdd(mtm)
    return {"CAGR": cagr, "DD": dd, "ratio": cagr / dd if dd > 0 else np.nan,
            "fills": len(acct)}


# -------------------------------------------------------------------- main
def main() -> None:
    coins = rf_final.coins_available()
    fit, hold = campaign.split(coins)
    rng = random.Random(3)
    rand38 = [rng.sample(coins, 38) for _ in range(100)]

    walks = {}
    for name, kw in EXITS.items():
        walks[name] = walk(coins, kw)
        print(f"  walked: {name}", file=sys.stderr, flush=True)
    paths = {name: baskets.return_paths(tbc) for name, tbc in walks.items()}

    # The default-off harness change must not move the baseline: compare with
    # the trades cached by baskets.py before tighten_at existed.
    old = baskets.all_trades(coins)
    base = walks["baseline: trail 25%"]
    same = all([round(t.r, 9) for t in base[c]] == [round(t.r, 9) for t in old[c]]
               for c in coins)
    print(f"baseline trades identical to baskets.py cache: {same}", file=sys.stderr)

    variants = [(n, n, None) for n in EXITS] + \
               [(n, "baseline: trail 25%", th) for n, th in THROTTLES.items()]

    ref = {}
    md = ["# Phase B, step 2: tighter trails after a big gain, and risk throttles", "",
          "Research engine, 15m fills, 10 slots, 1% risk, capital cap 100%, "
          "drawdown with open trades valued daily. `ratio` = CAGR / real drawdown. "
          "`random 38`: 100 random 38-coin baskets, each paired with the baseline "
          "on the same coins.", "",
          f"Baseline trades identical to the baskets.py cache: **{same}**.", "",
          "| lever | ALL CAGR | ALL real DD | **ALL ratio** | **FIT ratio** | "
          "**HOLD ratio** | random 38: baskets with a better ratio | median ratio change | "
          "median CAGR change | median DD change | passes |",
          "|" + "---|" * 11]
    for name, walk_name, th in variants:
        tbc, pth = walks[walk_name], paths[walk_name]
        a = score(tbc, pth, coins, th)
        f = score(tbc, pth, fit, th)
        h = score(tbc, pth, hold, th)
        rnd = [score(tbc, pth, b, th) for b in rand38]
        if not ref:
            ref = {"a": a, "f": f, "h": h, "rnd": rnd}
            better = "-"
            d_ratio = d_cagr = d_dd = "-"
            passes = "reference"
        else:
            pairs = [(x, y) for x, y in zip(rnd, ref["rnd"]) if x and y]
            better = f"{100*np.mean([x['ratio'] > y['ratio'] for x, y in pairs]):.0f}%"
            d_ratio = f"{np.median([x['ratio'] - y['ratio'] for x, y in pairs]):+.2f}"
            d_cagr = f"{np.median([x['CAGR'] - y['CAGR'] for x, y in pairs]):+.1f}"
            d_dd = f"{np.median([x['DD'] - y['DD'] for x, y in pairs]):+.1f}"
            ok = (f["ratio"] > ref["f"]["ratio"] and h["ratio"] > ref["h"]["ratio"]
                  and np.mean([x["ratio"] > y["ratio"] for x, y in pairs]) >= 0.6)
            passes = "**yes**" if ok else "no"
        md.append(f"| {name} | {a['CAGR']:.1f}% | {a['DD']:.1f}% | **{a['ratio']:.2f}** | "
                  f"**{f['ratio']:.2f}** | **{h['ratio']:.2f}** | {better} | {d_ratio} | "
                  f"{d_cagr} | {d_dd} | {passes} |")
        print(f"  scored: {name}", file=sys.stderr, flush=True)

    out = RES / "dd_levers2.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
