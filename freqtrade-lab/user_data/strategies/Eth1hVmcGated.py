"""ETH 1h VMC capitulation behind a daily regime gate — the batch-5 winner.

From research/ETH_RESEARCH_LOG.md. Two variants, because the brief's "60%
accuracy at 1:3" has two honest readings and they need different exits:

  Eth1hVmcGated   G075 scale-out — maximises NET win rate (67.6% in the harness)
  Eth1hVmcStrict  one fixed 3R exit — maximises trades that truly reach 1:3 (41%)

The discovery batch 5 rests on: on 4h every regime gate starved the signal, but
on 1h the daily gate is the strongest dial in the whole study (+0.20 avgR gated
vs -0.17 ungated). 1h produces enough candidates to pay for a filter.
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

from backend.config import load_config                      # noqa: E402
from backend.indicators.vumanchu import VuManChuCipherB     # noqa: E402
from backend.screener import rs                             # noqa: E402


class Eth1hVmcGated(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False

    # --- batch-5 plateau, not the single best cell --------------------------
    WT2_EXTREME = -50.0
    ATR_STOP_MULT = 2.0
    PIVOT_LOOKBACK = 4
    MAX_RISK_PCT = 0.10
    GATE_PAIR = "ETH/USDT"           # ETH's own daily trend beat BTC's here
    GATE_ALLOW = ("bull", "neutral")

    FIRST_LEG_R = 0.75
    FIRST_LEG_FRACTION = 0.5
    RUNNER_R = 3.0
    TIME_STOP_BARS = 240
    RISK_PER_TRADE = 0.01

    minimal_roi = {"0": 100}
    stoploss = -0.99
    use_custom_stoploss = True
    trailing_stop = False
    use_exit_signal = True
    position_adjustment_enable = True

    process_only_new_candles = True
    startup_candle_count = 400

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._params_1d = load_config().classifier_params("1d")
        self._gate_cache: pd.Series | None = None

    def informative_pairs(self):
        return [(self.GATE_PAIR, "1d")]

    # ------------------------------------------------------------------ gate
    def _gate_ok(self, index: pd.DatetimeIndex) -> np.ndarray:
        """Daily regime, knowable only one full day after the bar it labels."""
        if self._gate_cache is None:
            daily = self.dp.get_pair_dataframe(self.GATE_PAIR, "1d")
            if daily is None or daily.empty:
                raise RuntimeError(f"{self.GATE_PAIR} 1d data is required")
            hist = rs.classify_history(daily.set_index("date")["close"],
                                       self._params_1d, drop_forming=False)
            shifted = pd.Series(hist["direction"].to_numpy(),
                                index=hist.index + pd.Timedelta("1D"))
            self._gate_cache = shifted
        state = (self._gate_cache.reindex(index, method="ffill")
                 .fillna("unknown"))
        return state.isin(self.GATE_ALLOW).to_numpy()

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
        dataframe["vmc_signal"] = (signal & self._gate_ok(df.index)).astype(int)
        return dataframe

    @staticmethod
    def _atr(df: DataFrame, length: int = 14) -> np.ndarray:
        prev_c = df["close"].shift(1)
        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - prev_c).abs(),
                        (df["low"] - prev_c).abs()], axis=1).max(axis=1)
        return tr.rolling(length, min_periods=length).mean().to_numpy()

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["vmc_signal"] == 1,
                      ["enter_long", "enter_tag"]] = (1, "vmc_cap_1h")
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
        if trade.nr_of_successful_exits >= 1:
            return None
        sr = self._stop_and_risk(trade.pair, trade)
        if sr is None:
            return None
        if current_rate < trade.open_rate + self.FIRST_LEG_R * sr[1]:
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
        stop = trade.open_rate if trade.nr_of_successful_exits >= 1 else sr[0]
        return stoploss_from_absolute(stop, current_rate, is_short=False,
                                      leverage=trade.leverage)

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        sr = self._stop_and_risk(pair, trade)
        if sr is not None and current_rate >= trade.open_rate + self.RUNNER_R * sr[1]:
            return "runner_3R"
        if (current_time - trade.open_date_utc) / pd.Timedelta("1h") >= self.TIME_STOP_BARS:
            return "time_stop"
        return None


class Eth1hVmcStrict(Eth1hVmcGated):
    """One exit at a clean 3R — the strict "1:3" reading, best strict cell found."""

    WT2_EXTREME = -50.0
    ATR_STOP_MULT = 0.75
    PIVOT_LOOKBACK = 4
    GATE_PAIR = "BTC/USDT"
    position_adjustment_enable = False

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
