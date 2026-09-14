"""Phase B, step 3: is "tighten the trail to 10% after +200%" real?

    python research/dd_levers3.py

dd_levers2.py found one lever that passed every guard: once a trade is up
200%, tighten its trailing stop from 25% to 10%. It raised CAGR / drawdown on
all coins, on both halves, and on 100 of 100 random baskets. Two reasons to
doubt it anyway:

  * it is the last cell of the range tested, and its nearest neighbour
    (tighten after +100%) was WORSE -- the shape of a ridge, not a plateau
  * the random baskets all draw from the same 76 coins, so they share the same
    handful of trades that ever reached +200%; "100 of 100" is not 100
    independent confirmations

So this runs the neighbourhood (+150%, +200%, +300%; tight trail 5%, 10%, 15%)
and then runs every variant on the 203 NEW coins from new_coins.py, which
played no part in choosing the lever. It also counts how many trades each
variant actually changes, because a lever that touches six trades is six
anecdotes.

Old coins walk on 15m candles (as in dd_levers2.py); new coins on 1h, which is
all that was downloaded for them.
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
import new_coins    # noqa: E402
import dd_levers2 as L2   # noqa: E402
from tl_final import FINAL  # noqa: E402

RES = Path(__file__).resolve().parent / "results"
HOUR = pd.Timedelta("1h")

BASE = "baseline: trail 25%"
EXITS = {BASE: dict(trail_pct=0.25)}
for at in (1.5, 2.0, 3.0):
    for tight in (0.05, 0.10, 0.15):
        EXITS[f"tighten to {tight:.0%} after +{at:.0%}"] = dict(
            trail_pct=0.25, tighten_at=at, trail_pct_tight=tight)


def walk(coins: list[str], plan_kw: dict, detail: str, tag: str) -> dict[str, list]:
    key = repr((sorted(FINAL.items()), sorted(rf_final.REFINED.items()),
                sorted(plan_kw.items()), rf_final.TIME_STOP_H, detail, sorted(coins)))
    p = RES / f"{tag}_trades_{hashlib.md5(key.encode()).hexdigest()[:10]}.pkl"
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
        out[c] = harness.simulate(sig, h, harness.load(f"{c}/USDT", detail), plan,
                                  base_bar=HOUR)
    p.write_bytes(pickle.dumps(out))
    return out


def changed(base: dict, var: dict) -> tuple[int, float]:
    """How many trades the variant alters, and the total R it adds or removes."""
    n, dr = 0, 0.0
    for c in base:
        for a, b in zip(base[c], var[c]):
            if abs(a.r - b.r) > 1e-9:
                n += 1
                dr += b.r - a.r
    return n, dr


def section(title: str, coins: list[str], detail: str, tag: str, seed: int) -> list[str]:
    fit, hold = campaign.split(coins)
    rng = random.Random(seed)
    size = min(38, len(coins) // 2)
    rand = [rng.sample(coins, size) for _ in range(100)]
    walks = {n: walk(coins, kw, detail, tag) for n, kw in EXITS.items()}
    paths = {n: baskets.return_paths(t) for n, t in walks.items()}
    md = [f"## {title}", "",
          f"{len(coins)} coins, {detail} fills; random baskets: 100 x {size} coins "
          f"(seed {seed}), paired with the baseline on the same coins.", "",
          "| exit | trades changed | R added | ALL CAGR | ALL real DD | **ALL ratio** | "
          "**FIT ratio** | **HOLD ratio** | random: better ratio | median ratio change | passes |",
          "|" + "---|" * 11]
    ref = None
    for name in EXITS:
        tbc, pth = walks[name], paths[name]
        a, f, h = (L2.score(tbc, pth, cs) for cs in (coins, fit, hold))
        rnd = [L2.score(tbc, pth, b) for b in rand]
        n_chg, dr = changed(walks[BASE], tbc)
        if ref is None:
            ref = (f, h, rnd)
            better = med = "-"
            verdict = "reference"
        else:
            pairs = [(x, y) for x, y in zip(rnd, ref[2]) if x and y]
            share = np.mean([x["ratio"] > y["ratio"] for x, y in pairs])
            better = f"{100*share:.0f}%"
            med = f"{np.median([x['ratio'] - y['ratio'] for x, y in pairs]):+.2f}"
            ok = f["ratio"] > ref[0]["ratio"] and h["ratio"] > ref[1]["ratio"] and share >= 0.6
            verdict = "**yes**" if ok else "no"
        md.append(f"| {name} | {n_chg} | {dr:+.1f} | {a['CAGR']:.1f}% | {a['DD']:.1f}% | "
                  f"**{a['ratio']:.2f}** | **{f['ratio']:.2f}** | **{h['ratio']:.2f}** | "
                  f"{better} | {med} | {verdict} |")
        print(f"  {tag}: {name}", file=sys.stderr, flush=True)
    return md + [""]


def main() -> None:
    old = rf_final.coins_available()
    new, _ = new_coins.new_coins()
    md = ["# Phase B, step 3: tighten-after-gain, neighbours and new coins", "",
          "`ratio` = CAGR / drawdown with open trades valued daily. A variant "
          "passes if it beats the baseline ratio on both hash halves and on at "
          "least 60% of the paired random baskets.", ""]
    md += section("Old 76 coins (the lever was chosen here)", old, "15m", "ddl3old", 3)
    md += section("NEW coins (never used to choose anything)", new, "1h", "ddl3new", 5)
    out = RES / "dd_levers3.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
