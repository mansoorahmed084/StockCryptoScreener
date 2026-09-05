"""Daily Capitulation Divergence (D2) — ported to Freqtrade for Binance validation.

Spec: StockCryptoScreener/STRATEGY_RESEARCH.md, section "FINAL STRATEGY".
The original research ran on CoinDCX candles through this repo's own backtest
harness (backend/research/engine.py). This file re-runs the same rules on true
Binance spot candles through an independent engine, as a replication check.

It imports the repo's real indicator code — backend.indicators.vumanchu and
backend.screener.rs — so the oscillator, the divergence detector and the BTC
regime classifier are identical to the screener's. Only the execution engine
differs.

Entry (all must hold at a daily close):
  1. VMC regular bullish divergence, pivot confirmed 3 daily closes later
  2. WT2 <= OVERSOLD_AT_PIVOT (-45) at the divergence pivot
  3. BTC/USDT daily regime from rs.classify_history is not "bear"
  4. Stop distance <= MAX_RISK_PCT of the reference close
Enter long at the next daily open.

Stop:   pivot low - 0.5 * ATR(14, daily), fixed for the life of the trade.
Target: entry + TARGET_R * risk.  Time stop: 40 daily bars.
Size:   RISK_PER_TRADE of equity per position.
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

# --- import the screener's own indicator code -------------------------------
# .../StockCryptoScreener/freqtrade-lab/user_data/strategies/this_file.py
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.config import load_config                      # noqa: E402
from backend.indicators.vumanchu import VuManChuCipherB     # noqa: E402
from backend.screener import rs                             # noqa: E402

PIVOT_RIGHT = 3          # matches VuManChuCipherB(pivot_lookback=3)
BTC_PAIR = "BTC/USDT"


class VmcCapitulation(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    can_short = False

    # --- spec dials ---------------------------------------------------------
    OVERSOLD_AT_PIVOT = -45.0
    ATR_STOP_MULT = 0.5
    MAX_RISK_PCT = 0.10      # skip the trade if the stop sits further than this
    TARGET_R = 1.5
    TIME_STOP_BARS = 40
    RISK_PER_TRADE = 0.01

    # Freqtrade's own exits are switched off; custom_stoploss/custom_exit rule.
    minimal_roi = {"0": 100}
    stoploss = -0.99
    use_custom_stoploss = True
    trailing_stop = False
    # Must stay True: freqtrade only evaluates custom_exit() when this is set
    # (interface.py should_exit). populate_exit_trend emits nothing, so the
    # target and the time stop are the only exits besides custom_stoploss.
    use_exit_signal = True

    process_only_new_candles = True
    # 60d vol lookback + EMA warmup + pivot window, with headroom.
    startup_candle_count = 200

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._cfg = load_config()
        self._params_1d = self._cfg.classifier_params("1d")
        self._btc_regime: pd.Series | None = None

    # ------------------------------------------------------------------ data
    def informative_pairs(self):
        return [(BTC_PAIR, self.timeframe)]

    def _btc_not_bear(self, index: pd.DatetimeIndex) -> pd.Series:
        """BTC daily regime via the repo's noise-filtered classifier.

        A bar's state is knowable at its own close, matching prepare_daily().
        """
        if self._btc_regime is None:
            btc = self.dp.get_pair_dataframe(BTC_PAIR, self.timeframe)
            if btc is None or btc.empty:
                raise RuntimeError(f"{BTC_PAIR} {self.timeframe} data is required")
            close = btc.set_index("date")["close"]
            hist = rs.classify_history(close, self._params_1d, drop_forming=False)
            self._btc_regime = hist["direction"]
        return (self._btc_regime.reindex(index, method="ffill")
                .fillna("unknown").ne("bear"))

    # ------------------------------------------------------------ indicators
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe.set_index("date")

        vmc = VuManChuCipherB().compute(df)
        wt2 = vmc.panes.get("wt2")
        if wt2 is None:
            dataframe["vmc_signal"] = 0
            dataframe["vmc_stop"] = np.nan
            return dataframe

        atr = self._atr(df, 14)
        n = len(df)

        signal = np.zeros(n, dtype=bool)
        stop = np.full(n, np.nan)

        for marker in vmc.markers:
            if marker.kind != "bull_div":
                continue
            p = df.index.get_loc(marker.ts)          # pivot bar
            p_conf = p + PIVOT_RIGHT                  # first bar that knows about it
            if p_conf >= n:
                continue                              # never confirmed in this data
            if float(wt2.iloc[p]) > self.OVERSOLD_AT_PIVOT:
                continue                              # not deep enough capitulation
            atr_conf = atr[p_conf]
            if not np.isfinite(atr_conf):
                continue
            stop_price = float(df["low"].iloc[p]) - self.ATR_STOP_MULT * atr_conf
            ref_close = float(df["close"].iloc[p_conf])
            if stop_price <= 0 or ref_close <= 0:
                continue
            if (ref_close - stop_price) / ref_close > self.MAX_RISK_PCT:
                continue                              # oversized risk unit, skip
            signal[p_conf] = True
            stop[p_conf] = stop_price

        dataframe["vmc_stop"] = stop
        dataframe["vmc_signal"] = (
            pd.Series(signal, index=dataframe.index)
            & self._btc_not_bear(df.index).to_numpy()
        ).astype(int)
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
        dataframe.loc[dataframe["vmc_signal"] == 1, ["enter_long", "enter_tag"]] = (
            1, "vmc_capitulation")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    # -------------------------------------------------------------- per-trade
    def _signal_stop(self, pair: str, trade: Trade) -> float | None:
        """The stop recorded on the signal candle (the bar before entry)."""
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty:
            return None
        prior = df.loc[df["date"] < trade.open_date_utc]
        if prior.empty:
            return None
        value = prior["vmc_stop"].iloc[-1]
        return float(value) if np.isfinite(value) else None

    def custom_stake_amount(self, pair: str, current_time: datetime,
                            current_rate: float, proposed_stake: float,
                            min_stake: float | None, max_stake: float,
                            leverage: float, entry_tag: str | None,
                            side: str, **kwargs) -> float:
        """Risk RISK_PER_TRADE of equity, sized off the stop distance."""
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty:
            return proposed_stake
        stop_price = df["vmc_stop"].iloc[-1]
        if not np.isfinite(stop_price) or current_rate <= 0:
            return proposed_stake
        stop_pct = (current_rate - float(stop_price)) / current_rate
        if stop_pct <= 0:
            return proposed_stake
        equity = self.wallets.get_total_stake_amount() if self.wallets else proposed_stake
        stake = min((equity * self.RISK_PER_TRADE) / stop_pct, max_stake)
        if min_stake is not None:
            stake = max(stake, min_stake)
        return stake

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float,
                        after_fill: bool, **kwargs) -> float | None:
        stop_price = self._signal_stop(pair, trade)
        if stop_price is None:
            return None
        return stoploss_from_absolute(stop_price, current_rate, is_short=False,
                                      leverage=trade.leverage)

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        stop_price = self._signal_stop(pair, trade)
        if stop_price is not None:
            risk = trade.open_rate - stop_price
            if risk > 0 and current_rate >= trade.open_rate + self.TARGET_R * risk:
                return f"target_{self.TARGET_R}R"
        if (current_time - trade.open_date_utc).days >= self.TIME_STOP_BARS:
            return "time_stop"
        return None


class VmcCapitulation1R(VmcCapitulation):
    """D6 variant — the 1.0R target that scored 73.9% IS / 81.8% OOS."""

    TARGET_R = 1.0
