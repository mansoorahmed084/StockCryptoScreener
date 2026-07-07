import pandas as pd

from backend.config import ClassifierParams
from backend.screener import rs
from .util import trend


PARAMS = ClassifierParams(ema_len=21, vol_lookback=60, neutral_band=1.0,
                          hysteresis_out=0.6, persistence=2)


def _close(vals):
    return pd.Series(vals)


def test_uptrend_classified_bull():
    close = _close(trend(150, 100, 0.01, noise=0.001, seed=1))
    res = rs.classify(close, PARAMS)
    assert res.direction == rs.BULL
    assert res.strength > 0


def test_downtrend_classified_bear():
    close = _close(trend(150, 100, -0.01, noise=0.001, seed=2))
    res = rs.classify(close, PARAMS)
    assert res.direction == rs.BEAR
    assert res.strength < 0


def test_flat_series_neutral():
    close = _close([100.0] * 150)
    res = rs.classify(close, PARAMS)
    assert res.direction == rs.NEUTRAL


def test_insufficient_data_unknown():
    close = _close(trend(10, 100, 0.01, seed=3))
    res = rs.classify(close, PARAMS)
    assert res.direction == rs.UNKNOWN
    assert res.n == 9  # 10 minus the dropped forming candle


def test_drop_forming_excludes_last_candle():
    close = _close(trend(100, 100, 0.005, seed=4))
    kept = rs.classify(close, PARAMS, drop_forming=True)
    full = rs.classify(close, PARAMS, drop_forming=False)
    assert kept.n == full.n - 1


def test_change_pct_sign_matches_last_move():
    close = _close(trend(120, 100, 0.02, noise=0.0, seed=5))
    res = rs.classify(close, PARAMS)
    assert res.change_pct > 0
