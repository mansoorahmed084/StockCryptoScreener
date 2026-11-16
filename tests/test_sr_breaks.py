"""S&R Levels with Breaks rebuild (freqtrade-lab/research/sr_breaks.py): levels
are causal, a break is a close crossing the level with the volume and wick
rules, and the simulator books R as documented."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "freqtrade-lab" / "research"))

sr = pytest.importorskip("sr_breaks")


def walk(n=3000, seed=11):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.005, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.005, n))
    v = rng.lognormal(4, 0.8, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "volume": v}, index=idx)


def test_no_lookahead():
    df = walk()
    full = sr.indicator(df)
    for cut in (120, 1450, 2999):
        pd.testing.assert_frame_equal(sr.indicator(df.iloc[:cut]), full.iloc[:cut])


def test_level_appears_one_bar_after_confirmation():
    # a pivot high at bar 20 (width 15) is confirmed at bar 35, usable at 36
    n = 60
    h = np.full(n, 100.0)
    h[20] = 110.0
    df = pd.DataFrame({"open": 99.0, "high": h, "low": 98.0, "close": 99.0,
                       "volume": 1.0},
                      index=pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"))
    ind = sr.indicator(df)
    assert np.isnan(ind.res.iloc[35])
    assert ind.res.iloc[36] == 110.0
    assert ind.res.iloc[59] == 110.0      # stays until a newer pivot


def test_break_rules():
    ind = sr.indicator(walk())
    b = ind[ind.b_up]
    assert len(b) > 0
    assert (b.x_up & b.vol_ok & ~b.bull_wick).all()
    assert (ind.osc[ind.b_up] > 20).all()


def test_ema_matches_pine_seed():
    x = np.arange(1.0, 13.0)
    e = sr._ema(x, 5)
    assert np.isnan(e[3]) and e[4] == pytest.approx(3.0)
    assert e[5] == pytest.approx(2 / 6 * 6 + 4 / 6 * 3.0)


def test_sim_3r_target_and_level_exit():
    n = 40
    o = np.full(n, 100.0)
    h = o + 1
    l = o - 1
    c = o.copy()
    atr = np.full(n, 1.0)
    res = np.full(n, 99.5)
    sup = np.full(n, 95.0)
    up = np.zeros(n, bool)
    up[31] = True                      # break on bar 31, entry 100 at bar 32
    dn = np.zeros(n, bool)
    h[34] = 108.0                      # bar-stop 98.9 -> risk 1.1, 3R = 103.3
    r3 = sr._sim(o, h, l, c, atr, res, sup, up, dn, 1, 0, 0, 3.0, 42, 0.005,
                 0.15, 0.0)
    assert sr.WHY[r3[6][0]] == "target"
    assert r3[5][0] == pytest.approx(3.0)
    c2 = c.copy()
    c2[36] = 94.0                      # close under support -> exit open of 37
    l2 = l.copy()
    l2[36] = 94.0
    rs = sr._sim(o, h, l2, c2, atr, res, sup, up, dn, 1, 1, 1, 3.0, 42, 0.005,
                 0.15, 0.0)
    # support stop 94.9: bar 36 low 94 hits it first
    assert sr.WHY[rs[6][0]] == "stop"
    assert rs[5][0] == pytest.approx(-1.0)
