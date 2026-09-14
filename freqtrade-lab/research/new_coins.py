"""Phase A: TrendlineBreakoutLTF on coins it has never seen.

    python research/new_coins.py            # 300 random baskets per size

Every choice in this strategy -- the trendline rules, the 1h stop, the 25%
trail -- was made while looking at the same 76 coins. The hash split kept half
of them out of each decision, but all 76 were in the room. The coins here were
downloaded afterwards and were never looked at, so this is the cleanest
out-of-sample test available short of trading forward.

Nothing is re-tuned. The config is rf_final.REFINED, unchanged.

Which new coins count:
  * a Binance USDT spot pair, active in 2026-09, not in campaign.UNIVERSE
  * not a stablecoin, wrapped coin, leveraged token or tokenized stock
  * first daily candle before 2025-06-01, so a 200-day line has room to form
  * median daily USDT volume since 2024 at least that of BAND, the least
    liquid coin already traded -- the same bar the old universe clears

Exits are walked on 1h candles, not 15m: that is what was downloaded, and
1h / 15m / 5m fills were shown to agree (STRATEGY_TrendlineBreakoutLTF.md).
For a fair comparison the old 76 are re-run on 1h fills here too.

Survivorship still applies: only coins still listed today could be downloaded.
Coins that died since 2020 are missing from both universes.
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
import rf_final     # noqa: E402
from tl_final import FINAL  # noqa: E402

RES = Path(__file__).resolve().parent / "results"
DETAIL = "1h"
LISTED_BEFORE = pd.Timestamp("2025-06-01", tz="UTC")
VOL_SINCE = pd.Timestamp("2024-01-01", tz="UTC")


def median_volume(coin: str) -> float:
    d = harness.load(f"{coin}/USDT", "1d")
    d = d[d.index >= VOL_SINCE]
    return float((d["close"] * d["volume"]).median()) if len(d) else 0.0


def old_coins() -> list[str]:
    return rf_final.coins_available()


def new_coins() -> tuple[list[str], dict]:
    """New coins with 1d and 1h data that pass the listing and liquidity bars."""
    old = set(campaign.UNIVERSE)
    have = sorted(p.name.split("_USDT-")[0]
                  for p in harness.DATA_DIR.glob("*_USDT-1h.feather"))
    floor = min(median_volume(c) for c in old_coins())
    kept, why = [], {"listed too late": [], "too illiquid": [], "no daily data": []}
    for c in have:
        if c in old:
            continue
        try:
            d = harness.load(f"{c}/USDT", "1d")
        except FileNotFoundError:
            why["no daily data"].append(c)
            continue
        if d.index[0] >= LISTED_BEFORE:
            why["listed too late"].append(c)
        elif median_volume(c) < floor:
            why["too illiquid"].append(c)
        else:
            kept.append(c)
    return kept, {"floor": floor, **why}


def trades_for(coins: list[str], tag: str) -> dict[str, list]:
    key = repr((sorted(FINAL.items()), sorted(rf_final.REFINED.items()),
                sorted(rf_final.PLAN.items()), rf_final.TIME_STOP_H, DETAIL,
                sorted(coins)))
    p = RES / f"{tag}_trades_{hashlib.md5(key.encode()).hexdigest()[:10]}.pkl"
    if p.exists():
        return pickle.loads(p.read_bytes())
    out = {}
    for i, c in enumerate(coins, 1):
        out[c] = [t for t, _ in rf_final.collect([c], rf_final.REFINED, DETAIL)]
        if i % 20 == 0 or i == len(coins):
            print(f"  {tag}: walked {i}/{len(coins)}", file=sys.stderr, flush=True)
    p.write_bytes(pickle.dumps(out))
    return out


def run(coins: list[str], tbc: dict, paths: dict, slots: int = 10) -> dict | None:
    saved = baskets.MAX_OPEN
    baskets.MAX_OPEN = slots          # run_basket reads the module setting
    try:
        return baskets.run_basket([c for c in coins if c in tbc], tbc, paths)
    finally:
        baskets.MAX_OPEN = saved


def main() -> None:
    n_random = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    old = old_coins()
    new, why = new_coins()
    print(f"old universe {len(old)} coins; new coins kept {len(new)}", file=sys.stderr)

    t_old = trades_for(old, "old1h")
    t_new = trades_for(new, "new1h")
    tbc = {**t_old, **t_new}
    paths = baskets.return_paths(tbc)
    first = {c: harness.load(f"{c}/USDT", "1d").index[0] for c in new}

    md = ["# Phase A: TrendlineBreakoutLTF on coins it has never seen", "",
          f"Config unchanged (rf_final.REFINED). Exits walked on {DETAIL} candles; "
          f"{baskets.MAX_OPEN} slots, {baskets.RISK:.0%} risk, capital cap "
          f"{baskets.CAP:.0%}, open trades valued at every daily close. CAGR over "
          f"{baskets.MARKS[0].date()} -> {baskets.MARKS[-1].date()}.", "",
          "## Which new coins were tested", "",
          f"- **{len(new)} new coins kept.**",
          f"- Liquidity bar: median daily USDT volume since 2024 of at least "
          f"{why['floor']:,.0f} (BAND, the least liquid old coin).",
          f"- Dropped as listed on or after {LISTED_BEFORE.date()}: "
          f"{len(why['listed too late'])}.",
          f"- Dropped as too illiquid: {len(why['too illiquid'])}.",
          f"- Dropped for missing daily data: {len(why['no daily data'])}.", "",
          f"Kept: {' '.join(new)}", ""]

    rows = [("old 76 coins (1h fills)", run(old, tbc, paths)),
            (f"NEW coins only ({len(new)})", run(new, tbc, paths)),
            ("new coins listed before 2022",
             run([c for c in new if first[c] < pd.Timestamp("2022-01-01", tz="UTC")], tbc, paths)),
            ("new coins listed 2022 or later",
             run([c for c in new if first[c] >= pd.Timestamp("2022-01-01", tz="UTC")], tbc, paths)),
            (f"old + new together ({len(old) + len(new)}), 10 slots", run(old + new, tbc, paths)),
            ("old + new together, 15 slots", run(old + new, tbc, paths, slots=15)),
            ("old + new together, 20 slots", run(old + new, tbc, paths, slots=20))]
    md += ["## Headline", "", baskets.table(rows), ""]

    rng = random.Random(11)
    md += ["## Random baskets drawn only from the NEW coins", "",
           f"{n_random} baskets per size (seed 11). Compare with the same sizes "
           "drawn from the old 76 in `baskets.md`: 20 coins median 17.5%, "
           "38 coins median 31.2%.", "",
           "| size | CAGR p5 | p25 | median | p75 | p95 | real DD median | real DD p95 | "
           "CAGR/DD median | baskets profitable |",
           "|" + "---|" * 10]
    for size in (20, 38, 76):
        if size > len(new):
            continue
        res = [r for r in (run(rng.sample(new, size), tbc, paths)
                           for _ in range(n_random)) if r is not None]
        cg = np.array([r["CAGR%"] for r in res])
        dd = np.array([r["DD%"] for r in res])
        cd = np.array([r["CAGR/DD"] or 0.0 for r in res])
        q = lambda a, p: f"{np.percentile(a, p):.1f}"  # noqa: E731
        md.append(f"| {size} | {q(cg,5)} | {q(cg,25)} | {q(cg,50)} | {q(cg,75)} | "
                  f"{q(cg,95)} | {q(dd,50)} | {q(dd,95)} | {np.median(cd):.2f} | "
                  f"{100*np.mean(cg > 0):.0f}% |")
        print(f"  random size {size}: done", file=sys.stderr, flush=True)
    md.append("")

    md += ["## Every new coin on its own", "",
           "| coin | listed | trades | win% | avg R | total R | best trade R |",
           "|---|---|---|---|---|---|---|"]
    tot = {c: sum(t.r for t in t_new[c]) for c in new}
    for c in sorted(new, key=lambda c: -tot[c]):
        rs = np.array([t.r for t in t_new[c]])
        if not len(rs):
            md.append(f"| {c} | {first[c].date()} | 0 | - | - | - | - |")
            continue
        md.append(f"| {c} | {first[c].date()} | {len(rs)} | {100*np.mean(rs > 0):.0f} | "
                  f"{rs.mean():+.2f} | {rs.sum():+.1f} | {rs.max():+.1f} |")
    traded = [c for c in new if t_new[c]]
    pos = [c for c in traded if tot[c] > 0]
    old_traded = [c for c in old if t_old[c]]
    old_pos = [c for c in old_traded if sum(t.r for t in t_old[c]) > 0]
    md += ["", f"New coins: {len(traded)} of {len(new)} traded; {len(pos)} positive "
               f"total R ({100*len(pos)/max(len(traded),1):.0f}%). Old coins on 1h fills: "
               f"{len(old_pos)} of {len(old_traded)} positive "
               f"({100*len(old_pos)/max(len(old_traded),1):.0f}%).", ""]

    out = RES / "new_coins.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
