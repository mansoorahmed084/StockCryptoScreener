"""Market breadth: what does it mean when the WHOLE universe is oversold at once?

Every test in this project so far treats each coin's signal in isolation. But
crypto alts move together, so signals arrive in clusters. A divergence that
prints while three other coins are oversold is a different event from one that
prints while sixty are.

Two opposite hypotheses, both plausible, neither tested:

    WASHOUT   high breadth is a market-wide capitulation, so these are the
              highest-quality longs and the bounce is violent
    KNIFE     high breadth means the whole market is in freefall, individual
              structure means nothing, and you are catching a falling knife

Whichever is true, it should be a strong filter, and it is cheap to measure.
Breadth is computed once for the universe and reused for every coin, so it
costs one pass rather than one per experiment.

Nothing here looks forward: breadth at bar T uses only closed bars at or before
T, on the same timeframe as the signal.
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
from backend.indicators import wavetrend                # noqa: E402

_CACHE: dict = {}


def universe_breadth(coins: list[str], tf: str, *,
                     oversold: float = -50.0) -> pd.DataFrame:
    """Fraction of the universe that is oversold / rising, per bar.

    Returns a frame indexed by timestamp with:
        os_frac    share of coins whose WT2 <= oversold
        up_frac    share of coins whose WT2 rose on that bar
        n_cover    how many coins had data on that bar
    """
    key = (tuple(coins), tf, oversold)
    if key in _CACHE:
        return _CACHE[key]

    os_cols, up_cols = {}, {}
    for c in coins:
        try:
            df = harness.load(f"{c}/USDT", tf)
        except FileNotFoundError:
            continue
        if len(df) < 300:
            continue
        _, wt2 = wavetrend.wavetrend(df)
        os_cols[c] = (wt2 <= oversold).astype(float)
        up_cols[c] = (wt2 > wt2.shift(1)).astype(float)

    if not os_cols:
        raise RuntimeError("no coins loaded for breadth")
    os_df = pd.DataFrame(os_cols)
    up_df = pd.DataFrame(up_cols)
    cover = os_df.notna().sum(axis=1)
    out = pd.DataFrame({
        "os_frac": os_df.sum(axis=1) / cover.replace(0, np.nan),
        "up_frac": up_df.sum(axis=1) / cover.replace(0, np.nan),
        "n_cover": cover,
    }).dropna()
    # only trust bars where most of the universe is actually listed
    out = out[out["n_cover"] >= max(8, int(0.5 * len(os_cols)))]
    _CACHE[key] = out
    return out


def breadth_percentile(breadth: pd.DataFrame, column: str = "os_frac",
                       lookback: int = 2000) -> pd.Series:
    """Where today's breadth sits in its own recent history, 0..1.

    A raw fraction is not comparable across regimes -- 20% oversold means
    something different in a bull year than a bear one -- so rank it against a
    trailing window instead of using an absolute threshold.
    """
    return breadth[column].rolling(lookback, min_periods=lookback // 4).rank(pct=True)
