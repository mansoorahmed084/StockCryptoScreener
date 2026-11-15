"""Technical Sentiment Composite.

One 0–100 reading of how bullish or bearish the chart's own technicals are,
built by putting a set of well-known tools on a common scale and averaging
them. 50 is neutral; above ``bullish`` the tools agree on up, below
``bearish`` on down.

Two families feed it:

* Momentum oscillators — RSI, Stochastic %K, Stochastic RSI, CCI and Bull
  Bear Power. Each is zone-scaled: its oversold zone becomes 0–25, its lower
  half 25–50, its upper half 50–75 and its overbought zone 75–100.
* Trend tools — a moving average, Bollinger Bands, Supertrend, session VWAP
  bands and market structure. Each gives buy / sell flips, and the score is
  where price sits between the low and the high it has made around the latest
  flip, lightly smoothed. Linear regression is scored from the correlation of
  price with time.

This is an independent implementation of the confluence-scoring idea behind
sentiment meters such as LuxAlgo's "Market Sentiment Technicals", written from
the public description of the method. It is not that script, is not affiliated
with LuxAlgo, and is not expected to match it bar for bar.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .base import Indicator, IndicatorResult, Marker
from . import common

MOMENTUM = ("rsi", "stoch", "stoch_rsi", "cci", "bbp")
TREND = ("ma", "bb", "supertrend", "vwap", "linreg", "structure")
COMPONENTS = MOMENTUM + TREND

RATINGS = ("Strong bearish", "Bearish", "Neutral", "Bullish", "Strong bullish")


def anchored_range_score(close: pd.Series, buy: np.ndarray, sell: np.ndarray,
                         smooth: int = 3) -> pd.Series:
    """0–100 position of price between its running low and high, where a fresh
    buy flip restarts the high at the close and a fresh sell flip restarts the
    low. So a new up-signal reads 100 and decays as price gives ground; a new
    down-signal reads 0 and recovers as price bounces."""
    c = close.to_numpy(dtype=float)
    out = np.full(len(c), np.nan)
    state = 0
    hi = lo = np.nan
    for i, price in enumerate(c):
        if np.isnan(price):
            continue
        prev = state
        if buy[i]:
            state = 1
        elif sell[i]:
            state = -1
        if np.isnan(hi):
            hi = lo = price
        elif state > prev:
            hi, lo = price, min(lo, price)
        elif state < prev:
            lo, hi = price, max(hi, price)
        else:
            hi, lo = max(hi, price), min(lo, price)
        if hi > lo:
            out[i] = (price - lo) / (hi - lo)
        elif state:                      # a flip beyond the old range: top or bottom of it
            out[i] = 1.0 if state > 0 else 0.0
    raw = pd.Series(out, index=close.index)
    return raw.rolling(smooth, min_periods=1).mean() * 100


def band_scale(value: pd.Series, upper: pd.Series, lower: pd.Series) -> pd.Series:
    """Zone-scale a zero-centred oscillator against its own bands: 0 -> 50,
    the upper band -> 75, half as far again -> 100, and the mirror below."""
    v = value.to_numpy(dtype=float)
    up = np.maximum(upper.to_numpy(dtype=float), 1e-12)
    lo = np.minimum(lower.to_numpy(dtype=float), -1e-12)
    pos = 50 + 25 * np.clip(v / up, 0, 1) + 25 * np.clip((v - up) / (0.5 * up), 0, 1)
    neg = 50 - 25 * np.clip(v / lo, 0, 1) - 25 * np.clip((v - lo) / (0.5 * lo), 0, 1)
    out = np.where(v >= 0, pos, neg)
    bad = np.isnan(v) | np.isnan(up) | np.isnan(lo)
    return pd.Series(np.where(bad, np.nan, out), index=value.index)


def structure_breaks(df: pd.DataFrame, length: int) -> tuple[np.ndarray, np.ndarray]:
    """Closes through the last confirmed swing high (buy) / swing low (sell).
    A swing is only used once it is ``length`` bars old, when it is known."""
    high, low, close = (df[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
    is_top = common.pivot_highs(df["high"], length, length).to_numpy()
    is_bot = common.pivot_lows(df["low"], length, length).to_numpy()
    n = len(close)
    buy, sell = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    top = bot = np.nan
    for i in range(n):
        j = i - length
        if j >= 0:
            if is_top[j]:
                top = high[j]
            if is_bot[j]:
                bot = low[j]
        if close[i] > top:            # NaN compares False: no level, no break
            buy[i], top = True, np.nan
        if close[i] < bot:
            sell[i], bot = True, np.nan
    return buy, sell


def rating(value: float, bearish: float = 40, bullish: float = 60,
           strong_bearish: float = 25, strong_bullish: float = 75) -> str:
    if value is None or not math.isfinite(value):
        return ""
    if value >= strong_bullish:
        return RATINGS[4]
    if value >= bullish:
        return RATINGS[3]
    if value > bearish:
        return RATINGS[2]
    if value > strong_bearish:
        return RATINGS[1]
    return RATINGS[0]


class TechnicalSentiment(Indicator):
    name = "technical_sentiment"

    def __init__(self, rsi_len: int = 14, stoch_len: int = 14, stoch_smooth: int = 3,
                 stoch_rsi_len: int = 14, cci_len: int = 20, bbp_len: int = 13,
                 ma_len: int = 20, bb_len: int = 20, bb_mult: float = 2.0,
                 st_len: int = 10, st_mult: float = 3.0, vwap_mult: float = 2.0,
                 linreg_len: int = 25, structure_len: int = 5, norm_smooth: int = 3,
                 pivot_lookback: int = 5, bullish: float = 60.0, bearish: float = 40.0,
                 strong_bullish: float = 75.0, strong_bearish: float = 25.0):
        self.rsi_len = int(rsi_len)
        self.stoch_len = int(stoch_len)
        self.stoch_smooth = int(stoch_smooth)
        self.stoch_rsi_len = int(stoch_rsi_len)
        self.cci_len = int(cci_len)
        self.bbp_len = int(bbp_len)
        self.ma_len = int(ma_len)
        self.bb_len = int(bb_len)
        self.bb_mult = float(bb_mult)
        self.st_len = int(st_len)
        self.st_mult = float(st_mult)
        self.vwap_mult = float(vwap_mult)
        self.linreg_len = int(linreg_len)
        self.structure_len = int(structure_len)
        self.norm_smooth = max(1, int(norm_smooth))
        self.pivot_lookback = int(pivot_lookback)
        self.bullish = float(bullish)
        self.bearish = float(bearish)
        self.strong_bullish = float(strong_bullish)
        self.strong_bearish = float(strong_bearish)
        lengths = (self.rsi_len, self.stoch_len, self.stoch_smooth, self.stoch_rsi_len,
                   self.cci_len, self.bbp_len, self.ma_len, self.bb_len, self.st_len,
                   self.linreg_len, self.structure_len, self.pivot_lookback)
        if min(lengths) < 1:
            raise ValueError("lengths must be 1 or more")

    # ---- the components, each a 0–100 series --------------------------------
    def components(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        close, high, low = df["close"], df["high"], df["low"]
        out: dict[str, pd.Series] = {}
        smooth = self.norm_smooth

        rsi = common.rsi(close, self.rsi_len)
        out["rsi"] = common.zone_scale(rsi, (0, 30, 50, 70, 100))

        k = common.stochastic(close, high, low, self.stoch_len)
        k = k.rolling(self.stoch_smooth).mean()
        out["stoch"] = common.zone_scale(k, (0, 20, 50, 80, 100))

        srsi = common.stochastic(rsi, rsi, rsi, self.stoch_rsi_len)
        srsi = srsi.rolling(self.stoch_smooth).mean()
        out["stoch_rsi"] = common.zone_scale(srsi, (0, 20, 50, 80, 100))

        cci = common.cci(common.hlc3(df), self.cci_len)
        out["cci"] = common.zone_scale(cci, (-300, -100, 0, 100, 300))

        # Bull Bear Power: how far the bar's high and low sit from the average.
        # It has no fixed range, so its own 2-sigma bands stand in for the zones.
        bbp = high + low - 2 * common.ema(close, self.bbp_len)
        basis = bbp.rolling(100, min_periods=20).mean()
        dev = bbp.rolling(100, min_periods=20).std(ddof=0) * 2
        out["bbp"] = band_scale(bbp, basis + dev, basis - dev)

        def flips(buy: pd.Series, sell: pd.Series) -> pd.Series:
            return anchored_range_score(close, buy.fillna(False).to_numpy(dtype=bool),
                                        sell.fillna(False).to_numpy(dtype=bool), smooth)

        ma = close.rolling(self.ma_len).mean()
        out["ma"] = flips(close > ma, close < ma)

        mid = close.rolling(self.bb_len).mean()
        band = common.stdev(close, self.bb_len) * self.bb_mult
        out["bb"] = flips(close > mid + band, close < mid - band)

        st = common.supertrend(df, self.st_len, self.st_mult)
        out["supertrend"] = flips(close > st, close < st)

        if self._vwap_applies(df):
            _, upper, lower = common.session_vwap_bands(df, self.vwap_mult)
            out["vwap"] = flips(close > upper, close < lower)

        out["linreg"] = 50 * common.time_correlation(close, self.linreg_len) + 50

        buy, sell = structure_breaks(df, self.structure_len)
        out["structure"] = anchored_range_score(close, buy, sell, smooth)
        return out

    @staticmethod
    def _vwap_applies(df: pd.DataFrame) -> bool:
        """Session VWAP only means something on intraday candles with volume."""
        if len(df) < 3 or not (df["volume"] > 0).any():
            return False
        step = np.median(np.diff(df.index.asi8)) / 1e9
        return step < 86400

    # -------------------------------------------------------------------------
    def compute(self, df: pd.DataFrame) -> IndicatorResult:
        result = IndicatorResult()
        if df.empty or len(df) < 30:
            return result

        parts = self.components(df)
        table = pd.DataFrame(parts)
        enough = table.notna().all(axis=1)      # no reading until every tool has warmed up
        sentiment = table.mean(axis=1).where(enough)
        momentum = table[[c for c in MOMENTUM if c in table]].mean(axis=1).where(enough)
        trend = table[[c for c in TREND if c in table]].mean(axis=1).where(enough)
        result.panes = {"sentiment": sentiment, "momentum": momentum, "trend": trend,
                        **parts}

        lb = self.pivot_lookback
        bull, bear = common.pivot_divergences(df["low"], df["high"], sentiment, lb, mid=50.0)
        for b in bull:
            result.markers.append(Marker(df.index[b], "bull_div", float(df["low"].iloc[b]),
                                         "bull div"))
        for b in bear:
            result.markers.append(Marker(df.index[b], "bear_div", float(df["high"].iloc[b]),
                                         "bear div"))

        last = len(df) - 1
        now = float(sentiment.iloc[-1]) if np.isfinite(sentiment.iloc[-1]) else float("nan")
        result.signals = {
            "sentiment_bullish": now >= self.bullish,
            "sentiment_bearish": now <= self.bearish,
            "sentiment_strong_bullish": now >= self.strong_bullish,
            "sentiment_strong_bearish": now <= self.strong_bearish,
            # a divergence counts on the bar that confirms its pivot
            "sentiment_bull_div": (last - lb) in bull,
            "sentiment_bear_div": (last - lb) in bear,
        }
        return result

    def rating(self, value: float) -> str:
        return rating(value, self.bearish, self.bullish, self.strong_bearish,
                      self.strong_bullish)
