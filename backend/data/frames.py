"""OHLCV DataFrame contract and shared helpers.

Canonical candle frame:
    * index  : tz-aware UTC ``DatetimeIndex`` named ``ts``, ascending, unique
    * columns: ``open, high, low, close, volume`` (float64)

All adapters normalise their raw payloads to this shape so the rest of the code
(ratio builder, RS engine, indicators) never has to know which exchange the data
came from.
"""
from __future__ import annotations

from typing import Iterable, Mapping

import pandas as pd

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

# pandas resample rule for each timeframe (offset alias).
_RESAMPLE_RULE = {
    "1m": "1min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "8h": "8h",
    "1d": "1D",
    "3d": "3D",
    # W-MON + closed/label "left" = weeks spanning Mon 00:00 UTC .. Sun, labeled by
    # their Monday — matching exchange/TradingView weekly candles. Plain "1W" is
    # W-SUN and shifts every weekly candle by a day.
    "1w": "W-MON",
}

_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def empty_ohlcv() -> pd.DataFrame:
    idx = pd.DatetimeIndex([], tz="UTC", name="ts")
    return pd.DataFrame(columns=OHLCV_COLUMNS, index=idx, dtype="float64")


def from_records(records: Iterable[Mapping], *, time_key: str = "time",
                 time_unit: str = "ms") -> pd.DataFrame:
    """Build a canonical OHLCV frame from a list of dict candles.

    Accepts the CoinDCX candle shape ``{open, high, low, close, volume, time}``.
    Robust to newest-first ordering and duplicate timestamps.
    """
    rows = list(records)
    if not rows:
        return empty_ohlcv()
    df = pd.DataFrame(rows)
    if time_key not in df.columns:
        raise ValueError(f"records missing time key {time_key!r}")
    ts = pd.to_datetime(df[time_key], unit=time_unit, utc=True)
    df = df.assign(ts=ts).set_index("ts")
    for col in OHLCV_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[OHLCV_COLUMNS].astype("float64")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.index.name = "ts"
    return df


def resample_ohlcv(df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    """Resample a finer OHLCV frame up to ``target_tf`` (e.g. 1m -> 3m).

    Only aggregates buckets that have at least one source candle.
    """
    if target_tf not in _RESAMPLE_RULE:
        raise ValueError(f"Cannot resample to unknown timeframe {target_tf!r}")
    if df.empty:
        return empty_ohlcv()
    rule = _RESAMPLE_RULE[target_tf]
    out = df.resample(rule, label="left", closed="left").agg(_AGG)
    out = out.dropna(subset=["open", "close"], how="any")
    out.index.name = "ts"
    return out
