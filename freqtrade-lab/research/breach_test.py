"""Do shallow breaches of a divergence low perform better or worse than clean ones?

    python research/breach_test.py [timeframe] [tolerance_pct]

The scanner currently voids a bull divergence the moment price trades below the
pivot low that formed it. But four live cases breached by under 1%, and a breach
that shallow is arguably the SECOND LOW OF A DOUBLE BOTTOM -- the structure the
trader described -- rather than an invalidation.

That is a measurable question, so measure it. Every confirmed divergence is
sorted into one of three buckets, all of them knowable at the time:

    ALL      every confirmed divergence, entry at the confirmation bar. The
             only honest baseline, because it needs no knowledge of the future.
    CLEAN    price never traded below the pivot low inside the window.
             *** LOOKAHEAD -- NOT TRADEABLE. *** The entry sits before the bars
             used to classify it, so this bucket selects trades that did not go
             against you. Kept only to show the size of the illusion.
    SHALLOW  price dipped below by <= tol, then RECLAIMED the level.
             Entry on the reclaim, stop under the dip low.
    DEEP     price broke by more than tol. Measured too, to check the
             scanner is right to discard these.

No bucket uses information from after its own entry. The SHALLOW entry is
strictly later than the CLEAN one, which is the honest cost of waiting.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import harness                                          # noqa: E402
import strategies                                       # noqa: E402
from backend.indicators.vumanchu import VuManChuCipherB  # noqa: E402

PIVOT = 3
COINS = ["BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "SOL", "DOT", "LTC", "LINK",
         "AVAX", "TRX", "ATOM", "ETC", "XLM", "BCH", "FIL", "NEAR", "ALGO",
         "VET", "ICP", "HBAR", "AAVE", "UNI", "SAND", "MANA", "AXS", "THETA",
         "EGLD"]
BAR = {"15m": pd.Timedelta("15min"), "1h": pd.Timedelta("1h"),
       "4h": pd.Timedelta("4h"), "1d": pd.Timedelta("1D")}
DETAIL = {"15m": "5m", "1h": "5m", "4h": "1h", "1d": "1h"}


def bucket_signals(df: pd.DataFrame, *, tol: float, window: int,
                   atr_mult: float = 1.0, wt2_max: float = -40.0,
                   max_risk_pct: float = 0.10) -> dict[str, pd.DataFrame]:
    """Split confirmed bull divergences into CLEAN / SHALLOW / DEEP."""
    res = VuManChuCipherB(pivot_lookback=PIVOT).compute(df)
    wt2 = res.panes.get("wt2")
    if wt2 is None:
        return {}
    a = strategies.atr(df, 14).to_numpy()
    lows, highs, closes = (df["low"].to_numpy(), df["high"].to_numpy(),
                           df["close"].to_numpy())
    n = len(df)
    out: dict[str, list] = {"ALL": [], "CLEAN": [], "SHALLOW": [], "DEEP": []}

    for m in res.markers:
        if m.kind != "bull_div":
            continue
        p = df.index.get_loc(m.ts)
        c = p + PIVOT                       # confirmation bar
        if c >= n - 2 or float(wt2.iloc[p]) > wt2_max:
            continue
        L = float(lows[p])
        end = min(n, c + window + 1)

        # the honest baseline: take every confirmed divergence at confirmation
        if np.isfinite(a[c]):
            base_stop = L - atr_mult * a[c]
            base_ref = float(closes[c])
            if base_stop > 0 and base_ref > 0                     and (base_ref - base_stop) / base_ref <= max_risk_pct:
                out["ALL"].append({"ts": df.index[c], "direction": 1,
                                   "stop": float(base_stop)})

        # first bar after confirmation that trades below the pivot low
        rel = np.flatnonzero(lows[c + 1:end] < L)
        if rel.size == 0:
            bucket, sig_bar, stop_ref = "CLEAN", c, L
        else:
            i = c + 1 + int(rel[0])
            depth = (L - float(lows[i])) / L
            if depth > tol:
                bucket, sig_bar, stop_ref = "DEEP", i, float(lows[i])
            else:
                # wait for the reclaim -- that is the double-bottom trigger
                rec = np.flatnonzero(closes[i:end] > L)
                if rec.size == 0:
                    continue                # never reclaimed inside the window
                bucket = "SHALLOW"
                sig_bar = i + int(rec[0])
                stop_ref = float(lows[i])   # stop under the SECOND low

        if sig_bar >= n - 1 or not np.isfinite(a[sig_bar]):
            continue
        stop = stop_ref - atr_mult * a[sig_bar]
        ref = float(closes[sig_bar])
        if stop <= 0 or ref <= 0 or (ref - stop) / ref > max_risk_pct:
            continue
        out[bucket].append({"ts": df.index[sig_bar], "direction": 1,
                            "stop": float(stop)})

    frames = {}
    for k, rows in out.items():
        if rows:
            f = pd.DataFrame(rows).set_index("ts")
            frames[k] = f[~f.index.duplicated(keep="first")].sort_index()
    return frames


def main() -> None:
    tf = sys.argv[1] if len(sys.argv) > 1 else "4h"
    tol = float(sys.argv[2]) / 100 if len(sys.argv) > 2 else 0.01
    window = {"15m": 32, "1h": 24, "4h": 12, "1d": 5}[tf]
    plan = harness.ExitPlan(legs=[(3.0, 1.0)], time_stop_bars=120)

    keys = ("ALL", "CLEAN", "SHALLOW", "DEEP")
    pooled: dict[str, list] = {k: [] for k in keys}
    per_coin: dict[str, list] = {k: [] for k in keys}

    for coin in COINS:
        pair = f"{coin}/USDT"
        try:
            base, det = harness.load(pair, tf), harness.load(pair, DETAIL[tf])
        except FileNotFoundError:
            continue
        frames = bucket_signals(base, tol=tol, window=window)
        for k, sig in frames.items():
            tr = harness.simulate(sig, base, det, plan, base_bar=BAR[tf])
            if not tr:
                continue
            pooled[k] += tr
            if len(tr) >= 8:
                per_coin[k].append(harness.metrics(tr)["avg_r"])

    print(f"# Breach test — {tf}, tolerance {tol*100:g}%, "
          f"reclaim window {window} bars, {len(COINS)} coins\n")
    print("| bucket | trades | win% | hit 3R% | avgR | PF | maxDD_R | streak "
          "| coins tested | coins positive |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for k in keys:
        tr = pooled[k]
        if not tr:
            print(f"| {k} | 0 |" + " — |" * 9)
            continue
        m = harness.metrics(tr)
        pc = per_coin[k]
        pos = sum(1 for x in pc if x > 0)
        tag = f"{k} (LOOKAHEAD)" if k == "CLEAN" else k
        print(f"| **{tag}** | {m['n']} | {m['win_net_pct']} | "
              f"{m['win_target_pct']} | **{m['avg_r']:+.3f}** | {m['pf']} | "
              f"{m['max_dd_r']} | {m['worst_streak']} | {len(pc)} | "
              f"**{pos}/{len(pc)}**" + " |")


if __name__ == "__main__":
    main()
