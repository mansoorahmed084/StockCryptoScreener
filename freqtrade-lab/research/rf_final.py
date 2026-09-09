"""Validate the chosen refined config against the daily control.

    python research/rf_final.py [max_open]

Three checks the grid cannot do for itself:

1. **Lookahead.** Every refined signal is re-derived with all later 1h bars
   physically deleted. The daily signal already passed this; the 1h timing and
   the 1h stop are new code and have to pass it too.
2. **Fill resolution.** The grid walked exits on 1h bars. A 6% stop is far more
   sensitive to intrabar sequencing than the daily strategy's 21% stop, so the
   winner is re-run on 15m detail. If the result moves much, the 1h number was
   an artifact.
3. **The account.** Pooled R assumes every clustered signal could be filled.
   `tl_account.py` sizing -- bank the profit at exit, not at entry -- says what
   an account with a slot limit actually gets.

Everything is reported next to the daily control, which is the thing the
refinement has to beat.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness      # noqa: E402
import trendline    # noqa: E402
import refine       # noqa: E402
import campaign     # noqa: E402
import portfolio    # noqa: E402
from tl_final import FINAL                    # noqa: E402
from tl_account import simulate_honest        # noqa: E402
from tl_portfolio import CAPITAL              # noqa: E402

START = pd.Timestamp("2020-01-01", tz="UTC")
HOUR = pd.Timedelta("1h")
TIME_STOP_H = 365 * 24

# Chosen on FIT ratio (2.37, the highest of the family) from the grid, with the
# marginals agreeing: next_open beats every waiting mode, ltf_swing beats the
# daily stop, and a wide percent trail beats a tight one.
REFINED = dict(entry_mode="next_open", stop_mode="ltf_swing", wait_hours=72,
               atr_mult=1.0, swing_hours=24, atr_len=14, retest_tol=0.02,
               ema_len=20, min_risk_pct=0.02, max_risk_pct=0.25)
CONTROL = dict(REFINED, stop_mode="daily")
PLAN = dict(trail_pct=0.25)


def coins_available() -> list[str]:
    return [c for c in campaign.UNIVERSE
            if (harness.DATA_DIR / f"{c}_USDT-1d.feather").exists()
            and (harness.DATA_DIR / f"{c}_USDT-1h.feather").exists()]


def daily_sig(coin: str) -> pd.DataFrame:
    d = harness.load(f"{coin}/USDT", "1d")
    s = trendline.trendline_breakout(d, **FINAL)
    return s[s.index >= START] if not s.empty else s


def collect(coins: list[str], kw: dict, detail_tf: str = "1h") -> list:
    plan = harness.ExitPlan(legs=[(100.0, 1.0)], time_stop_bars=TIME_STOP_H,
                            **PLAN)
    out = []
    for c in coins:
        ds = daily_sig(c)
        if ds.empty:
            continue
        h = harness.load(f"{c}/USDT", "1h")
        sig = refine.refined_signals(ds, h, **kw)
        if sig.empty:
            continue
        try:
            det = harness.load(f"{c}/USDT", detail_tf)
        except FileNotFoundError:
            continue
        for tr in harness.simulate(sig, h, det, plan, base_bar=HOUR):
            out.append((tr, c))
    return out


def pooled(trades: list) -> dict:
    m = harness.metrics([t for t, _ in trades])
    if m.get("n"):
        yrs = 6.7
        m["annual_r"] = round(m["n"] * m["avg_r"] / yrs, 1)
        m["ratio"] = round(m["annual_r"] / m["max_dd_r"], 2) if m["max_dd_r"] else 0
    return m


def lookahead_check(coins: list[str], kw: dict, per_coin: int = 5) -> None:
    checked = missing = 0
    for c in coins[:22]:
        ds = daily_sig(c)
        if ds.empty:
            continue
        h = harness.load(f"{c}/USDT", "1h")
        sig = refine.refined_signals(ds, h, **kw)
        for ts in sig.index[:per_coin]:
            i = h.index.get_loc(ts)
            # Cut the frame at the DECISION bar. Nothing after it exists -- not
            # even the bar the trade enters on.
            trunc = h.iloc[:i + 1].copy()
            s2 = refine.refined_signals(ds, trunc, **kw)
            checked += 1
            if s2.empty or s2.index[-1] != ts:
                missing += 1
                print(f"    LOOKAHEAD: {c} {ts} vanishes when future removed")
    print(f"  {checked} refined signals replayed, {missing} used the future")


def main() -> None:
    max_open = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    coins = coins_available()
    fit, hold = campaign.split(coins)
    print("# REFINED vs CONTROL — same daily breakouts, different stop\n")
    print(f"# refined: {REFINED['entry_mode']} entry, "
          f"{REFINED['stop_mode']} stop x{REFINED['atr_mult']} ATR(1h), "
          f"exit {PLAN}")
    print(f"# control: {CONTROL['entry_mode']} entry, daily stop, "
          f"exit {PLAN}\n")

    print("## 1. Does the refined signal use the future?")
    lookahead_check(coins, REFINED)

    print("\n## 2. Pooled R — 1h fills vs 15m fills")
    print("| variant | detail | basket | n | win% | avgR | PF | annR | "
          "maxDD_R | **ratio** |")
    print("|" + "---|" * 10)
    store = {}
    for name, kw in (("control", CONTROL), ("refined", REFINED)):
        for det in ("1h", "15m"):
            for bname, cs in (("FIT", fit), ("HOLDOUT", hold)):
                tr = collect(cs, kw, det)
                store[(name, det, bname)] = tr
                m = pooled(tr)
                if not m.get("n"):
                    continue
                print(f"| {name} | {det} | {bname} | {m['n']} | "
                      f"{m['win_net_pct']} | {m['avg_r']:+.3f} | {m['pf']} | "
                      f"{m['annual_r']} | {m['max_dd_r']} | "
                      f"**{m.get('ratio', 0):.2f}** |")

    print(f"\n## 3. The account — 15m fills, max {max_open} open, 1% risk, "
          "profit banked at exit")
    print("| variant | coins | signals | filled | win% | **CAGR** | PF | "
          "**maxDD** | losing years |")
    print("|" + "---|" * 9)
    years = {}
    for name, kw in (("control", CONTROL), ("refined", REFINED)):
        for bname, cs in (("FIT", fit), ("HOLDOUT", hold), ("ALL", coins)):
            tr = (store.get((name, "15m", bname))
                  if bname != "ALL" else collect(coins, kw, "15m"))
            if not tr:
                continue
            a = simulate_honest(tr, CAPITAL, 0.01, max_open)
            if a.empty:
                continue
            yrs = (a["exit"].max() - a["entry"].min()).days / 365.25
            s = portfolio.summary(a, yrs, CAPITAL)
            by = portfolio.by_year(a, CAPITAL)
            if bname == "ALL":
                years[name] = by
            print(f"| {name} | {bname} | {len(tr)} | {s['n']} | {s['win%']} | "
                  f"**{s['cagr%']:.1f}%** | {s['pf']} | **{s['max_dd%']:.1f}%** | "
                  f"{int((by['return%'] < 0).sum())}/{len(by)} |")

    for name, by in years.items():
        print(f"\n### {name}, whole universe, year by year")
        print(by.to_string())


if __name__ == "__main__":
    main()
