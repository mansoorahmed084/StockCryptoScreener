"""Data quality & integrity checks.

Synthesised ratios (e.g. SOL/BTC = SOL/USDT ÷ BTC/USDT) are only trustworthy if
both legs are fresh, gap-free and aligned to the same candle boundaries. These
helpers let the ratio builder and RS engine mark a cell ``unknown`` instead of
emitting a misleading signal.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.config import timeframe_to_seconds


@dataclass(frozen=True)
class QualityReport:
    ok: bool
    reason: str = ""
    rows: int = 0
    gaps: int = 0
    stale: bool = False


def last_timestamp(df: pd.DataFrame) -> pd.Timestamp | None:
    if df.empty:
        return None
    return df.index[-1]


def is_stale(df: pd.DataFrame, timeframe: str, *, now: pd.Timestamp | None = None,
             multiplier: float = 3.0) -> bool:
    """True if the newest candle is older than ``multiplier`` timeframes."""
    last = last_timestamp(df)
    if last is None:
        return True
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    max_age = timeframe_to_seconds(timeframe) * multiplier
    return (now - last).total_seconds() > max_age


def count_gaps(df: pd.DataFrame, timeframe: str) -> int:
    """Number of missing candles between first and last timestamp."""
    if len(df) < 2:
        return 0
    step = pd.Timedelta(seconds=timeframe_to_seconds(timeframe))
    deltas = df.index.to_series().diff().dropna()
    # a delta of N*step means (N-1) missing candles
    missing = ((deltas / step).round() - 1).clip(lower=0)
    return int(missing.sum())


def assess(df: pd.DataFrame, timeframe: str, *, min_rows: int = 30,
           now: pd.Timestamp | None = None, stale_multiplier: float = 3.0) -> QualityReport:
    """Summarise whether a frame is usable for classification."""
    if df.empty:
        return QualityReport(ok=False, reason="empty", rows=0)
    rows = len(df)
    if rows < min_rows:
        return QualityReport(ok=False, reason=f"too_few_rows({rows}<{min_rows})",
                             rows=rows)
    if df["close"].isna().all():
        return QualityReport(ok=False, reason="all_nan_close", rows=rows)
    stale = is_stale(df, timeframe, now=now, multiplier=stale_multiplier)
    if stale:
        return QualityReport(ok=False, reason="stale", rows=rows, stale=True)
    gaps = count_gaps(df, timeframe)
    return QualityReport(ok=True, rows=rows, gaps=gaps, stale=False)


def align(a: pd.DataFrame, b: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Inner-join two OHLCV frames on their timestamps (strict alignment)."""
    common = a.index.intersection(b.index)
    return a.loc[common], b.loc[common]
