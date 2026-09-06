"""ETH 4h VMC capitulation with a G3 scale-out — freqtrade confirmation build.

This is the batch-2 winner from research/ETH_RESEARCH_LOG.md re-expressed for
freqtrade, so the fast harness result can be checked against an independent
engine before anyone believes it.

Entry (ETH/USDT, 4h closes):
  * VMC regular bullish divergence, pivot confirmed 3 bars later
  * WT2 <= WT2_EXTREME at the divergence pivot
  * stop = pivot low - ATR_STOP_MULT * ATR(14); skip if further than MAX_RISK_PCT
  * no regime gate — batch 2 showed every gate starves a single-coin universe

Exit (the "G3" shape from SHORT_TERM_STRATEGY.md Iteration F):
  * book half the position at +1R
  * move the stop on the remainder to breakeven
  * exit the remainder at +3R, the breakeven stop, or a 120-bar time stop

The 1:3 reward tail is preserved by the runner; the win rate comes from the
first leg. Both are reported separately in the research log.
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

from backend.indicators.vumanchu import VuManChuCipherB     # noqa: E402


class EthVmcScaleOut(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "4h"
    can_short = False

    # --- dials, from the batch-2 plateau (not the single best cell) ----------
    WT2_EXTREME = -45.0
    ATR_STOP_MULT = 1.5
    PIVOT_LOOKBACK = 3
    MAX_RISK_PCT = 0.10
    FIRST_LEG_R = 1.0
    FIRST_LEG_FRACTION = 0.5
    RUNNER_R = 3.0
    TIME_STOP_BARS = 120
    RISK_PER_TRADE = 0.01

    minimal_roi = {"0": 100}
    stoploss = -0.99
    use_custom_stoploss = True
    trailing_stop = False
    use_exit_signal = True          # gates custom_exit; see reference memory
    position_adjustment_enable = True

    process_only_new_candles = True
    startup_candle_count = 300

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
            for marker in res.markers:
                if marker.kind != "bull_div":
                    continue
                p = df.index.get_loc(marker.ts)
                p_conf = p + self.PIVOT_LOOKBACK
                if p_conf >= n or float(wt2.iloc[p]) > self.WT2_EXTREME:
                    continue
                a = atr[p_conf]
                if not np.isfinite(a):
                    continue
                stop_price = float(df["low"].iloc[p]) - self.ATR_STOP_MULT * a
                ref = float(df["close"].iloc[p_conf])
                if stop_price <= 0 or ref <= 0:
                    continue
                if (ref - stop_price) / ref > self.MAX_RISK_PCT:
                    continue
                signal[p_conf] = True
                stop[p_conf] = stop_price

        dataframe["vmc_stop"] = stop
        dataframe["vmc_signal"] = signal.astype(int)
        return dataframe

    @staticmethod
    def _atr(df: DataFrame, length: int = 14) -> np.ndarray:
        prev_c = df["close"].shift(1)
        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - prev_c).abs(),
                        (df["low"] - prev_c).abs()], axis=1).max(axis=1)
        return tr.rolling(length, min_periods=length).mean().to_numpy()

    # ---------------------------------------------------------------- trends
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["vmc_signal"] == 1,
                      ["enter_long", "enter_tag"]] = (1, "vmc_cap_4h")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    # -------------------------------------------------------------- per-trade
    def _stop_and_risk(self, pair: str, trade: Trade) -> tuple[float, float] | None:
        """The stop recorded on the signal candle, plus the 1R distance."""
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty:
            return None
        prior = df.loc[df["date"] < trade.open_date_utc]
        if prior.empty:
            return None
        stop = prior["vmc_stop"].iloc[-1]
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
        stop = df["vmc_stop"].iloc[-1]
        if not np.isfinite(stop) or current_rate <= 0:
            return proposed_stake
        stop_pct = (current_rate - float(stop)) / current_rate
        if stop_pct <= 0:
            return proposed_stake
        equity = self.wallets.get_total_stake_amount() if self.wallets else proposed_stake
        stake = min((equity * self.RISK_PER_TRADE) / stop_pct, max_stake)
        if min_stake is not None:
            stake = max(stake, min_stake)
        return stake

    def adjust_trade_position(self, trade: Trade, current_time: datetime,
                              current_rate: float, current_profit: float,
                              min_stake: float | None, max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_entry_profit: float, current_exit_profit: float,
                              **kwargs) -> float | None:
        """Book FIRST_LEG_FRACTION at +1R, once."""
        if trade.nr_of_successful_exits >= 1:
            return None
        sr = self._stop_and_risk(trade.pair, trade)
        if sr is None:
            return None
        _, risk = sr
        if current_rate < trade.open_rate + self.FIRST_LEG_R * risk:
            return None
        amount = trade.stake_amount * self.FIRST_LEG_FRACTION
        if min_stake is not None and amount < min_stake:
            return None
        return -amount

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float,
                        after_fill: bool, **kwargs) -> float | None:
        sr = self._stop_and_risk(pair, trade)
        if sr is None:
            return None
        stop, _ = sr
        # once the first leg is booked the remainder rides on a breakeven stop
        if trade.nr_of_successful_exits >= 1:
            stop = trade.open_rate
        return stoploss_from_absolute(stop, current_rate, is_short=False,
                                      leverage=trade.leverage)

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        sr = self._stop_and_risk(pair, trade)
        if sr is not None:
            _, risk = sr
            if current_rate >= trade.open_rate + self.RUNNER_R * risk:
                return "runner_3R"
        held_bars = (current_time - trade.open_date_utc) / pd.Timedelta(self.timeframe)
        if held_bars >= self.TIME_STOP_BARS:
            return "time_stop"
        return None


class EthVmcFixed3R(EthVmcScaleOut):
    """Control: same entries, one exit at 3R. The strict 1:3 reading."""

    position_adjustment_enable = False
    FIRST_LEG_FRACTION = 0.0

    def adjust_trade_position(self, *args, **kwargs):
        return None

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float,
                        after_fill: bool, **kwargs) -> float | None:
        sr = self._stop_and_risk(pair, trade)
        if sr is None:
            return None
        return stoploss_from_absolute(sr[0], current_rate, is_short=False,
                                      leverage=trade.leverage)
