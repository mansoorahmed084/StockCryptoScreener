"""Liquidity Swings rebuild (freqtrade-lab/research/liquidity_swings.py):
zones are causal, a sweep is a wick through and a close back, a close through
kills the zone, and the sweep-break hook leaves B_final unchanged when told to."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "freqtrade-lab" / "research"))

ls = pytest.importorskip("liquidity_swings")


def walk(n=800, seed=5):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.006, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.006, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "volume": 1.0}, index=idx)


def test_no_lookahead():
    df = walk()
    full = ls.zones(df)
    for cut in (100, 401, 799):
        pd.testing.assert_frame_equal(ls.zones(df.iloc[:cut]), full.iloc[:cut])


def frame_of(rows):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["volume"] = 1.0
    df.index = pd.date_range("2024-01-01", periods=len(df), freq="1h", tz="UTC")
    return df


def v_low(n_side=2):
    """A clean V: swing low at bar n_side with low 90, body 92-93."""
    rows = [[100 - i, 101 - i, 99 - i, 100 - i] for i in range(n_side)]
    rows.append([93, 94, 90, 92])
    rows += [[95 + i, 96 + i, 94 + i, 95 + i] for i in range(n_side)]
    return rows


def test_sweep_and_count():
    rows = v_low()
    rows.append([95, 95.5, 92.5, 95])   # touches the 90-92 zone? no (low 92.5)
    rows.append([94, 94.5, 91.0, 93])   # touch: low 91 < 92 -> count 1
    rows.append([93, 93.5, 89.0, 91])   # sweep: wick to 89, close 91 >= 90
    z = ls.zones(frame_of(rows), length=2)
    assert z.lz_btm.iloc[4] == 90 and z.lz_top.iloc[4] == 92
    assert z.lo_last.iloc[6] == -1
    assert z.lo_last.iloc[7] == 1      # swept, with one earlier touch
    assert z.lo_any.iloc[7] == 1


def test_close_through_kills_zone():
    rows = v_low()
    rows.append([93, 93.5, 88.0, 89])   # closes below 90: zone dead, no sweep
    rows.append([89, 92.0, 87.0, 91])
    z = ls.zones(frame_of(rows), length=2)
    assert z.lo_last.iloc[5] == -1
    assert np.isnan(z.lz_btm.iloc[5])
    assert z.lo_any.iloc[6] == -1


@pytest.mark.parametrize("coin", ["BTC", "SOL"])
def test_fractal_mode_is_b_final(coin):
    pytest.importorskip("pyarrow")
    if not ls.smc.have(coin, ls.BASE):
        pytest.skip("no candles on disk")
    a = ls.run_sb(coin, ls.SBCfg())
    b = ls.smc.run(coin, ls.B_FINAL, ls.BASE)
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))
