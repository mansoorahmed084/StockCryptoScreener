import pandas as pd

from backend.data import quality
from .util import make_ohlcv


def test_count_gaps_detects_missing_candle():
    df = make_ohlcv([1, 2, 3, 4, 5], timeframe="1h")
    df2 = df.drop(df.index[2])  # remove one candle -> one gap
    assert quality.count_gaps(df2, "1h") == 1


def test_no_gaps_on_contiguous():
    df = make_ohlcv([1, 2, 3, 4, 5], timeframe="1h")
    assert quality.count_gaps(df, "1h") == 0


def test_is_stale_true_for_old_data():
    df = make_ohlcv([1, 2, 3], timeframe="1h", start="2020-01-01")
    assert quality.is_stale(df, "1h") is True


def test_assess_flags_short_and_empty():
    assert quality.assess(make_ohlcv([1, 2], timeframe="1h"), "1h").ok is False
    from backend.data.frames import empty_ohlcv
    rep = quality.assess(empty_ohlcv(), "1h")
    assert rep.ok is False and rep.reason == "empty"


def test_align_intersects_timestamps():
    a = make_ohlcv([1, 2, 3, 4], timeframe="1h")
    b = make_ohlcv([1, 2, 3], timeframe="1h")
    a2, b2 = quality.align(a, b)
    assert len(a2) == len(b2) == 3
    assert a2.index.equals(b2.index)
