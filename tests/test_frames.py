import pandas as pd

from backend.data.frames import from_records, resample_ohlcv
from .util import make_ohlcv


def test_from_records_normalises_and_sorts():
    records = [
        {"time": 2000, "open": 2, "high": 3, "low": 1, "close": 2.5, "volume": 10},
        {"time": 1000, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 5},
    ]
    df = from_records(records)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.is_monotonic_increasing
    assert df["close"].iloc[0] == 1.5  # oldest first after sort
    assert str(df.index.tz) == "UTC"


def test_from_records_dedups():
    records = [
        {"time": 1000, "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 5},
        {"time": 1000, "open": 1, "high": 2, "low": 1, "close": 9.0, "volume": 5},
    ]
    df = from_records(records)
    assert len(df) == 1
    assert df["close"].iloc[0] == 9.0  # keep last


def test_resample_1m_to_3m():
    closes = list(range(1, 13))  # 12 one-minute candles
    df = make_ohlcv(closes, timeframe="1m", start="2024-01-01")  # 3m-aligned
    out = resample_ohlcv(df, "3m")
    assert len(out) == 4
    # first 3m bucket aggregates candles 1,2,3
    assert out["open"].iloc[0] == df["open"].iloc[0]
    assert out["close"].iloc[0] == df["close"].iloc[2]
    assert out["high"].iloc[0] == df["high"].iloc[:3].max()
    assert out["volume"].iloc[0] == df["volume"].iloc[:3].sum()
