"""VuManChu Cipher B + Divergences.

Re-implemented from the public Pine script spec: WaveTrend (WT1/WT2) with buy/sell
crosses in the overbought/oversold zones, the RSI+MFI money-flow area, and regular
bullish/bearish divergences between WT2 pivots and price.

Not a bit-exact port of every cosmetic dot, but reproduces the load-bearing
signals (cross buys/sells, regular divergences) that the screener acts on.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Indicator, IndicatorResult, Marker
from . import common, wavetrend


class VuManChuCipherB(Indicator):
    name = "vumanchu_cipher_b"

    def __init__(self, channel_len: int = 9, average_len: int = 12, ma_len: int = 3,
                 overbought: float = 53.0, oversold: float = -53.0,
                 mfi_period: int = 60, mfi_mult: float = 150.0,
                 pivot_lookback: int = 3):
        self.channel_len = channel_len
        self.average_len = average_len
        self.ma_len = ma_len
        self.overbought = overbought
        self.oversold = oversold
        self.mfi_period = mfi_period
        self.mfi_mult = mfi_mult
        self.pivot_lookback = pivot_lookback

    def compute(self, df: pd.DataFrame) -> IndicatorResult:
        result = IndicatorResult()
        if df.empty or len(df) < self.average_len + 5:
            return result

        wt1, wt2 = wavetrend.wavetrend(df, self.channel_len, self.average_len,
                                       self.ma_len)
        mfi = common.vumanchu_moneyflow(df, self.mfi_period, self.mfi_mult)
        result.panes = {"wt1": wt1, "wt2": wt2, "mfi": mfi}

        cross_up = (wt1.shift(1) <= wt2.shift(1)) & (wt1 > wt2)
        cross_dn = (wt1.shift(1) >= wt2.shift(1)) & (wt1 < wt2)
        buy = cross_up & (wt2 <= self.oversold)
        sell = cross_dn & (wt2 >= self.overbought)

        markers: list[Marker] = []
        for ts in df.index[buy.fillna(False)]:
            markers.append(Marker(ts, "buy", float(df.loc[ts, "low"]), "WT buy"))
        for ts in df.index[sell.fillna(False)]:
            markers.append(Marker(ts, "sell", float(df.loc[ts, "high"]), "WT sell"))

        bull, bear = self._divergences(df["close"], wt2)
        markers += bull + bear

        last = -1
        result.markers = markers
        result.signals = {
            "vumanchu_buy": bool(buy.iloc[last]) if len(buy) else False,
            "vumanchu_sell": bool(sell.iloc[last]) if len(sell) else False,
            "vumanchu_bull_div": any(m.kind == "bull_div" and m.ts == df.index[last]
                                     for m in bull),
            "vumanchu_bear_div": any(m.kind == "bear_div" and m.ts == df.index[last]
                                     for m in bear),
        }
        return result

    def _divergences(self, price: pd.Series, osc: pd.Series):
        """Regular divergences between consecutive WT2 pivots and price."""
        lb = self.pivot_lookback
        lows = common.pivot_lows(osc, lb, lb)
        highs = common.pivot_highs(osc, lb, lb)
        bull: list[Marker] = []
        bear: list[Marker] = []

        low_idx = list(np.where(lows.to_numpy())[0])
        for a, b in zip(low_idx, low_idx[1:]):
            # regular bullish: price lower low, oscillator higher low, in oversold
            if (price.iloc[b] < price.iloc[a] and osc.iloc[b] > osc.iloc[a]
                    and osc.iloc[b] < 0):
                ts = price.index[b]
                bull.append(Marker(ts, "bull_div", float(price.iloc[b]), "bull div"))

        high_idx = list(np.where(highs.to_numpy())[0])
        for a, b in zip(high_idx, high_idx[1:]):
            # regular bearish: price higher high, oscillator lower high, in overbought
            if (price.iloc[b] > price.iloc[a] and osc.iloc[b] < osc.iloc[a]
                    and osc.iloc[b] > 0):
                ts = price.index[b]
                bear.append(Marker(ts, "bear_div", float(price.iloc[b]), "bear div"))
        return bull, bear
