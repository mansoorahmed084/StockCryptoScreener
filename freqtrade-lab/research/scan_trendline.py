"""Live scan: which coins are pressing against a long-term descending trendline.

    python research/scan_trendline.py [days_back]

The TAO chart that started this work showed price sitting ON the line, not
through it — which is the state worth watching, because the entry is a close
above it. So this reports two things per coin:

  NEAR   the line is valid today and price is within reach of it, with the
         distance in percent. These are the watchlist.
  BROKE  the entry already fired in the last `days_back` days.

The line is rebuilt exactly as `trendline.trendline_breakout` builds it, from
bars strictly before the bar being judged, so nothing here is hindsight. A coin
with no row has no qualifying falling line: either its highest high is too
recent, the line is not falling, price has not dropped far enough beneath it,
or too few highs sit on it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness      # noqa: E402
import trendline    # noqa: E402
import campaign     # noqa: E402
from tl_campaign import BASE  # noqa: E402

CFG = dict(BASE, min_span=120)
NEAR_PCT = 0.15          # report the line if price is within this of it


def line_now(df: pd.DataFrame, cfg: dict) -> dict | None:
    """The descending line as it stands on the LAST closed bar, or None."""
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    i = len(df) - 1
    if i < cfg["lookback"] + 1:
        return None

    lo_w = i - cfg["lookback"]
    a = lo_w + int(np.argmax(highs[lo_w:i]))
    if i - a < cfg["min_span"]:
        return None
    ks = np.arange(a + 1, i)
    if ks.size == 0:
        return None
    s = float(((highs[a + 1:i] - highs[a]) / (ks - a)).max())
    if s >= 0:
        return None

    trough = float(lows[a:i].min())
    if highs[a] <= 0 or (highs[a] - trough) / highs[a] < cfg["min_drop_pct"]:
        return None
    line = highs[a] + s * (np.arange(a, i) - a)
    touches = int(np.sum(highs[a:i] >= line * (1.0 - cfg["touch_tol"])))
    if touches < cfg["min_touches"]:
        return None

    level = highs[a] + s * (i - a)
    close = float(df["close"].iloc[-1])
    return {"level": level, "close": close, "anchor": df.index[a],
            "anchor_high": highs[a], "span": i - a, "touches": touches,
            "gap_pct": 100 * (level - close) / close,
            "fall_pct_yr": 100 * (1 - (1 + s / highs[a]) ** 365) if highs[a] else 0.0}


def main() -> None:
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    near, broke = [], []

    for c in campaign.UNIVERSE:
        try:
            df = harness.load(f"{c}/USDT", "1d")
        except FileNotFoundError:
            continue

        sig = trendline.trendline_breakout(df, **CFG)
        if not sig.empty:
            cut = df.index[-1] - pd.Timedelta(days=days_back)
            for ts, r in sig[sig.index >= cut].iterrows():
                px = float(df.loc[ts, "close"])
                broke.append({"coin": c, "broke": ts.date(),
                              "days_ago": (df.index[-1] - ts).days,
                              "close_then": px, "now": float(df["close"].iloc[-1]),
                              "stop": r["stop"],
                              "risk_%": round(100 * (px - r["stop"]) / px, 1)})

        ln = line_now(df, CFG)
        if ln and -3.0 <= ln["gap_pct"] <= 100 * NEAR_PCT:
            near.append({"coin": c, "close": ln["close"],
                         "line": round(ln["level"], 6),
                         "gap_%": round(ln["gap_pct"], 1),
                         "line_from": ln["anchor"].date(),
                         "span_d": ln["span"], "touches": ln["touches"]})

    print(f"# long-term descending trendlines, daily, as of "
          f"{harness.load('BTC/USDT', '1d').index[-1].date()}")
    print(f"# lookback {CFG['lookback']}d, min span {CFG['min_span']}d, "
          f"min drop {CFG['min_drop_pct']:.0%}, {CFG['min_touches']} touches\n")

    print(f"## BROKE OUT in the last {days_back} days  (the entry fired)")
    if broke:
        print(pd.DataFrame(broke).sort_values("days_ago").to_string(index=False))
    else:
        print("none")

    print(f"\n## PRESSING the line (within {NEAR_PCT:.0%}) — the watchlist")
    if near:
        print(pd.DataFrame(near).sort_values("gap_%").to_string(index=False))
    else:
        print("none")
    print("\nA negative gap means price is already above the line but the break "
          "bar itself did not qualify (volume, risk cap, or cooldown).")


if __name__ == "__main__":
    main()
