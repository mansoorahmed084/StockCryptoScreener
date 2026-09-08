"""Daily VMC divergence + structure break — the phase-7 result, for freqtrade.

From research/ETH_RESEARCH_LOG.md phase 7. The one family in this project that
is positive on held-out coins at every parameter setting tested, with the
structure break improving every one of them.

Entry (daily closes, long only):
  * VMC bullish divergence, pivot confirmed 3 closes later
  * WT2 <= WT2_MAX at the divergence pivot
  * price then CLOSES above a falling line fitted through the highs since that
    pivot, within WAIT_BARS days -- the structure break the trader's charts
    showed. The setup is void if price loses the pivot low first.
  * stop under the lowest low of the setup, minus 1 x ATR(14)

Exit: fixed 3R, or a 60-day time stop.

Long only: the short mirror measured at -0.003R against +0.220R for longs in
phase 2 and was never rescued.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, stoploss_from_absolute

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.indicators.vumanchu import VuManChuCipherB   # noqa: E402


class DailyDivBreakout(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    can_short = False

    WT2_MAX = -30.0
    PIVOT_LOOKBACK = 3
    WAIT_BARS = 8
    ATR_STOP_MULT = 1.0
    MAX_RISK_PCT = 0.15
    TARGET_R = 3.0
    TIME_STOP_BARS = 60
    RISK_PER_TRADE = 0.01

    minimal_roi = {"0": 100}
    stoploss = -0.99
    use_custom_stoploss = True
    trailing_stop = False
    use_exit_signal = True          # gates custom_exit; see reference memory
    process_only_new_candles = True
    startup_candle_count = 200

    # ------------------------------------------------------------ indicators
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe.set_index("date")
        res = VuManChuCipherB(pivot_lookback=self.PIVOT_LOOKBACK).compute(df)
        wt2 = res.panes.get("wt2")

        n = len(df)
        signal = np.zeros(n, dtype=bool)
        stop = np.full(n, np.nan)

        if wt2 is not None:
            atr = self._atr(df, 14)
            highs = df["high"].to_numpy()
            lows = df["low"].to_numpy()
            closes = df["close"].to_numpy()

            for marker in res.markers:
                if marker.kind != "bull_div":
                    continue
                p = df.index.get_loc(marker.ts)
                c = p + self.PIVOT_LOOKBACK          # divergence confirmed
                if c >= n - 1 or float(wt2.iloc[p]) > self.WT2_MAX:
                    continue
                pivot_low = float(lows[p])
                end = min(n, c + self.WAIT_BARS + 1)

                trig = None
                for i in range(c + 1, end):
                    if lows[i] < pivot_low:          # setup void
                        break
                    window = highs[c:i]              # strictly before bar i
                    if window.size < 3:
                        continue
                    xs = np.arange(window.size, dtype=float)
                    slope, intercept = np.polyfit(xs, window, 1)
                    level = (float(window.max()) if slope > 0
                             else float(intercept + slope * window.size))
                    if closes[i] > level:
                        trig = i
                        break

                if trig is None or not np.isfinite(atr[trig]):
                    continue
                low_ref = min(pivot_low, float(lows[c:trig + 1].min()))
                stop_price = low_ref - self.ATR_STOP_MULT * atr[trig]
                ref = float(closes[trig])
                if stop_price <= 0 or ref <= 0:
                    continue
                if (ref - stop_price) / ref > self.MAX_RISK_PCT:
                    continue
                signal[trig] = True
                stop[trig] = stop_price

        dataframe["div_stop"] = stop
        dataframe["div_signal"] = signal.astype(int)
        return dataframe

    @staticmethod
    def _atr(df: DataFrame, length: int = 14) -> np.ndarray:
        prev_c = df["close"].shift(1)
        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - prev_c).abs(),
                        (df["low"] - prev_c).abs()], axis=1).max(axis=1)
        return tr.rolling(length, min_periods=length).mean().to_numpy()

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["div_signal"] == 1,
                      ["enter_long", "enter_tag"]] = (1, "div_breakout")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    # -------------------------------------------------------------- per-trade
    def _stop_and_risk(self, pair: str, trade: Trade) -> tuple[float, float] | None:
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty:
            return None
        prior = df.loc[df["date"] < trade.open_date_utc]
        if prior.empty:
            return None
        stop = prior["div_stop"].iloc[-1]
        if not np.isfinite(stop):
            return None
        risk = trade.open_rate - float(stop)
        return (float(stop), risk) if risk > 0 else None

    def custom_stake_amount(self, pair: str, current_time: datetime,
                            current_rate: float, proposed_stake: float,
                            min_stake: float | None, max_stake: float,
                            leverage: float, entry_tag: str | None,
                            side: str, **kwargs) -> float:
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty:
            return proposed_stake
        stop = df["div_stop"].iloc[-1]
        if not np.isfinite(stop) or current_rate <= 0:
            return proposed_stake
        stop_pct = (current_rate - float(stop)) / current_rate
        if stop_pct <= 0:
            return proposed_stake
        equity = self.wallets.get_total_stake_amount() if self.wallets else proposed_stake
        stake = min((equity * self.RISK_PER_TRADE) / stop_pct, max_stake)
        return max(stake, min_stake) if min_stake is not None else stake

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float,
                        after_fill: bool, **kwargs) -> float | None:
        sr = self._stop_and_risk(pair, trade)
        if sr is None:
            return None
        return stoploss_from_absolute(sr[0], current_rate, is_short=False,
                                      leverage=trade.leverage)

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        sr = self._stop_and_risk(pair, trade)
        if sr is not None and current_rate >= trade.open_rate + self.TARGET_R * sr[1]:
            return "target_3R"
        if (current_time - trade.open_date_utc).days >= self.TIME_STOP_BARS:
            return "time_stop"
        return None


class DailyDivBreakout50(DailyDivBreakout):
    """Deeper-oversold variant: fewer trades, higher per-trade edge."""

    WT2_MAX = -50.0
