"""Live scan: which coins are showing a VMC bullish divergence on several timeframes.

    python research/scan_divergence.py [recent_bars]

Uses the repo's own `VuManChuCipherB`, so the divergences are the same ones the
screener and the dashboard would draw. A divergence pivot is only counted once
confirmed by `pivot_lookback` later closes — the same knowability rule the
backtests use — so nothing here is visible only in hindsight.

For each coin and timeframe it reports how many bars ago the last bullish
divergence was confirmed AND is still structurally valid. A divergence whose
pivot low has since been traded through is discarded, not reported: price made
a lower low and the oscillator followed, which is continuation, not divergence.
The `broken` column counts how many were discarded that way.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import harness                                          # noqa: E402
from backend.config import load_config                  # noqa: E402
from backend.indicators.vumanchu import VuManChuCipherB  # noqa: E402
from backend.indicators import common                    # noqa: E402
from backend.screener import rs                          # noqa: E402

PIVOT = 3
# Breach depth below which a break is reported as "marginal" rather than
# "broken". Reporting only -- breach_test.py measured shallow breaches at
# -0.196R against -0.204R for deep ones on 4h across 29 coins, i.e. no
# difference, so a marginal breach still does NOT count as an active signal.
MARGINAL_BREACH = 0.01
TIMEFRAMES = ["1w", "1d", "4h", "1h", "15m"]

# How long a divergence counts as "active", per timeframe. Chosen so each means
# a comparable amount of WALL-CLOCK time (roughly 3 weeks down to 8 hours) --
# a flat bar count would make 15m absurdly strict and 1w absurdly loose.
ACTIVE_BARS = {"1w": 3, "1d": 5, "4h": 12, "1h": 24, "15m": 32}
COINS = ["BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "SOL", "DOT", "LTC", "LINK",
         "AVAX", "TRX", "ATOM", "ETC", "XLM", "BCH", "FIL", "NEAR", "ALGO",
         "VET", "ICP", "HBAR", "AAVE", "UNI", "SAND", "MANA", "AXS", "THETA",
         "EGLD"]


def weekly(df1d: pd.DataFrame) -> pd.DataFrame:
    return df1d.resample("W-MON", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}).dropna()


def last_valid_bull_div(df: pd.DataFrame) -> dict:
    """Most recent bull divergence that is still STRUCTURALLY VALID.

    A bull divergence rests on a pivot low. Once price trades back below that
    low, the premise is gone: price made a lower low and the oscillator
    followed, which is continuation, not divergence. The earlier version of
    this scan ignored that and reported dead signals as live — AAVE on
    2026-09-08 was flagged as a fresh 1h signal three bars after it had been
    stopped out.

    Returns bars_ago / wt2_at_pivot / pivot_low for the newest surviving
    divergence, plus how many newer ones were discarded as broken.
    """
    res = VuManChuCipherB(pivot_lookback=PIVOT).compute(df)
    wt2 = res.panes.get("wt2")
    if wt2 is None:
        return {"ago": None, "invalidated": 0}
    n = len(df)
    lows = df["low"].to_numpy()

    cands = []
    for m in res.markers:
        if m.kind != "bull_div":
            continue
        p = df.index.get_loc(m.ts)
        conf = p + PIVOT
        if conf < n:
            cands.append((n - 1 - conf, p))
    cands.sort()                                  # newest first

    invalidated = 0
    worst_marginal = None
    for ago, p in cands:
        pivot_low = float(lows[p])
        since = float(lows[p + 1:].min()) if n > p + 1 else pivot_low
        depth = (pivot_low - since) / pivot_low if pivot_low > 0 else 0.0
        if depth > 0:
            invalidated += 1
            # remember the shallowest recent break for reporting, but do NOT
            # promote it to active: measured no better than a deep break
            if depth <= MARGINAL_BREACH and worst_marginal is None:
                worst_marginal = {"ago": ago, "wt2": float(wt2.iloc[p]),
                                  "low": pivot_low, "breach": depth}
            continue
        return {"ago": ago, "wt2": float(wt2.iloc[p]), "low": pivot_low,
                "invalidated": invalidated, "breach": 0.0,
                "wt2_now": float(wt2.iloc[-1])}
    return {"ago": None, "invalidated": invalidated, "marginal": worst_marginal}


def main() -> None:
    scale = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    windows = {tf: max(1, int(round(b * scale))) for tf, b in ACTIVE_BARS.items()}
    params_1d = load_config().classifier_params("1d")
    rows = []

    for coin in COINS:
        pair = f"{coin}/USDT"
        frames: dict[str, pd.DataFrame] = {}
        for tf in ("1d", "4h", "1h", "15m"):
            try:
                frames[tf] = harness.load(pair, tf)
            except FileNotFoundError:
                pass
        if "1d" not in frames:
            continue
        frames["1w"] = weekly(frames["1d"])

        entry = {"coin": coin}
        for tf in TIMEFRAMES:
            df = frames.get(tf)
            if df is None or len(df) < 120:
                entry[tf] = None
                continue
            entry[tf] = last_valid_bull_div(df)

        d1 = frames["1d"]
        hist = rs.classify_history(d1["close"], params_1d, drop_forming=False)
        entry["regime"] = hist["direction"].iloc[-1] if len(hist) else "unknown"
        mfi = common.vumanchu_moneyflow(d1)
        entry["mflow"] = "green" if mfi.iloc[-1] > 0 else "red"
        entry["price"] = float(d1["close"].iloc[-1])
        entry["active"] = sum(
            1 for tf in TIMEFRAMES
            if entry.get(tf) and entry[tf].get("ago") is not None
            and entry[tf]["ago"] <= windows[tf])
        entry["killed"] = sum(entry[tf].get("invalidated", 0) for tf in TIMEFRAMES
                              if entry.get(tf))
        rows.append(entry)

    rows.sort(key=lambda r: (-r["active"], r["coin"]))
    asof = frames["1h"].index[-1] if "1h" in frames else frames["1d"].index[-1]

    print(f"# VMC bullish divergence scan — data through {asof} UTC")
    print("# active windows: " + ", ".join(f"{tf}<={w}b"
                                           for tf, w in windows.items()) + "\n")
    print("| coin | TFs active | 1w | 1d | 4h | 1h | 15m | daily regime | "
          "money flow | broken |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        cells = []
        for tf in TIMEFRAMES:
            v = r.get(tf)
            if not v or v.get("ago") is None:
                mg = (v or {}).get("marginal")
                if mg:
                    cells.append(f"marg {mg['ago']}b (-{mg['breach']*100:.1f}%)")
                else:
                    cells.append("—" if not v or not v.get("invalidated")
                                 else f"void x{v['invalidated']}")
            else:
                mark = "**" if v["ago"] <= windows[tf] else ""
                cells.append(f"{mark}{v['ago']}b{mark} (wt {v['wt2']:.0f})")
        flag = "**" if r["active"] >= 2 else ""
        print(f"| {flag}{r['coin']}{flag} | {flag}{r['active']}{flag} | "
              + " | ".join(cells)
              + f" | {r['regime']} | {r['mflow']} | {r['killed']} |")

    multi = [r for r in rows if r["active"] >= 2]
    print(f"\n## {len(multi)} coins with divergence active on 2+ timeframes\n")
    for r in multi:
        tfs = [tf for tf in TIMEFRAMES
               if r.get(tf) and r[tf].get("ago") is not None
               and r[tf]["ago"] <= windows[tf]]
        print(f"- **{r['coin']}** — {', '.join(tfs)} · daily regime "
              f"*{r['regime']}* · money flow *{r['mflow']}* · "
              f"last {r['price']:.4f}")


if __name__ == "__main__":
    main()
