"""Candles in and out: TradingView "Export chart data" CSVs, and a synthetic market for self-tests."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.indicators.sentiment import vwap_anchor_ids


@dataclass
class Candles:
    """OHLCV arrays ready for the compiled kernel."""
    index: pd.DatetimeIndex
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    anchor: np.ndarray       # VWAP session number per bar (day, week, month... by timeframe)
    use_vwap: bool           # the candles have volume (same rule as the pandas indicator)

    @property
    def n(self) -> int:
        return len(self.c)

    def frame(self) -> pd.DataFrame:
        """The canonical frame the pandas indicators take."""
        return pd.DataFrame({"open": self.o, "high": self.h, "low": self.l, "close": self.c,
                             "volume": self.v}, index=self.index)

    def args(self):
        return (self.h, self.l, self.c, self.v, self.anchor, self.use_vwap)


def candles_from_frame(df: pd.DataFrame) -> Candles:
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    df = df.copy()
    df.index = idx
    vol = df["volume"].to_numpy(dtype=np.float64) if "volume" in df else np.zeros(len(df))
    use_vwap = bool(len(df) >= 3 and (vol > 0).any())
    return Candles(
        index=idx,
        o=df["open"].to_numpy(dtype=np.float64),
        h=df["high"].to_numpy(dtype=np.float64),
        l=df["low"].to_numpy(dtype=np.float64),
        c=df["close"].to_numpy(dtype=np.float64),
        v=vol,
        anchor=vwap_anchor_ids(idx),
        use_vwap=use_vwap,
    )


def _parse_time(col: pd.Series) -> pd.DatetimeIndex:
    """TradingView writes Unix seconds or an ISO timestamp, depending on the export setting."""
    if pd.api.types.is_numeric_dtype(col):
        unit = "s" if float(col.iloc[0]) < 1e11 else "ms"
        return pd.DatetimeIndex(pd.to_datetime(col, unit=unit, utc=True))
    return pd.DatetimeIndex(pd.to_datetime(col, utc=True))


def load_tv_csv(path: str) -> tuple[Candles, pd.DataFrame]:
    """Read a TradingView export: candles plus every other column (the plotted series).

    Returns the candles and a frame of the extra columns on the same index.
    """
    raw = pd.read_csv(path)
    raw.columns = [str(c).strip() for c in raw.columns]
    lower = {c.lower(): c for c in raw.columns}
    for need in ("time", "open", "high", "low", "close"):
        if need not in lower:
            raise ValueError(f"{path}: no '{need}' column (found {list(raw.columns)})")
    idx = _parse_time(raw[lower["time"]])
    base = {lower[k] for k in ("time", "open", "high", "low", "close")}
    vol_col = lower.get("volume")
    if vol_col:
        base.add(vol_col)
    frame = pd.DataFrame({
        "open": raw[lower["open"]], "high": raw[lower["high"]], "low": raw[lower["low"]],
        "close": raw[lower["close"]],
        "volume": raw[vol_col] if vol_col else 0.0,
    })
    frame.index = idx
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    extras = raw.drop(columns=[c for c in raw.columns if c in base])
    extras.index = idx
    extras = extras[~extras.index.duplicated(keep="last")].sort_index()
    extras = extras.apply(pd.to_numeric, errors="coerce")
    return candles_from_frame(frame), extras


def synthetic_candles(n: int = 6000, step_minutes: int = 15, seed: int = 0,
                      start: str = "2024-01-01") -> Candles:
    """A regime-switching random walk with volatility clustering, volume and wicks.

    Not a model of any market; it only needs trends, reversals and ranges so every component of
    the indicator moves through all of its states.
    """
    rng = np.random.default_rng(seed)
    drift = np.zeros(n)
    vol = np.zeros(n)
    regime_drift, regime_vol = 0.0, 0.002
    for i in range(n):
        if i % 150 == 0:
            regime_drift = rng.normal(0, 0.0006)
            regime_vol = float(np.exp(rng.normal(np.log(0.002), 0.4)))
        drift[i], vol[i] = regime_drift, regime_vol
    ret = drift + vol * rng.standard_normal(n)
    close = 100.0 * np.exp(np.cumsum(ret))
    open_ = np.concatenate(([100.0], close[:-1]))
    wick = np.abs(rng.standard_normal((n, 2))) * vol[:, None] * close[:, None] * 0.6
    high = np.maximum(open_, close) + wick[:, 0]
    low = np.minimum(open_, close) - wick[:, 1]
    volume = np.exp(rng.normal(7.0, 0.5, n)) * (1 + 20 * np.abs(ret) / vol.mean())
    idx = pd.date_range(start, periods=n, freq=f"{step_minutes}min", tz="UTC")
    return candles_from_frame(pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx))
