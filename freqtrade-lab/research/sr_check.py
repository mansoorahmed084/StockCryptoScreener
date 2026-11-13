"""Second round for the S&R Breaks candidate (SR_BREAKS_RESEARCH.md).

    python research/sr_check.py

1. Plateau, on the OLD 76 coins only: move one dial at a time around the
   candidate (pivot width, target, time stop, stop buffer, side). A real edge
   sits on a plateau; a lucky one sits on a spike.
2. Against SMC sweep-break (B_final), on all coins and on the new 203:
   monthly R correlation, losing-month overlap, and one shared account
   (0.5% risk per trade) for each book alone and both together.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smc           # noqa: E402
import smc_account   # noqa: E402
import smc_oos       # noqa: E402
import sr_breaks as sr  # noqa: E402

CAND = sr.Cfg(tf="4h", side="both", vol=False, wick=True, stop="support",
              exit="3R")
OUT = Path(__file__).resolve().parent / "results" / "sr_check.json"


def plateau(old: list[str]) -> list[dict]:
    dials = [("width", (10, 15, 20)), ("tp_r", (2.0, 3.0, 4.0, 6.0)),
             ("max_hold", (24, 42, 84)), ("sl_buf", (0.0, 0.1, 0.5)),
             ("side", ("both", "long"))]
    fit, hold = smc.split(old)
    rows = []
    for k, vals in dials:
        for v in vals:
            cfg = replace(CAND, **{k: v})
            t = sr.basket(old, cfg)
            m = smc.metrics(t)
            a = smc_account.account(t, risk=0.005)
            row = {"dial": k, "value": v, "n": m["n"], "avg_r": m["avg_r"],
                   "pf": m["pf"], "fit": smc.metrics(t[t.coin.isin(fit)])["avg_r"],
                   "hold": smc.metrics(t[t.coin.isin(hold)])["avg_r"],
                   "cagr": a["cagr"], "dd": a["dd_worst"]}
            rows.append(row)
            print(f"  {k:8s}={str(v):5s} n={m['n']:5d} avgR={m['avg_r']:+.3f} "
                  f"pf={m['pf']:.2f} fit={row['fit']:+.3f} hold={row['hold']:+.3f} "
                  f"cagr={a['cagr']} dd={a['dd_worst']}", flush=True)
    return rows


def b_final(coins: list[str]) -> pd.DataFrame:
    fr = [smc.run(c, smc_oos.FINALISTS["B_final"], "1h") for c in coins]
    fr = [f for f in fr if len(f)]
    return pd.concat(fr, ignore_index=True)


def versus(sb: pd.DataFrame, srt: pd.DataFrame, label: str) -> dict:
    cols = ["coin", "entry_time", "exit_time", "r", "risk_pct"]
    a, b = sb[cols].copy(), srt[cols].copy()
    ma = a.groupby(a.exit_time.dt.to_period("M"))["r"].sum()
    mb = b.groupby(b.exit_time.dt.to_period("M"))["r"].sum()
    m = pd.concat([ma.rename("sb"), mb.rename("sr")], axis=1).fillna(0.0)
    both_lose = int(((m.sb < 0) & (m.sr < 0)).sum())
    out = {
        "months": len(m),
        "corr_monthly": round(float(m.sb.corr(m.sr)), 3),
        "sb_losing_months": int((m.sb < 0).sum()),
        "sr_losing_months": int((m.sr < 0).sum()),
        "both_losing_months": both_lose,
        "sr_when_sb_loses": round(float(m.sr[m.sb < 0].mean()), 2),
    }
    for name, t in (("sb", a), ("sr", b), ("both", pd.concat([a, b]))):
        for slots in (10, 20):
            acc = smc_account.account(t, risk=0.005, slots=slots)
            out[f"{name}_s{slots}"] = {k: acc[k] for k in
                                       ("trades", "skipped", "cagr", "dd_closed",
                                        "dd_worst", "years")}
    print(f"\n{label}: monthly corr {out['corr_monthly']}, losing months "
          f"sb {out['sb_losing_months']} / sr {out['sr_losing_months']} / both "
          f"{both_lose} of {out['months']}; sr avg R in sb's losing months "
          f"{out['sr_when_sb_loses']}", flush=True)
    for name in ("sb", "sr", "both"):
        for slots in (10, 20):
            x = out[f"{name}_s{slots}"]
            print(f"  {name:4s} slots={slots}: trades {x['trades']:5d} skipped "
                  f"{x['skipped']:5d} CAGR {x['cagr']}% worstDD {x['dd_worst']}% "
                  f"years {x['years']}", flush=True)
    return out


def main() -> None:
    old = [c for c in smc.UNIVERSE if smc.have(c, sr.BASE)]
    new = smc_oos.new_coins()
    res = {}
    print("PLATEAU (old 76 only)", flush=True)
    res["plateau"] = plateau(old)
    allc = old + new
    sb = b_final(allc)
    srt = sr.basket(allc, CAND)
    res["all"] = versus(sb, srt, "ALL 279 coins")
    res["new"] = versus(sb[sb.coin.isin(new)], srt[srt.coin.isin(new)],
                        "NEW 203 coins")
    OUT.write_text(json.dumps(res, default=str, indent=1))


if __name__ == "__main__":
    main()
