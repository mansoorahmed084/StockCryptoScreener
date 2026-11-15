"""Signals & Overlays own build (freqtrade-lab/research/signals_overlays.py): every
value is causal, signals and exits follow their rules, the sensitivity search
breaks ties the same way every time, and the simulator books R as documented."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "freqtrade-lab" / "research"))

so = pytest.importorskip("signals_overlays")


def walk(n=3000, seed=7):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.006, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.006, n))
    v = rng.lognormal(4, 0.8, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


SETTINGS = [
    {}, {"mode": "cont"}, {"auto": "medium"}, {"mode": "cont", "auto": "long"},
    {"filt": "trail"}, {"filt": "neo"}, {"filt": "strength"}, {"ml": "34"},
    {"mode": "cont", "ml": "12"}, {"sens": 20},
]


@pytest.mark.parametrize("kw", SETTINGS)
def test_no_lookahead(kw):
    df = walk()
    full = so.Book(df)
    f_sig, f_ex, f_cls = full.signals(**kw)
    for cut in (700, 1850):
        part = so.Book(df.iloc[:cut])
        sig, ex, cls = part.signals(**kw)
        assert np.array_equal(sig, f_sig[:cut])
        assert np.array_equal(ex, f_ex[:cut])
        assert np.array_equal(cls, f_cls[:cut])
        for name in ("trail", "tracer", "catcher", "lead", "lag", "trend_str"):
            np.testing.assert_allclose(getattr(part, name), getattr(full, name)[:cut],
                                       rtol=1e-12, equal_nan=True)
        mode = kw.get("mode", "conf")
        np.testing.assert_array_equal(part.optimal(mode), full.optimal(mode)[:cut])


def test_confirmation_signals_alternate_and_strong_agrees_with_baseline():
    b = so.Book(walk())
    sig, _, _ = b.signals()
    s = sig[sig != 0]
    assert len(s) > 20
    assert (np.sign(s[1:]) != np.sign(s[:-1])).all()
    i = np.flatnonzero(sig == 2)
    assert (b.c[i] > b.base[i]).all()
    i = np.flatnonzero(sig == -1)
    assert not (b.c[i] < b.base[i]).any()


@pytest.mark.parametrize("mode", ["conf", "cont"])
def test_exits_follow_their_signal_and_are_in_profit(mode):
    b = so.Book(walk())
    sig, ex, _ = b.signals(mode)
    assert (ex != 0).sum() > 5
    pos, entry, count = 0, np.nan, 0
    for t in range(b.n):
        if sig[t]:
            assert ex[t] == 0
            pos, entry, count = np.sign(sig[t]), b.c[t], 0
        elif ex[t]:
            count += 1
            assert ex[t] == pos
            assert pos * (b.c[t] - entry) > 0
            if mode == "cont":
                assert count == 1          # one exit per contrarian signal


def test_contrarian_strong_needs_the_strong_level():
    b = so.Book(walk(seed=3))
    sig, rs = b.cont(12)
    for t in np.flatnonzero(sig > 0):
        # walk back over the visit below 30 that this signal ends
        j = t - 1
        low = rs[j]
        while j > 0 and rs[j] < so.OS:
            low = min(low, rs[j])
            j -= 1
        assert (sig[t] == 2) == (low <= so.OS_STRONG)


def test_filters_only_drop_signals():
    b = so.Book(walk())
    raw, _, _ = b.signals()
    for filt, ok_bull, ok_bear in (
            ("trail", b.c > b.trail, b.c < b.trail),
            ("tracer", b.tracer_dir == 1, b.tracer_dir == -1),
            ("catcher", b.catcher_dir == 1, b.catcher_dir == -1),
            ("strength", b.trend_str > 50, b.trend_str > 50)):
        sig, _, _ = b.signals(filt=filt)
        assert ((sig == 0) | (sig == raw)).all()
        assert ok_bull[sig > 0].all() and ok_bear[sig < 0].all()
        assert 0 < (sig != 0).sum() < (raw != 0).sum()


def test_classifier_filter_and_class_range():
    b = so.Book(walk())
    for mode in ("conf", "cont"):
        _, _, cls = b.signals(mode)
        sig12, _, _ = b.signals(mode, ml="12")
        sig34, _, _ = b.signals(mode, ml="34")
        at = cls[cls != 0]
        assert at.min() >= 1 and at.max() <= 4
        assert np.isin(cls[sig12 != 0], (1, 2)).all()
        assert np.isin(cls[sig34 != 0], (3, 4)).all()


def test_cls_hi_is_the_nearest_rank_quartile_count():
    rng = np.random.default_rng(1)
    gz = rng.normal(size=400)
    gz[:30] = np.nan
    out = so._cls_hi(gz, 200)
    assert (out[:229] == 1).all()                      # window not full of real values
    for t in (229, 300, 399):
        w = np.sort(gz[t - 199:t + 1])
        q = [w[int(np.ceil(p * 200)) - 1] for p in (0.25, 0.5, 0.75)]
        assert out[t] == 1 + sum(gz[t] > x for x in q)


def test_best_breaks_ties_to_the_lower_index():
    rng = np.random.default_rng(2)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 800)))
    a = np.sign(rng.normal(size=800)).astype(np.int8)
    worse = (-a).astype(np.int8)
    # rows 0 and 1 are identical: their scores must tie exactly on every bar
    best = so._best(np.stack([a, a, worse]), c, 250)
    assert not (best == 1).any()


def test_autopilot_range_and_optimal_start():
    b = so.Book(walk())
    for auto, (lo, hi) in so.AUTO_RANGE.items():
        opt = b.optimal("conf", auto)
        assert np.isnan(opt[:250]).all()
        assert opt[250:].min() >= lo and opt[250:].max() <= hi


def test_rsi_and_ema_seeds():
    up = np.arange(1.0, 40.0)
    assert np.isnan(so.rsi(up)[13]) and so.rsi(up)[14] == 100.0
    e = so._ema(np.arange(1.0, 13.0), 5)
    assert np.isnan(e[3]) and e[4] == pytest.approx(3.0)


def test_smart_trail_side_and_ratchet():
    b = so.Book(walk())
    d, tr = b.trail_dir, b.trail
    same = (d[1:] == d[:-1]) & ~np.isnan(tr[:-1])
    assert (d[1:][same] * (b.c[1:][same] - tr[1:][same]) >= 0).all()
    step = (tr[1:] - tr[:-1])[same]
    assert (d[1:][same] * step >= 0).all()             # it never moves against the trend


def test_tpsl_levels_are_ordered():
    b = so.Book(walk())
    sig, _, _ = b.signals()
    lv, hit = b.tpsl(sig > 0, sig < 0, 5.0)
    tp1, tp2, sl1, sl2 = lv
    ok = ~np.isnan(tp1)
    up = tp1 > sl1
    assert ((tp2 > tp1) & (sl1 > sl2))[ok & up].all()
    assert ((tp2 < tp1) & (sl1 < sl2))[ok & ~up].all()
    assert hit.any()


def _flat(n=40):
    o = np.full(n, 100.0)
    return o, o + 1, o - 1, o.copy(), np.full(n, 1.0)


def test_sim_target_stop_and_cost_split():
    o, h, l, c, atr = _flat()
    sig = np.zeros(40, np.int8)
    ex = np.zeros(40, np.int8)
    sig[5] = 1                               # entry 100 at bar 6, stop 98, risk 2, 3R = 106
    h2 = h.copy()
    h2[9] = 107.0
    r = so._sim(o, h2, l, c, atr, sig, ex, 0, 2, False, 2, 2.0, 3.0, 42, 0.005, 0.15)
    assert so.WHY[r[6][0]] == "target" and r[3][0] == pytest.approx(3.0)
    assert r[4][0] == pytest.approx((100 + 106) / 2)      # net R = gross - cost x k
    l2 = l.copy()
    l2[9] = 97.0
    h3 = h.copy()
    h3[9] = 107.0                            # stop and target in one bar: the stop fills
    r = so._sim(o, h3, l2, c, atr, sig, ex, 0, 2, False, 2, 2.0, 3.0, 42, 0.005, 0.15)
    assert so.WHY[r[6][0]] == "stop" and r[3][0] == pytest.approx(-1.0)


def test_sim_flip_reverses_and_cross_exits_first():
    o, h, l, c, atr = _flat()
    o = o.copy()
    o[21] = 101.0
    sig = np.zeros(40, np.int8)
    ex = np.zeros(40, np.int8)
    sig[5], sig[20] = 1, -1
    r = so._sim(o, h, l, c, atr, sig, ex, 0, 2, False, 0, 2.0, 3.0, 42, 0.005, 0.15)
    assert list(so.WHY[r[6]]) == ["flip", "data_end"]
    assert r[1][0] == 21 and r[0][1] == 21 and r[2][1] == -1     # out and short at the same open
    assert r[3][0] == pytest.approx((101 - 100) / 2)
    ex[10] = 1
    r = so._sim(o, h, l, c, atr, sig, ex, 0, 1, False, 1, 2.0, 3.0, 42, 0.005, 0.15)
    assert so.WHY[r[6][0]] == "cross" and r[1][0] == 11 and len(r[0]) == 1   # long only


def test_sim_strong_only_and_risk_limits():
    o, h, l, c, atr = _flat()
    sig = np.zeros(40, np.int8)
    ex = np.zeros(40, np.int8)
    sig[5], sig[15] = 1, 2
    r = so._sim(o, h, l, c, atr, sig, ex, 0, 2, True, 0, 2.0, 3.0, 42, 0.005, 0.15)
    assert list(r[0]) == [16]
    r = so._sim(o, h, l, c, atr * 0.1, sig, ex, 0, 2, False, 0, 2.0, 3.0, 42, 0.005, 0.15)
    assert len(r[0]) == 0                    # a 0.2% stop is under the 0.5% floor
