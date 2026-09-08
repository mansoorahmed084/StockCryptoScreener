"""Phase 7 campaign: stack every supported ingredient, then test market breadth.

    python research/campaign.py breadth      # washout or knife?
    python research/campaign.py stack        # do the supported ingredients compose?
    python research/campaign.py final <args> # one config, full report

Ingredients that survived a held-out-coin test in earlier phases, and are
therefore allowed in without re-litigating:

    structure-break entry   phase 6, +0.05R on both baskets
    money-flow green        phase 6, +0.10R on both baskets
    1h over 15m             phase 6, cost/R 6% vs 13%
    volatile instruments    phase 6, alts move ~2x BTC per bar
    daily regime gate       phase 2, +0.20R gated vs -0.17R ungated on 1h
    deep oversold           phase 1, deep pivots ~3x the drift of shallow

Never tested, and the reason this campaign exists: BREADTH. Signals arrive in
clusters because alts move together. A divergence printing while 60% of the
universe is oversold is a different event from one printing while 5% is.

The universe is split by hashing the coin name, so the fit/holdout membership
does not track market cap, listing age or sector -- all of which would leak.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness      # noqa: E402
import breakout     # noqa: E402
import breadth as bd  # noqa: E402
import strategies   # noqa: E402

UNIVERSE = """BTC ETH BNB XRP ADA DOGE SOL DOT LTC LINK AVAX TRX ATOM ETC XLM BCH
FIL NEAR ALGO VET ICP HBAR AAVE UNI SAND MANA AXS THETA EGLD STX SEI TAO S INJ TIA
SUI APT ARB OP FET GRT IMX LDO PENDLE JUP PYTH ENA ONDO AR RUNE CFX GALA CHZ CRV
SUSHI COMP SNX ZIL ONE IOTA QNT KSM NEO WAVES ENJ ANKR CELO SKL OCEAN BAND KAVA
ROSE FLOW MASK DYDX MINA WLD BLUR""".split()

# Timeframe is a CLI argument because the cost findings all point the same way:
# fees eat 18% of every R on 15m, 13% on 1h majors, 6% on 1h alts, ~9% on 4h and
# least of all on daily -- which is also where the one strategy that has ever
# survived a held-out-coin test already lives.
TFS = {"1h": ("15m", pd.Timedelta("1h")),
       "4h": ("1h", pd.Timedelta("4h")),
       "1d": ("1h", pd.Timedelta("1D"))}
TF, (DETAIL, BAR) = "1h", TFS["1h"]


def split(coins: list[str]) -> tuple[list[str], list[str]]:
    """Deterministic hash split, so membership carries no market information."""
    fit, hold = [], []
    for c in coins:
        h = int(hashlib.md5(c.encode()).hexdigest(), 16)
        (fit if h % 2 == 0 else hold).append(c)
    return fit, hold


def available(coins: list[str]) -> list[str]:
    ok = []
    for c in coins:
        try:
            harness.load(f"{c}/USDT", TF)
            harness.load(f"{c}/USDT", DETAIL)
            ok.append(c)
        except FileNotFoundError:
            pass
    return ok


def run(coins: list[str], breadth_pct: pd.Series | None,
        plan: harness.ExitPlan, use_gate: bool, **kw) -> tuple[dict, list]:
    pooled, per = [], []
    for c in coins:
        pair = f"{c}/USDT"
        try:
            base, det = harness.load(pair, TF), harness.load(pair, DETAIL)
        except FileNotFoundError:
            continue
        gate = None
        if use_gate:
            try:
                gate = strategies.higher_tf_regime(
                    base, harness.load(pair, "1d"), "1d", pd.Timedelta("1D"))
            except FileNotFoundError:
                continue
        sig = breakout.divergence_breakout(base, breadth=breadth_pct,
                                           gate=gate, **kw)
        if sig.empty:
            continue
        tr = harness.simulate(sig, base, det, plan, base_bar=BAR)
        if not tr:
            continue
        pooled += tr
        if len(tr) >= 8:
            per.append(harness.metrics(tr)["avg_r"])
    return harness.metrics(pooled), per


def row(label: str, mf: dict, pf: list, mh: dict, ph: list) -> str:
    if not mf.get("n") or not mh.get("n"):
        return f"| {label} | 0 |" + " — |" * 10
    return (f"| {label} | {mf['n']} | {mf['win_net_pct']} | {mf['avg_r']:+.3f} | "
            f"{sum(1 for x in pf if x > 0)}/{len(pf)} || {mh['n']} | "
            f"{mh['win_net_pct']} | **{mh['avg_r']:+.3f}** | {mh['pf']} | "
            f"{mh['max_dd_r']} | **{sum(1 for x in ph if x > 0)}/{len(ph)}** |")


HEAD = ("| config | FIT n | win% | avgR | +coins || HOLD n | win% | **avgR** | "
        "PF | maxDD_R | +coins |\n" + "|" + "---|" * 11)


def main() -> None:
    global TF, DETAIL, BAR
    mode = sys.argv[1] if len(sys.argv) > 1 else "breadth"
    if len(sys.argv) > 2 and sys.argv[2] in TFS:
        TF = sys.argv[2]
        DETAIL, BAR = TFS[TF]
    print(f"# timeframe {TF}, detail {DETAIL}")
    coins = available(UNIVERSE)
    fit, hold = split(coins)
    print(f"# universe {len(coins)} coins — FIT {len(fit)} / HOLDOUT {len(hold)}")
    print(f"# FIT: {' '.join(fit)}")
    print(f"# HOLDOUT: {' '.join(hold)}\n")

    b = bd.universe_breadth(coins, TF, oversold=-50.0)
    pct = bd.breadth_percentile(b, "os_frac", lookback=2000)
    plan = harness.ExitPlan(legs=[(3.0, 1.0)], time_stop_bars=200)
    wait = {"1h": 24, "4h": 12, "1d": 8}[TF]
    base_kw = dict(trigger="slope", wt2_max=-50.0, wait_bars=wait, atr_mult=1.0)

    if mode == "breadth":
        print("## Is a cluster of simultaneous signals a WASHOUT or a KNIFE?\n")
        print(HEAD)
        for lo, hi, name in ((None, None, "all breadth (control)"),
                             (0.0, 0.33, "LOW breadth (quiet market)"),
                             (0.33, 0.66, "MID breadth"),
                             (0.66, 1.01, "HIGH breadth (washout)"),
                             (0.85, 1.01, "EXTREME breadth")):
            kw = dict(base_kw, mfi_min=0.0, breadth_min=lo, breadth_max=hi)
            mf, pf = run(fit, pct, plan, False, **kw)
            mh, ph = run(hold, pct, plan, False, **kw)
            print(row(name, mf, pf, mh, ph))

    elif mode == "exits":
        # The stacked entry wins 29% at a 3R target, which is close to the 25%
        # breakeven. Either the entry is directionless, or 3R is simply further
        # than these moves travel. This separates those two explanations.
        print("## Is 3R too far for this entry?\n")
        print(HEAD)
        kw = dict(base_kw, mfi_min=0.0)
        EXITS = [
            ("target 1R", [(1.0, 1.0)], None),
            ("target 1.5R", [(1.5, 1.0)], None),
            ("target 2R", [(2.0, 1.0)], None),
            ("target 2.5R", [(2.5, 1.0)], None),
            ("target 3R", [(3.0, 1.0)], None),
            ("half 1R -> BE, run 3R", [(1.0, 0.5), (3.0, 0.5)], 0),
            ("half 1R -> BE, run 2R", [(1.0, 0.5), (2.0, 0.5)], 0),
            ("half 0.75R -> BE, run 2R", [(0.75, 0.5), (2.0, 0.5)], 0),
            ("thirds 1/2/3R -> BE", [(1.0, .34), (2.0, .33), (3.0, .33)], 0),
        ]
        for name, legs, be in EXITS:
            pl = harness.ExitPlan(legs=legs, be_after_leg=be, time_stop_bars=200)
            mf, pf = run(fit, None, pl, True, **kw)
            mh, ph = run(hold, None, pl, True, **kw)
            print(row(name, mf, pf, mh, ph))

    elif mode == "stack":
        print("## Do the supported ingredients compose?\n")
        print(HEAD)
        combos = [
            ("bare divergence", dict(trigger="none", mfi_min=None), False),
            ("+ structure break", dict(trigger="slope", mfi_min=None), False),
            ("+ money flow", dict(trigger="slope", mfi_min=0.0), False),
            ("+ daily gate", dict(trigger="slope", mfi_min=0.0), True),
        ]
        for name, over, gate in combos:
            kw = dict(base_kw, **over)
            mf, pf = run(fit, None, plan, gate, **kw)
            mh, ph = run(hold, None, plan, gate, **kw)
            print(row(name, mf, pf, mh, ph))


if __name__ == "__main__":
    main()
