"""Does the long-term trendline break earn more per unit of drawdown?

    python research/tl_campaign.py base      # one config, full report
    python research/tl_campaign.py exits     # how to take the trade off
    python research/tl_campaign.py line      # how the line is drawn
    python research/tl_campaign.py quality   # drop / touches / volume filters
    python research/tl_campaign.py weekly    # the same line on weekly candles

The bar to clear is set in research/HANDOVER.md: DailyDivBreakout earns
annual_R 3.74 against maxDD_R 6.7, a ratio of 0.56, and that ratio is what an
account actually owns because position size scales return and drawdown equally.
A strategy that catches 100% moves but only trades twice a year, or gives back
most of it, does not beat that -- so every row here reports annual_R, maxDD_R
and the ratio, and the verdict column is HOLDOUT coins, never fit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness      # noqa: E402
import trendline    # noqa: E402
import strategies   # noqa: E402
from campaign import UNIVERSE, split  # noqa: E402

TF, DETAIL, BAR = "1d", "1h", pd.Timedelta("1D")
START = pd.Timestamp("2020-01-01", tz="UTC")   # 1h detail coverage begins here

BASE = dict(lookback=260, min_span=60, min_touches=3, touch_tol=0.03,
            min_drop_pct=0.25, stop_lookback=20, atr_mult=1.0,
            max_risk_pct=0.25, cooldown=20)


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


_GATE: dict = {}


def gate_for(pair: str, base: pd.DataFrame):
    if pair not in _GATE:
        _GATE[pair] = strategies.higher_tf_regime(
            base, harness.load("BTC/USDT", "1d"), "1d", pd.Timedelta("1D"))
    return _GATE[pair]


def run(coins: list[str], plan: harness.ExitPlan, *, weekly: bool = False,
        btc_gate: bool = False, **kw) -> dict:
    pooled, per, span = [], [], 0.0
    bar = pd.Timedelta("7D") if weekly else BAR
    for c in coins:
        pair = f"{c}/USDT"
        try:
            daily, det = harness.load(pair, TF), harness.load(pair, DETAIL)
        except FileNotFoundError:
            continue
        base = trendline.weekly(daily) if weekly else daily
        if len(base) < kw.get("lookback", 260) + 5:
            continue
        gate = gate_for(pair, base) if btc_gate else None
        sig = trendline.trendline_breakout(base, gate=gate, **kw)
        if sig.empty:
            continue
        sig = sig[sig.index >= START]
        if sig.empty:
            continue
        tr = harness.simulate(sig, base, det, plan, base_bar=bar)
        if not tr:
            continue
        pooled += tr
        span = max(span, (daily.index[-1] - max(daily.index[0], START)).days / 365.25)
        if len(tr) >= 4:
            per.append(harness.metrics(tr)["avg_r"])
    m = harness.metrics(pooled)
    if m.get("n") and span > 0:
        m["annual_r"] = round(m["n"] * m["avg_r"] / span, 2)
        m["per_year"] = round(m["n"] / span, 1)
        dd = m["max_dd_r"]
        m["ratio"] = round(m["annual_r"] / dd, 2) if dd > 0 else float("inf")
    m["coins_pos"] = sum(1 for x in per if x > 0)
    m["coins_n"] = len(per)
    return m


HEAD = ("| config | FIT n | avgR | annR || HOLD n | win% | **avgR** | PF | "
        "annR | maxDD_R | **ratio** | +coins |\n" + "|" + "---|" * 12)


def row(label: str, f: dict, h: dict) -> str:
    if not f.get("n") or not h.get("n"):
        return f"| {label} | {f.get('n', 0)} |" + " - |" * 11
    return (f"| {label} | {f['n']} | {f['avg_r']:+.2f} | {f.get('annual_r', 0):.2f} "
            f"|| {h['n']} | {h['win_net_pct']} | **{h['avg_r']:+.2f}** | {h['pf']} | "
            f"{h.get('annual_r', 0):.2f} | {h['max_dd_r']} | "
            f"**{h.get('ratio', 0):.2f}** | {h['coins_pos']}/{h['coins_n']} |")


def plan_of(name: str) -> harness.ExitPlan:
    T = 180
    BIG = [(100.0, 1.0)]          # unreachable: the trail is the real exit
    return {
        "3R": harness.ExitPlan(legs=[(3.0, 1.0)], time_stop_bars=T),
        "5R": harness.ExitPlan(legs=[(5.0, 1.0)], time_stop_bars=T),
        "8R": harness.ExitPlan(legs=[(8.0, 1.0)], time_stop_bars=T),
        "trail 2R": harness.ExitPlan(legs=BIG, trail_r=2.0, time_stop_bars=T),
        "trail 3R": harness.ExitPlan(legs=BIG, trail_r=3.0, time_stop_bars=T),
        "trail 4R": harness.ExitPlan(legs=BIG, trail_r=4.0, time_stop_bars=T),
        "trail 3R start 2R": harness.ExitPlan(legs=BIG, trail_r=3.0,
                                              trail_start_r=2.0, time_stop_bars=T),
        "half 2R then trail 3R": harness.ExitPlan(
            legs=[(2.0, 0.5), (100.0, 0.5)], be_after_leg=0, trail_r=3.0,
            time_stop_bars=T),
        "trail 3R 365d": harness.ExitPlan(legs=BIG, trail_r=3.0, time_stop_bars=365),
    }[name]


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "base"
    coins = available(UNIVERSE)
    fit, hold = split(coins)
    print(f"# LONG-TERM TRENDLINE BREAKOUT - {TF} candles, {DETAIL} detail fills")
    print(f"# universe {len(coins)} - FIT {len(fit)} / HOLDOUT {len(hold)}, "
          f"signals from {START.date()}")
    print("# benchmark to beat: DailyDivBreakout ratio 0.56 "
          "(annual_R 3.74 / maxDD_R 6.7)\n")

    if mode == "exits":
        print("## How should the trade be taken off?\n" + HEAD)
        for name in ["3R", "5R", "8R", "trail 2R", "trail 3R", "trail 4R",
                     "trail 3R start 2R", "half 2R then trail 3R", "trail 3R 365d"]:
            pl = plan_of(name)
            print(row(name, run(fit, pl, **BASE), run(hold, pl, **BASE)), flush=True)

    elif mode == "line":
        print("## How should the line be drawn?\n" + HEAD)
        pl = plan_of("trail 3R")
        for name, over in [
            ("lookback 130 (6mo)", dict(lookback=130)),
            ("lookback 260 (base)", dict()),
            ("lookback 400 (13mo)", dict(lookback=400)),
            ("lookback 550 (18mo)", dict(lookback=550)),
            ("min_span 30", dict(min_span=30)),
            ("min_span 60 (base)", dict()),
            ("min_span 120", dict(min_span=120)),
            ("min_span 200", dict(min_span=200)),
        ]:
            kw = dict(BASE, **over)
            print(row(name, run(fit, pl, **kw), run(hold, pl, **kw)), flush=True)

    elif mode == "quality":
        print("## Which quality filters earn their place?\n" + HEAD)
        pl = plan_of("trail 3R")
        for name, over in [
            ("no filters", dict(min_touches=2, min_drop_pct=0.0)),
            ("touches 3 (base)", dict()),
            ("touches 4", dict(min_touches=4)),
            ("drop 40%", dict(min_drop_pct=0.40)),
            ("drop 60%", dict(min_drop_pct=0.60)),
            ("volume 1.5x", dict(vol_mult=1.5)),
            ("volume 2.5x", dict(vol_mult=2.5)),
            ("stop 1.5 ATR", dict(atr_mult=1.5)),
            ("stop 0.5 ATR", dict(atr_mult=0.5)),
            ("risk cap 15%", dict(max_risk_pct=0.15)),
            ("BTC regime gate", dict()),
        ]:
            kw = dict(BASE, **over)
            g = name == "BTC regime gate"
            print(row(name, run(fit, pl, btc_gate=g, **kw),
                      run(hold, pl, btc_gate=g, **kw)), flush=True)

    elif mode == "weekly":
        print("## The same line on WEEKLY candles\n" + HEAD)
        for name, over in [("weekly, span 12w", dict(lookback=60, min_span=12,
                                                     stop_lookback=4, cooldown=4)),
                           ("weekly, span 20w", dict(lookback=80, min_span=20,
                                                     stop_lookback=4, cooldown=4)),
                           ("weekly, span 30w", dict(lookback=110, min_span=30,
                                                     stop_lookback=4, cooldown=4))]:
            kw = dict(BASE, **over)
            pl = harness.ExitPlan(legs=[(100.0, 1.0)], trail_r=3.0, time_stop_bars=52)
            print(row(name, run(fit, pl, weekly=True, **kw),
                      run(hold, pl, weekly=True, **kw)), flush=True)

    else:
        pl = plan_of("trail 3R")
        print("## Base config\n" + HEAD)
        f, h = run(fit, pl, **BASE), run(hold, pl, **BASE)
        print(row("base", f, h))
        print(f"\nFIT    {f}\nHOLD   {h}")


if __name__ == "__main__":
    main()
