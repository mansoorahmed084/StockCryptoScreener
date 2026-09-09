"""TrendlineBreakout with the stop placed from 1h structure, not daily.

Same daily breakouts as `TrendlineBreakout`. Two things change, and a 600-cell
grid picked both (research/results/rf_grid_report.md):

1. **The stop comes from 1h structure.** The daily stop sits under a 20-day low
   minus 1.5 ATR, roughly 21% away. The 1h stop sits under the last 24 hours of
   1h lows minus 1 ATR(1h), roughly 6% away. Everything is measured in R and R
   is the size of that stop, so the same price move is worth three times more.

   The 24-hour window is exactly the signal day, so the swing low IS the daily
   bar's low. Only ATR(1h) needs the 1h feed.

2. **The exit is a 25% trailing stop, not 3R.** This is the part that makes the
   first part work. An R-based trail SCALES with the entry stop: tighten the
   stop and the trail tightens with it, and the tighter stop buys nothing. A
   percent trail is scale-free -- give back no more than 25% of the high,
   whatever the stop was -- so a tight entry stop can be paired with an exit
   wide enough to let a 100% move run.

What did NOT work, and is therefore not here: waiting for a lower-timeframe
entry trigger. A 1h break of the daily bar's high, a retest of the broken line,
and an EMA pullback were all tested across the grid and all scored WORSE than
simply taking the next daily open. These breaks tend to go immediately; waiting
misses the ones that matter.

**Position size is risk divided by stop distance, so a 1% risk behind a 6% stop
is a 17% position.** Ten of those is 167% of the account. Set max_open_trades so
that cannot happen, or accept that some entries will be refused for want of
capital -- the research measured a peak exposure of 178% uncapped.

Backtest with --timeframe-detail 15m. Fills were checked at 1h, 15m and 5m and
agree, so 15m is enough.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import stoploss_from_absolute

from TrendlineBreakout import TrendlineBreakout


class TrendlineBreakoutLTF(TrendlineBreakout):
    INTERFACE_VERSION = 3

    INFORMATIVE_TF = "1h"
    LTF_ATR_LEN = 14
    LTF_ATR_MULT = 1.0
    MIN_RISK_PCT = 0.02         # a stop inside the noise is not a stop
    MAX_RISK_PCT = 0.25

    TRAIL_PCT = 0.25            # give back no more than this much of the high
    TRAIL_R = None              # the percent trail replaces the R trail

    def informative_pairs(self):
        pairs = self.dp.current_whitelist() if self.dp else []
        return [(p, self.INFORMATIVE_TF) for p in pairs]

    # ------------------------------------------------------------ indicators
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_indicators(dataframe, metadata)

        atr1h = self._informative_atr(metadata["pair"], df)
        # The 24h swing low the research used IS this daily bar's low, because
        # the window is exactly the signal day. So only ATR(1h) is borrowed.
        stop = df["low"].to_numpy(dtype=float) - self.LTF_ATR_MULT * atr1h
        close = df["close"].to_numpy(dtype=float)

        sig = df["tl_signal"].to_numpy().astype(bool)
        with np.errstate(invalid="ignore", divide="ignore"):
            risk = (close - stop) / close
        ok = (sig & np.isfinite(stop) & (stop > 0)
              & (risk >= self.MIN_RISK_PCT) & (risk <= self.MAX_RISK_PCT))

        df["tl_stop"] = np.where(ok, stop, np.nan)
        df["tl_signal"] = ok.astype(int)
        return df

    def _informative_atr(self, pair: str, daily: DataFrame) -> np.ndarray:
        """ATR(1h) sampled at the hour each daily candle closes.

        A daily candle stamped D closes at D+1 00:00, so the last 1h candle
        inside it is the one stamped D+1 00:00 minus one hour. Taking the ATR
        there uses only bars that had closed when the daily signal printed.
        """
        n = len(daily)
        if self.dp is None:
            return np.full(n, np.nan)
        inf = self.dp.get_pair_dataframe(pair, self.INFORMATIVE_TF)
        if inf is None or inf.empty:
            return np.full(n, np.nan)

        a = pd.Series(self._atr(inf, self.LTF_ATR_LEN), index=inf["date"])
        want = daily["date"] + pd.Timedelta(days=1) - pd.Timedelta(hours=1)
        return a.reindex(want).to_numpy()

    # -------------------------------------------------------------- per-trade
    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float,
                        after_fill: bool, **kwargs) -> float | None:
        sr = self._stop_and_risk(pair, trade)
        if sr is None:
            return None
        stop = sr[0]
        # Trail a fixed percentage below the highest price the trade has seen,
        # never below the entry stop. max() ratchets: the peak only rises, so
        # the trail only rises with it.
        peak = float(trade.max_rate or trade.open_rate)
        stop = max(stop, peak * (1.0 - self.TRAIL_PCT))
        return stoploss_from_absolute(stop, current_rate, is_short=False,
                                      leverage=trade.leverage)
