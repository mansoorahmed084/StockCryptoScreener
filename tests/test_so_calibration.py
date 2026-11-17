"""Backtester, scorers and trailing-stop rules used to compare Signals & Overlays (calibration/so_*.py)."""
from types import SimpleNamespace

import numpy as np
import pytest

from calibration.so_backtest import backtest
from calibration import so_variants as V


def _series():
    #            bar: 0    1    2    3    4    5    6
    o = np.array([100, 100, 150, 200, 200, 100, 100.0])
    c = np.array([100, 120, 190, 200, 150, 100, 100.0])
    return o, c


def test_signals_are_acted_on_at_the_next_open():
    o, c = _series()
    sig = np.zeros(7)
    sig[0] = 1            # green on bar 0 -> long at bar 1's open (100)
    sig[3] = -1           # red on bar 3   -> reverse at bar 4's open (200)
    r = backtest(o, c, sig, 0, 6, fee=0.0)
    t = r.trades
    assert list(t["entry_bar"]) == [1, 4] and list(t["side"]) == [1, -1]
    assert list(t["entry"]) == [100.0, 200.0] and t["exit"].iloc[0] == 200.0
    assert t["ret"].iloc[0] == pytest.approx(1.0)                       # long 100 -> 200
    assert t["ret"].iloc[1] == pytest.approx(0.5)                       # short 200 -> last close 100
    assert r.equity[-1] == pytest.approx(3.0)


def test_a_fee_is_paid_on_entry_and_exit():
    o = np.full(5, 100.0)
    c = np.full(5, 100.0)
    sig = np.array([1, 0, -2, 0, 0.0])
    r = backtest(o, c, sig, 0, 4, long_only=True, fee=0.001)
    assert len(r.trades) == 1
    assert r.trades["ret"].iloc[0] == pytest.approx((1 - 0.001) ** 2 - 1)


def test_long_only_closes_on_red_without_shorting():
    o, c = _series()
    sig = np.zeros(7)
    sig[0], sig[3] = 1, -1
    r = backtest(o, c, sig, 0, 6, long_only=True, fee=0.0)
    assert list(r.trades["side"]) == [1] and r.equity[-1] == pytest.approx(2.0)   # flat after the exit


def test_strong_only_ignores_normal_signals():
    o, c = _series()
    sig = np.zeros(7)
    sig[0] = 1            # normal: ignored
    sig[3] = -2           # strong sell with nothing open: a short from bar 4 to the end
    r = backtest(o, c, sig, 0, 6, strong_only=True, fee=0.0)
    assert list(r.trades["side"]) == [-1] and r.trades["entry_bar"].iloc[0] == 4


def test_drawdown_counts_the_open_trade():
    o = np.array([100, 100, 100, 100.0])
    c = np.array([100, 100, 60, 100.0])
    sig = np.array([1, 0, 0, 0.0])
    r = backtest(o, c, sig, 0, 3, long_only=True, fee=0.0)
    assert r.stats["max_drawdown"] == pytest.approx(-0.4)               # it fell to 60 and recovered


def test_hl_trailing_stop_ratchets_then_flips_on_a_close():
    n = 40
    base = np.concatenate([np.linspace(100, 160, 25), np.linspace(160, 90, 15)])
    h, l, c = base + 1, base - 1, base
    tr, d = V.trail_hl(h, l, c, np.full(n, 8.0))
    assert d[20] == 1 and tr[20] < c[20]                                # uptrend: the stop sits under price
    ups = tr[:25][d[:25] == 1]
    assert np.all(np.diff(ups) >= -1e-9)                                # and only ever moves up
    assert d[-1] == -1 and tr[-1] > c[-1]                               # a close through it flips it over


def test_score_signals_matches_side_within_a_bar():
    from calibration.so_compare import score_signals
    ref = SimpleNamespace(signals={10: (1, "strong"), 20: (-1, "normal"), 30: (1, "normal")},
                          covered=np.ones(50, bool))
    sig = np.zeros(50)
    sig[11] = 2           # green strong, one bar late: matches
    sig[20] = 1           # green where the reference is red: no match
    sig[40] = -1          # extra
    s = score_signals(ref, sig, tol=1)
    assert s["matched"] == 1 and s["ref"] == 3 and s["ours"] == 3
    assert s["recall"] == pytest.approx(1 / 3) and s["strong"] == 1.0
