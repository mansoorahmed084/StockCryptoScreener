import pandas as pd

from backend.config import ClassifierParams
from backend.screener import rs
from backend.signals.backtest import backtest_signal
from .util import trend

PARAMS = ClassifierParams(ema_len=21, vol_lookback=60, neutral_band=1.0,
                          hysteresis_out=0.6, persistence=2)


def test_classify_history_shape():
    close = pd.Series(trend(150, 100, 0.01, noise=0.001, seed=1))
    hist = rs.classify_history(close, PARAMS)
    assert list(hist.columns) == ["strength", "direction"]
    assert len(hist) == len(close) - 1  # forming candle dropped


def test_backtest_uptrend_bull_profitable():
    close = pd.Series(trend(300, 100, 0.01, noise=0.002, seed=2))
    stats = backtest_signal(close, PARAMS, direction=rs.BULL, horizon=10)
    assert stats.n > 0
    assert stats.mean_fwd > 0        # bull signals precede up moves
    assert stats.hit_rate > 0.5


def test_backtest_no_entries_returns_zero():
    close = pd.Series([100.0] * 150)  # flat -> never bull
    stats = backtest_signal(close, PARAMS, direction=rs.BULL, horizon=10)
    assert stats.n == 0
