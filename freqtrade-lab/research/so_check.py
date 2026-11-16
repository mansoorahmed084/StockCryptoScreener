"""Second round for the Signals & Overlays (own build) candidates
(SIGNALS_OVERLAYS_RESEARCH.md).

    python research/so_check.py            # all coins
    python research/so_check.py --quick    # 5 + 5 coins, to check it runs

1. Plateau, on the OLD 76 coins only: move one dial at a time around each
   candidate (sensitivity, target, time stop, stop width, side, strong only,
   Smart Trail period). A real edge sits on a plateau; a lucky one on a spike.
2. Against SMC sweep-break (B_final), on all coins and on the new 203:
   monthly R correlation, losing-month overlap, and one shared account
   (0.5% risk per trade) for each book alone and both together, plus both
   together at 0.25% risk to compare at a similar drawdown.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smc           # noqa: E402
import smc_account   # noqa: E402
import smc_oos       # noqa: E402
import signals_overlays as so  # noqa: E402

CANDS = {
    "4h_trail": so.Cfg(tf="4h", mode="conf", side="both", exit="3R", filt="trail"),
    "1d_all": so.Cfg(tf="1d", mode="conf", side="both", exit="3R"),
}
DIALS = [("sens", (8, 12, 16, 20)), ("tp_r", (2.0, 3.0, 4.0, 6.0)),
         ("max_hold", (21, 42, 84)), ("stop_atr", (1.5, 2.0, 3.0)),
         ("side", ("both", "long")), ("strong", (False, True))]
TRAIL_P = (2, 3, 4)          # Smart Trail period, for the candidate that uses it
OUT = Path(__file__).resolve().parent / "results" / "so_check.json"
COLS = ["coin", "entry_time", "exit_time", "r", "risk_pct"]


def plateau(old: list[str]) -> list[dict]:
    fit, hold = (set(x) for x in smc.split(old))
    jobs = []                # (candidate, dial, value, config, Smart Trail period)
    for name, cand in CANDS.items():
        for k, vals in DIALS:
            jobs += [(name, k, v, replace(cand, **{k: v}), 3) for v in vals]
        if cand.filt == "trail":
            jobs += [(name, "trail_p", p, cand, p) for p in TRAIL_P]
    parts: list[list] = [[] for _ in jobs]
    for coin in old:
        books: dict = {}
        for i, (_, _, _, cfg, p) in enumerate(jobs):
            key = (cfg.tf, p)
            if key not in books:
                df = smc.bars(coin, cfg.tf, so.BASE)
                books[key] = so.Book(df, trail_p=p) if len(df) > so.WARMUP + 50 else None
            if books[key] is None:
                continue
            tr = so.run(coin, cfg, books[key])
            if len(tr):
                parts[i].append(tr)
        smc.bars.cache_clear()
        smc.harness._FRAMES.pop((f"{coin}/USDT", so.BASE), None)
    rows = []
    for (name, k, v, _, _), p in zip(jobs, parts):
        t = pd.concat(p, ignore_index=True)
        m = smc.metrics(t)
        a = smc_account.account(t, risk=0.005)
        rs = t.r.sort_values(ascending=False)
        row = {"cand": name, "dial": k, "value": v, "n": m["n"], "avg_r": m["avg_r"],
               "pf": m["pf"], "fit": smc.metrics(t[t.coin.isin(fit)])["avg_r"],
               "hold": smc.metrics(t[t.coin.isin(hold)])["avg_r"],
               "trim1": round(float(rs.iloc[len(rs) // 100:].mean()), 3),
               "yrs_pos": m["yrs_pos"], "cagr": a["cagr"], "dd": a["dd_worst"]}
        rows.append(row)
        print(f"  {name:9s} {k:8s}={str(v):5s} n={m['n']:6d} avgR={m['avg_r']:+.3f} "
              f"pf={m['pf']:.2f} fit={row['fit']:+.3f} hold={row['hold']:+.3f} "
              f"trim1={row['trim1']:+.3f} yrs={m['yrs_pos']} cagr={a['cagr']} "
              f"dd={a['dd_worst']}", flush=True)
    return rows


def b_final(coins: list[str]) -> pd.DataFrame:
    fr = [smc.run(c, smc_oos.FINALISTS["B_final"], "1h") for c in coins]
    fr = [f for f in fr if len(f)]
    return pd.concat(fr, ignore_index=True)


def monthly(t: pd.DataFrame) -> pd.Series:
    return t.groupby(t.exit_time.dt.tz_localize(None).dt.to_period("M"))["r"].sum()


def accounts(books: dict[str, pd.DataFrame], risk: float = 0.005) -> dict:
    out = {}
    for name, t in books.items():
        for slots in (10, 20):
            acc = smc_account.account(t, risk=risk, slots=slots)
            x = {k: acc[k] for k in ("trades", "skipped", "cagr", "dd_closed",
                                     "dd_worst", "years")}
            x["ratio"] = round(x["cagr"] / x["dd_worst"], 2) if x["dd_worst"] else None
            out[f"{name}_s{slots}"] = x
            print(f"  {name:12s} slots={slots}: trades {x['trades']:5d} skipped "
                  f"{x['skipped']:5d} CAGR {x['cagr']}% worstDD {x['dd_worst']}% "
                  f"ratio {x['ratio']} years {x['years']}", flush=True)
    return out


def versus(sb: pd.DataFrame, other: pd.DataFrame, name: str, label: str) -> dict:
    a, b = sb[COLS].copy(), other[COLS].copy()
    m = pd.concat([monthly(a).rename("sb"), monthly(b).rename("x")], axis=1).fillna(0.0)
    out = {
        "months": len(m),
        "corr_monthly": round(float(m.sb.corr(m.x)), 3),
        "sb_losing_months": int((m.sb < 0).sum()),
        "x_losing_months": int((m.x < 0).sum()),
        "both_losing_months": int(((m.sb < 0) & (m.x < 0)).sum()),
        "x_total_r_when_sb_loses": round(float(m.x[m.sb < 0].sum()), 1),
        "x_avg_r_when_sb_loses": round(float(m.x[m.sb < 0].mean()), 2),
    }
    print(f"\n{label} | {name}: monthly corr {out['corr_monthly']}, losing months "
          f"sweep-break {out['sb_losing_months']} / {name} {out['x_losing_months']} / "
          f"both {out['both_losing_months']} of {out['months']}; {name} total R in "
          f"sweep-break's losing months {out['x_total_r_when_sb_loses']}", flush=True)
    out["accounts"] = accounts({"sweep-break": a, name: b, "both": pd.concat([a, b])})
    # the same two books at half the risk per trade, to compare at a similar drawdown
    print("  at 0.25% risk per trade:", flush=True)
    out["accounts_half_risk"] = accounts({"both": pd.concat([a, b])}, risk=0.0025)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    q = ap.parse_args().quick
    old = [c for c in smc.UNIVERSE if smc.have(c, so.BASE)]
    new = smc_oos.new_coins()
    if q:
        old, new = old[:5], new[:5]
    res: dict = {}
    print(f"PLATEAU (old {len(old)} coins only)", flush=True)
    res["plateau"] = plateau(old)
    allc = old + new
    print(f"\nsweep-break on {len(allc)} coins ...", flush=True)
    sb = b_final(allc)
    t = so.collect(allc, list(CANDS.values()))
    for name, cfg in CANDS.items():
        x = t[cfg]
        res[name] = {
            "all": versus(sb, x, name, f"ALL {len(allc)} coins"),
            "new": versus(sb[sb.coin.isin(new)], x[x.coin.isin(new)], name,
                          f"NEW {len(new)} coins"),
        }
    # the two candidates against each other, and all three books in one account
    a, b = (t[c] for c in CANDS.values())
    m = pd.concat([monthly(a).rename("a"), monthly(b).rename("b")], axis=1).fillna(0.0)
    res["cand_corr_monthly"] = round(float(m.a.corr(m.b)), 3)
    print(f"\n4h_trail vs 1d_all monthly corr {res['cand_corr_monthly']}", flush=True)
    for label, pick in (("ALL", allc), ("NEW", new)):
        print(f"\n{label}: all three books in one account", flush=True)
        both = pd.concat([sb[sb.coin.isin(pick)][COLS], a[a.coin.isin(pick)][COLS],
                          b[b.coin.isin(pick)][COLS]])
        res[f"three_{label.lower()}"] = accounts({"all three": both})
        print("  at 0.25% risk per trade:", flush=True)
        res[f"three_{label.lower()}_half_risk"] = accounts({"all three": both}, risk=0.0025)
    OUT.write_text(json.dumps(res, default=str, indent=1))


if __name__ == "__main__":
    main()
