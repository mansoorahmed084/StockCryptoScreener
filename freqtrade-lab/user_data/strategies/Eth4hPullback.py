"""ETH 4h pullback + stochastic reset — the phase-2 leaders, for freqtrade.

From research/ETH_RESEARCH_LOG.md batch 9. Two variants because the in-sample
leader and the best out-of-sample config are not the same configuration, and
pretending otherwise would be dishonest:

  Eth4hPullback       best in-sample: +0.513R, PF 2.00, 46 trades/yr, 20.4R DD
                      but only 31.6% over 19 out-of-sample trades
  Eth4hPullbackLowDD  best out-of-sample: 66.7% over 33 trades, 17.6-20.2R DD,
                      worst losing streak 8, at a lower +0.22R

Entry, both variants (4h closes, long only):
  * the bar low pierces EMA(20) and it closes back above  — the pullback
  * a stochastic %K/%D cross up happened within the last 2 bars — the "reset"
  * the daily regime gate is not against the trade
  * stop under the 5-bar swing low, minus ATR_STOP_MULT * ATR(14)

Long only on purpose. Batch 9 measured the short mirror at -0.003R median
against +0.220R for longs: this entry has no short-side edge on ETH.
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

from backend.config import load_config          # noqa: E402
from backend.indicators import common           # noqa: E402
from backend.screener import rs                 # noqa: E402


class Eth4hPullback(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "4h"
    can_short = False

    EMA_LEN = 20
    STOCH_K, STOCH_SMOOTH, STOCH_D = 14, 3, 3
    CROSS_WITHIN = 2          # batch 9: 2 bars halves drawdown vs 5
    SWING_LEN = 5
    ATR_STOP_MULT = 2.0
    MAX_RISK_PCT = 0.10
    GATE_PAIR = "BTC/USDT"
    GATE_ALLOW = ("bull", "neutral")

    TARGET_R = 3.0
    FIRST_LEG_R: float | None = None    # None = single exit at TARGET_R
    FIRST_LEG_FRACTION = 0.5
    TIME_STOP_BARS = 120
    RISK_PER_TRADE = 0.01

    minimal_roi = {"0": 100}
    stoploss = -0.99
    use_custom_stoploss = True
    trailing_stop = False
    use_exit_signal = True
    position_adjustment_enable = False
    process_only_new_candles = True
    startup_candle_count = 300

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._params_1d = load_config().classifier_params("1d")
        self._gate_cache: pd.Series | None = None

    def informative_pairs(self):
        return [(self.GATE_PAIR, "1d")]

    def _gate_ok(self, index: pd.DatetimeIndex) -> np.ndarray:
        if self._gate_cache is None:
            daily = self.dp.get_pair_dataframe(self.GATE_PAIR, "1d")
            if daily is None or daily.empty:
                raise RuntimeError(f"{self.GATE_PAIR} 1d data is required")
            hist = rs.classify_history(daily.set_index("date")["close"],
                                       self._params_1d, drop_forming=False)
            self._gate_cache = pd.Series(hist["direction"].to_numpy(),
                                         index=hist.index + pd.Timedelta("1D"))
        state = self._gate_cache.reindex(index, method="ffill").fillna("unknown")
        return state.isin(self.GATE_ALLOW).to_numpy()

    @staticmethod
    def _atr(df: DataFrame, length: int = 14) -> pd.Series:
        prev_c = df["close"].shift(1)
        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - prev_c).abs(),
                        (df["low"] - prev_c).abs()], axis=1).max(axis=1)
        return tr.rolling(length, min_periods=length).mean()

    def _stochastic(self, df: DataFrame) -> tuple[pd.Series, pd.Series]:
        low = df["low"].rolling(self.STOCH_K, min_periods=self.STOCH_K).min()
        high = df["high"].rolling(self.STOCH_K, min_periods=self.STOCH_K).max()
        rng = (high - low).replace(0, np.nan)
        k = common.sma(100 * (df["close"] - low) / rng, self.STOCH_SMOOTH)
        return k, common.sma(k, self.STOCH_D)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe.set_index("date")
        ema = common.ema(df["close"], self.EMA_LEN)
        k, d = self._stochastic(df)
        atr = self._atr(df, 14)

        pullback = (df["low"] <= ema) & (df["close"] > ema)
        cross = (k.shift(1) <= d.shift(1)) & (k > d)
        cross_recent = (cross.fillna(False)
                        .rolling(self.CROSS_WITHIN, min_periods=1)
                        .max().astype(bool))
        stop = (df["low"].rolling(self.SWING_LEN, min_periods=1).min()
                - self.ATR_STOP_MULT * atr)

        risk_ok = ((df["close"] - stop) / df["close"]).between(0, self.MAX_RISK_PCT)
        signal = (pullback & cross_recent & risk_ok & stop.notna()
                  & self._gate_ok(df.index))

        dataframe["vmc_stop"] = stop.to_numpy()
        dataframe["vmc_signal"] = signal.to_numpy().astype(int)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["vmc_signal"] == 1,
                      ["enter_long", "enter_tag"]] = (1, "pullback_reset")
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
        return max(stake, min_stake) if min_stake is not None else stake

    def adjust_trade_position(self, trade: Trade, current_time: datetime,
                              current_rate: float, current_profit: float,
                              min_stake: float | None, max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_entry_profit: float, current_exit_profit: float,
                              **kwargs) -> float | None:
        if self.FIRST_LEG_R is None or trade.nr_of_successful_exits >= 1:
            return None
        sr = self._stop_and_risk(trade.pair, trade)
        if sr is None or current_rate < trade.open_rate + self.FIRST_LEG_R * sr[1]:
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
        stop = (trade.open_rate if (self.FIRST_LEG_R is not None
                                    and trade.nr_of_successful_exits >= 1)
                else sr[0])
        return stoploss_from_absolute(stop, current_rate, is_short=False,
                                      leverage=trade.leverage)

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        sr = self._stop_and_risk(pair, trade)
        if sr is not None and current_rate >= trade.open_rate + self.TARGET_R * sr[1]:
            return f"target_{self.TARGET_R:g}R"
        if (current_time - trade.open_date_utc) / pd.Timedelta("4h") >= self.TIME_STOP_BARS:
            return "time_stop"
        return None


class Eth4hPullbackLowDD(Eth4hPullback):
    """Lowest drawdown that still earns, and the best out-of-sample behaviour."""

    ATR_STOP_MULT = 0.5
    GATE_PAIR = "ETH/USDT"
    FIRST_LEG_R = 1.0            # book half at 1R, stop to breakeven
    position_adjustment_enable = True
