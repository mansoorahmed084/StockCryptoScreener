"""Backtest TrendlineBreakoutLTF on many coin baskets.

    python research/baskets.py            # every basket, 300 random baskets per size
    python research/baskets.py 1000       # more random baskets

The headline 49% was earned on one universe, and five trades made most of it.
So the question here is not "is the number good" but "does it depend on which
coins you pick". Every basket is run the same way:

  * the research engine's refined config (rf_final.REFINED): daily trendline
    break, next daily open, stop under the signal day's low minus 1xATR(1h),
    25% trailing exit, 365-day time stop, 15m fills
  * an account: 10 slots, 1% risk, profit banked at exit, total positions
    capped at 100% of the account (tl_account.simulate_honest)
  * drawdown measured TWO ways: closed trades only, and with every open
    position valued at each daily close. The second one is the real one --
    STRATEGY_TrendlineBreakoutLTF.md, "Drawdown, measured two ways".

CAGR is measured over the SAME calendar span for every basket
(2020-01-02 -> 2026-09-07) with open trades valued at the end, so baskets are
comparable. That is why the whole universe reads ~42% here and 48.3% in
rf_final.py, which measures from the first entry to the last exit.

A basket's trades are the same trades whatever else is in the basket -- a
coin's signals do not depend on other coins. So each coin is walked on 15m
candles once, cached, and every basket reuses the result. Only the account
(which slots fill, how big each position is) changes from basket to basket.
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
import campaign     # noqa: E402
import rf_final     # noqa: E402
import tl_account   # noqa: E402
from tl_final import FINAL           # noqa: E402
from tl_portfolio import CAPITAL     # noqa: E402

RES = Path(__file__).resolve().parent / "results"
MARKS = pd.date_range("2020-01-02", "2026-09-07", freq="D", tz="UTC")
YEARS = (MARKS[-1] - MARKS[0]).days / 365.25
MAX_OPEN, RISK, CAP = 10, 0.01, 1.0

# ---------------------------------------------------------------- baskets
MAJORS = "BTC ETH BNB XRP SOL ADA DOGE TRX LTC BCH LINK AVAX DOT".split()
# Sector labels are a judgment call, kept non-overlapping so every coin sits in
# exactly one. They are for grouping, not a claim about what each project is.
SECTORS = {
    "majors": MAJORS,
    "other layer-1s": ("ATOM NEAR ALGO ICP EGLD SEI SUI APT TIA INJ ONE KAVA CFX "
                       "FLOW MINA ROSE HBAR KSM NEO ZIL CELO S XLM ETC IOTA WAVES").split(),
    "layer-2 / scaling": "ARB OP IMX STX SKL".split(),
    "DeFi": "UNI AAVE CRV SUSHI COMP SNX DYDX LDO PENDLE JUP ENA ONDO RUNE".split(),
    "AI / data / infra": "FET GRT AR OCEAN TAO WLD PYTH BAND FIL ANKR QNT THETA VET".split(),
    "gaming / NFT / social": "SAND MANA AXS GALA ENJ CHZ BLUR MASK".split(),
}


def cache_path() -> Path:
    """Cache keyed on the strategy, so a changed config cannot reuse old trades."""
    key = repr((sorted(FINAL.items()), sorted(rf_final.REFINED.items()),
                sorted(rf_final.PLAN.items()), rf_final.TIME_STOP_H))
    return RES / f"baskets_trades_{hashlib.md5(key.encode()).hexdigest()[:10]}.pkl"


def all_trades(coins: list[str]) -> dict[str, list]:
    p = cache_path()
    if p.exists():
        return pickle.loads(p.read_bytes())
    out = {}
    for i, c in enumerate(coins, 1):
        out[c] = [t for t, _ in rf_final.collect([c], rf_final.REFINED, "15m")]
        print(f"  walked {c:6s} {len(out[c]):3d} trades  ({i}/{len(coins)})",
              file=sys.stderr, flush=True)
    p.write_bytes(pickle.dumps(out))
    return out


def return_paths(tbc: dict[str, list]) -> dict:
    """For every trade: its return since entry at each daily close it was open."""
    paths = {}
    for c, trs in tbc.items():
        close = harness.load(f"{c}/USDT", "1d")["close"]
        # the value at mark m uses the daily bar that CLOSED at m
        px = close.reindex(MARKS - pd.Timedelta("1D")).to_numpy()
        for t in trs:
            live = (MARKS > t.entry_time) & (MARKS < t.exit_time)
            paths[(t.entry_time, c)] = np.nan_to_num(
                np.where(live, px / t.entry - 1.0, 0.0))
    return paths


# ----------------------------------------------------------------- one run
def mdd(x: np.ndarray) -> float:
    peak = np.maximum.accumulate(x)
    return float(100 * np.max((peak - x) / peak))


def run_basket(coins: list[str], tbc: dict, paths: dict) -> dict | None:
    trades = [(t, c) for c in coins for t in tbc.get(c, [])]
    if not trades:
        return None
    pooled = harness.metrics([t for t, _ in trades])
    acct = tl_account.simulate_honest(trades, CAPITAL, RISK, MAX_OPEN,
                                      max_exposure=CAP)
    if acct.empty:
        return None

    # Realised equity at each daily mark: the profit of every trade closed by
    # then. Search on the DatetimeIndex itself, never on raw .asi8 integers:
    # exit times arrive at microsecond resolution and the marks at nanosecond,
    # so the raw integers differ by 1000x and every exit looked earlier than
    # every mark. That made realised equity a flat line and corrupted both
    # drawdowns and the year table. The assert catches it if it ever recurs.
    ex = pd.DatetimeIndex(acct["exit"])
    order = np.argsort(ex.asi8)               # same resolution: order is safe
    exits = ex[order]
    cum = np.concatenate([[0.0], np.cumsum(acct["pnl"].to_numpy()[order])])
    k = exits.searchsorted(MARKS, side="right")
    mid = len(k) // 2
    assert k[mid] == int((exits <= MARKS[mid]).sum()), "exit/mark alignment broke"
    realised = CAPITAL + cum[k]
    byk = {(t.entry_time, c): t for t, c in trades}
    unreal = np.zeros(len(MARKS))
    for e, c in zip(acct["entry"], acct["coin"]):
        unreal += byk[(e, c)].notional * paths[(e, c)]
    mtm = realised + unreal

    eq = pd.Series(mtm, MARKS)
    ye = eq.groupby(eq.index.year).last()
    prev = np.concatenate([[CAPITAL], ye.to_numpy()[:-1]])
    yr = ye.to_numpy() / prev - 1
    pnl = np.sort(acct["pnl"].to_numpy())[::-1]
    gain = pnl[pnl > 0].sum()
    cagr = 100 * ((mtm[-1] / CAPITAL) ** (1 / YEARS) - 1) if mtm[-1] > 0 else -100.0
    mtm_dd = mdd(mtm)
    annual_r = pooled["n"] * pooled["avg_r"] / YEARS
    return {
        "coins": len(coins),
        "traded": int(acct["coin"].nunique()),
        "signals": pooled["n"],
        "fills": len(acct),
        "win%": round(100 * float((acct["r"] > 0).mean()), 1),
        "avgR": round(float(pooled["avg_r"]), 2),
        "PF": pooled["pf"],
        "R_ratio": round(annual_r / pooled["max_dd_r"], 2) if pooled["max_dd_r"] else None,
        "CAGR%": round(cagr, 1),
        "closedDD%": round(mdd(realised), 1),
        "DD%": round(mtm_dd, 1),
        "CAGR/DD": round(cagr / mtm_dd, 2) if mtm_dd > 0 else None,
        "best5%": round(100 * pnl[:5].clip(min=0).sum() / gain, 0) if gain > 0 else None,
        "losing_yrs": f"{int((yr < 0).sum())}/{len(yr)}",
        "worst_yr%": round(100 * float(yr.min()), 1),
    }


COLS = ["coins", "traded", "signals", "fills", "win%", "avgR", "PF", "CAGR%",
        "closedDD%", "DD%", "CAGR/DD", "best5%", "losing_yrs", "worst_yr%"]


def table(rows: list[tuple[str, dict | None]]) -> str:
    head = "| basket | " + " | ".join(COLS) + " |\n|" + "---|" * (len(COLS) + 1)
    out = [head]
    for name, r in rows:
        if r is None:
            out.append(f"| {name} | " + " | ".join("-" for _ in COLS) + " |")
        else:
            out.append(f"| {name} | " + " | ".join(str(r[c]) for c in COLS) + " |")
    return "\n".join(out)


# -------------------------------------------------------------------- main
def main() -> None:
    n_random = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    coins = rf_final.coins_available()
    fit, hold = campaign.split(coins)
    print(f"walking {len(coins)} coins on 15m candles (cached after the first run)",
          file=sys.stderr, flush=True)
    tbc = all_trades(coins)
    paths = return_paths(tbc)
    run = lambda cs: run_basket([c for c in cs if c in tbc], tbc, paths)  # noqa: E731

    md = ["# TrendlineBreakoutLTF across coins and baskets", "",
          f"Research engine, 15m fills, {MAX_OPEN} slots, {RISK:.0%} risk, positions "
          f"capped at {CAP:.0%} of the account. CAGR over {MARKS[0].date()} -> "
          f"{MARKS[-1].date()} ({YEARS:.2f} years) with open trades valued at the end. "
          "`DD%` values open trades at every daily close; `closedDD%` counts closed "
          "trades only. `best5%` is the share of all gains made by the 5 best trades. "
          "`R_ratio` is annual R / max drawdown in R with no slot limit.", ""]

    # --- 1. reference baskets
    ref = [("all coins", run(coins)), ("fit half (hash split)", run(fit)),
           ("held-out half (hash split)", run(hold))]
    md += ["## 1. Reference", "", table(ref), ""]

    # --- 2. sectors
    rows = [(f"{k} ({len([c for c in v if c in tbc])})", run(v)) for k, v in SECTORS.items()]
    rows.append(("everything except majors", run([c for c in coins if c not in MAJORS])))
    md += ["## 2. Sectors", "",
           "Small baskets have fewer signals than there are slots, so their CAGR is "
           "held down by idle cash. Compare `avgR`, `PF` and `R_ratio` across sizes, "
           "and CAGR only between baskets of similar size.", "", table(rows), ""]

    # --- 3. liquidity
    vol = {}
    for c in coins:
        d = harness.load(f"{c}/USDT", "1d")
        d = d[d.index >= pd.Timestamp("2024-01-01", tz="UTC")]
        vol[c] = float((d["close"] * d["volume"]).median()) if len(d) else 0.0
    ranked = sorted(coins, key=lambda c: -vol[c])
    third = len(ranked) // 3
    rows = [("most liquid third", run(ranked[:third])),
            ("middle third", run(ranked[third:2 * third])),
            ("least liquid third", run(ranked[2 * third:]))]
    md += ["## 3. Liquidity (median daily USDT volume since 2024)", "", table(rows), "",
           f"Most liquid: {' '.join(ranked[:third])}", "",
           f"Least liquid: {' '.join(ranked[2 * third:])}", ""]

    # --- 4. listing age
    first = {c: harness.load(f"{c}/USDT", "1d").index[0] for c in coins}
    cut20, cut22 = pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2022-01-01", tz="UTC")
    rows = [("listed before 2020", run([c for c in coins if first[c] < cut20])),
            ("listed 2020-2021", run([c for c in coins if cut20 <= first[c] < cut22])),
            ("listed 2022 or later", run([c for c in coins if first[c] >= cut22]))]
    md += ["## 4. Listing age (first daily candle on Binance)", "", table(rows), ""]

    # --- 5. without the winners
    tot_r = {c: sum(t.r for t in tbc[c]) for c in coins}
    best = sorted(coins, key=lambda c: -tot_r[c])
    rows = [("all coins", ref[0][1])]
    for k in (3, 5, 10, 15):
        rows.append((f"without the top {k} coins", run(best[k:])))
    md += ["## 5. Take away the coins that carried it", "",
           "The top coins are ranked by total R in this same engine, so this uses "
           "hindsight on purpose: it asks what is left when the luckiest names are "
           "removed.", "", table(rows), "",
           f"Top 15 by total R: {', '.join(f'{c} {tot_r[c]:+.1f}R' for c in best[:15])}", ""]

    # --- 6. random baskets
    rng = random.Random(7)
    md += ["## 6. Random baskets", "",
           f"{n_random} baskets per size, drawn without replacement from all "
           f"{len(coins)} coins (seed 7).", "",
           "| size | CAGR p5 | p25 | median | p75 | p95 | DD% median | DD% p95 | "
           "CAGR/DD median | baskets with CAGR > 0 | baskets with CAGR/DD > 1 |",
           "|" + "---|" * 11]
    for size in (10, 20, 38):
        res = [run(rng.sample(coins, size)) for _ in range(n_random)]
        res = [r for r in res if r is not None]
        cg = np.array([r["CAGR%"] for r in res]); dd = np.array([r["DD%"] for r in res])
        cd = np.array([r["CAGR/DD"] if r["CAGR/DD"] is not None else 0.0 for r in res])
        q = lambda a, p: f"{np.percentile(a, p):.1f}"  # noqa: E731
        md.append(f"| {size} | {q(cg,5)} | {q(cg,25)} | {q(cg,50)} | {q(cg,75)} | "
                  f"{q(cg,95)} | {q(dd,50)} | {q(dd,95)} | {np.median(cd):.2f} | "
                  f"{100*np.mean(cg > 0):.0f}% | {100*np.mean(cd > 1):.0f}% |")
        print(f"  random size {size}: done", file=sys.stderr, flush=True)
    md.append("")

    # --- 7. every coin on its own (pooled R, no account)
    md += ["## 7. Every coin on its own", "",
           "Pooled trades per coin, no slot limit. One coin rarely has enough trades "
           "for its own account, so this is per-trade expectancy, not a CAGR.", "",
           "| coin | trades | win% | avg R | total R | best trade R | worst trade R |",
           "|---|---|---|---|---|---|---|"]
    for c in best:
        trs = tbc[c]
        if not trs:
            md.append(f"| {c} | 0 | - | - | - | - | - |")
            continue
        rs = np.array([t.r for t in trs])
        md.append(f"| {c} | {len(rs)} | {100*np.mean(rs > 0):.0f} | {rs.mean():+.2f} | "
                  f"{rs.sum():+.1f} | {rs.max():+.1f} | {rs.min():+.1f} |")
    pos = sum(1 for c in coins if tbc[c] and tot_r[c] > 0)
    traded = sum(1 for c in coins if tbc[c])
    md += ["", f"{traded} coins traded; {pos} have positive total R, "
               f"{traded - pos} negative; {len(coins) - traded} never traded.", ""]

    out = RES / "baskets.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\nwritten {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
