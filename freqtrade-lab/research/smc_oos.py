"""The final exam for an SMC config: coins it has never seen, higher costs,
and an account instead of an R sum.

    python research/smc_oos.py            # runs the configs in FINALISTS

New coins are every Binance USDT pair on disk outside the 76-coin universe,
listed before 2025-06-01 and at least as liquid as the least liquid of the 76
(the same bar as new_coins.py). None of them was used to pick anything.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness       # noqa: E402
import smc           # noqa: E402
import smc_loop      # noqa: E402
import smc_account   # noqa: E402

LISTED_BEFORE = pd.Timestamp("2025-06-01", tz="UTC")
VOL_SINCE = pd.Timestamp("2024-01-01", tz="UTC")


def _med_vol(coin: str) -> float:
    d = harness.load(f"{coin}/USDT", "1d")
    d = d[d.index >= VOL_SINCE]
    return float((d["close"] * d["volume"]).median()) if len(d) else 0.0


def new_coins() -> list[str]:
    old = set(smc.UNIVERSE)
    have = sorted(p.name.split("_USDT-")[0]
                  for p in harness.DATA_DIR.glob("*_USDT-1h.feather"))
    floor = min(_med_vol(c) for c in smc.UNIVERSE if smc.have(c, "1d"))
    out = []
    for c in have:
        if c in old or not smc.have(c, "1d"):
            continue
        d = harness.load(f"{c}/USDT", "1d")
        if d.index[0] < LISTED_BEFORE and _med_vol(c) >= floor:
            out.append(c)
    return out


def exam(name: str, cfg: smc.Cfg, base: str = "1h") -> dict:
    old = [c for c in smc.UNIVERSE if smc.have(c, base)]
    fit, hold = smc.split(old)
    new = new_coins()
    res = {"name": name}
    stress = replace(cfg, cost=0.0010)
    for label, coins in (("old", old), ("new", new)):
        tr = smc_loop.evaluate([cfg, stress], coins, base, f"{name} {label}")
        for tag, t in (("", tr[0]), ("cost10_", tr[1])):
            if label == "old" and not tag:
                f = t[t.coin.astype(str).isin(set(fit))]
                h = t[t.coin.astype(str).isin(set(hold))]
                res["fit"] = smc.metrics(f)
                res["hold"] = smc.metrics(h)
                res["old_acct"] = smc_account.account(t)
                res["old_by_year"] = t.groupby(t.exit_time.dt.year)["r"].agg(
                    ["size", "mean"]).round(3).to_dict("index")
            res[f"{tag}{label}"] = smc.metrics(t)
            if not tag:
                res[f"{label}_acct"] = smc_account.account(t)
                res[f"{label}_long"] = smc.metrics(t[t.dir > 0])
                res[f"{label}_short"] = smc.metrics(t[t.dir < 0])
        if label == "new":
            t = tr[0]
            res["new_by_year"] = t.groupby(t.exit_time.dt.year)["r"].agg(
                ["size", "mean"]).round(3).to_dict("index")
    res["n_new_coins"] = len(new)
    return res


def show(res: dict) -> None:
    keys = ["n", "win", "avg_r", "pf", "per_yr", "ann_r", "dd_r", "ratio",
            "coins_pos", "yrs_pos"]
    print(f"\n=== {res['name']}  (new coins: {res['n_new_coins']})")
    rows = {k: res[k] for k in ("fit", "hold", "old", "new", "cost10_old",
                                "cost10_new", "old_long", "old_short",
                                "new_long", "new_short") if k in res}
    print(pd.DataFrame(rows).T.reindex(columns=keys).to_string())
    for k in ("old_acct", "new_acct"):
        a = res[k]
        print(f"{k}: CAGR {a['cagr']}%  dd closed {a['dd_closed']}%  "
              f"dd worst-case {a['dd_worst']}%  trades {a['trades']} "
              f"(skipped {a['skipped']})  years {a['years']}")
    for k in ("old_by_year", "new_by_year"):
        print(k, {y: f"{v['mean']:+.2f}/{int(v['size'])}" for y, v in res[k].items()})


L = smc_loop.LEADERS
FINALISTS: dict[str, smc.Cfg] = {
    # round 4 picks (SMC_RESEARCH.md): the leader plus the filters that
    # helped it on BOTH halves; the unfiltered leader runs alongside so the
    # exam also tests whether the filters themselves generalise
    "C_rev1h_ny_vol": replace(L["C_rev1h"], hour_from=12, min_volx=0.9),
    "C_rev1h_raw": L["C_rev1h"],
    "A_ote4h_leg": replace(L["A_ote4h"], max_leg_atr=3.5),
    "A_ote4h_raw": L["A_ote4h"],
    "B_mkt4h_leg_vol": replace(L["B_mkt4h"], max_leg_atr=3.5, min_volx=0.9),
    "B_mkt4h_raw": L["B_mkt4h"],
    # round 5: exit picked on the 76 old coins only (the middle of a plateau)
    "B_final": replace(L["B_mkt4h"], tp_r=6.0, max_hold=168, exit_choch=True,
                       sl_buf=0.5),
}


if __name__ == "__main__":
    import json
    pick = sys.argv[1:] or list(FINALISTS)
    for name in pick:
        res = exam(name, FINALISTS[name])
        show(res)
        (smc_loop.RES / f"smc_exam_{name}.json").write_text(
            json.dumps(res, default=str, indent=1))
