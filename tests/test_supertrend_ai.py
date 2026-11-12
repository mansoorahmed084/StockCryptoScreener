"""SuperTrend AI rebuild (freqtrade-lab/research/supertrend_ai.py): the
indicator never looks ahead, the line sits on the right side of price, and the
simulator books R the way the docstring says."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "freqtrade-lab" / "research"))

st = pytest.importorskip("supertrend_ai")


def walk(n=600, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.005, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.005, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "volume": 1.0}, index=idx)


def test_no_lookahead():
    df = walk()
    full = st.indicator(df)
    for cut in (150, 333, 599):
        part = st.indicator(df.iloc[:cut])
        pd.testing.assert_frame_equal(part, full.iloc[:cut])


def test_line_on_the_right_side():
    ind = st.indicator(walk())
    live = ind[ind.os >= 0]
    c = walk()["close"].reindex(live.index)
    assert (c[live.os == 1] >= live.ts[live.os == 1]).all()
    assert (c[live.os == 0] <= live.ts[live.os == 0]).all()
    assert live.factor.between(1.0, 5.0).all()


def test_single_factor_has_no_best_cluster():
    """One factor: every score ties, Pine's first-nearest rule puts it in
    cluster 0, the 'best' cluster stays empty and no line is drawn."""
    ind = st.indicator(walk(), fmin=3.0, fmax=3.0, step=0.5)
    assert (ind.os == -1).all()


def test_final_line_is_a_supertrend_on_the_chosen_factor():
    """Given the factor the clustering chose on each bar, a hand-written
    SuperTrend must flip exactly where the indicator flips."""
    df = walk()
    ind = st.indicator(df)
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    fac = ind.factor.to_numpy()
    assert np.isfinite(fac).sum() > 400
    atr = st.smc._atr(h, l, c, 10)
    hl2 = (h + l) / 2
    up = lo = np.nan
    os = 0
    ref = []
    for i in range(1, len(c)):
        if np.isnan(fac[i]):
            ref.append(-1)
            continue
        u, d = hl2[i] + fac[i] * atr[i], hl2[i] - fac[i] * atr[i]
        up = min(u, up) if (up == up and c[i - 1] < up) else u
        lo = max(d, lo) if (lo == lo and c[i - 1] > lo) else d
        os = 1 if c[i] > up else 0 if c[i] < lo else os
        ref.append(os)
    assert ind.os.to_numpy()[1:].tolist() == ref


def test_sim_long_then_flip_exit():
    # flat, a bull flip on bar 2, a bear flip on bar 5
    o = np.array([10, 10, 10, 11, 12, 13, 12, 11.0])
    h = o + 0.5
    l = o - 0.5
    c = o.copy()
    os_ = np.array([0, 0, 1, 1, 1, 0, 0, 0])
    ts = np.array([12, 12, 9, 9.5, 10, 14, 14, 14.0])
    score = np.full(8, 5.0)
    bias = np.zeros(8, np.int64)
    res = st._sim(o, h, l, c, os_, ts, score, bias, 1, 1, 0, 0.0, False, 0.0)
    sig, tin, tout, d, px, stop, r, why, mfe, sc = res
    assert len(r) == 1
    assert (sig[0], tin[0], tout[0], d[0]) == (2, 3, 6, 1)
    # entry 11 (open of bar 3), risk 11 - 9 = 2, exit 12 (open of bar 6)
    assert r[0] == pytest.approx(0.5)
    assert st.WHY[why[0]] == "flip"


def test_sim_touch_stop_inside_bar():
    o = np.array([10, 10, 10, 11, 12, 9, 9, 9.0])
    h = o + 0.5
    l = o - 0.5
    c = o.copy()
    os_ = np.array([0, 0, 1, 1, 1, 1, 1, 1])
    ts = np.array([12, 12, 9, 9.5, 10, 10, 10, 10.0])
    res = st._sim(o, h, l, c, os_, ts, np.full(8, 5.0), np.zeros(8, np.int64),
                  1, 1, 1, 0.0, False, 0.0)
    r, why = res[6], res[7]
    # bar 5 opens at 9, below the 10 stop: filled at the open, a gap loss
    assert r[0] == pytest.approx((9 - 11) / 2)
    assert st.WHY[why[0]] == "stop"
