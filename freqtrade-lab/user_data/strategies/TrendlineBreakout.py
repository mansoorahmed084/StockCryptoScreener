"""Long-term descending trendline breakout — the trader's own chart setup.

Two daily charts were supplied, TAO/USDT and STX/USDT. Both show one falling
line anchored at a major high, resting on every lower high for the better part
of a year, and a break that ran far. This is that setup, mechanised.

It is deliberately NOT DailyDivBreakout. There the line spans the few days
since a divergence pivot and the trade is closed at 3R. Here the line spans
months, no divergence is required, and the trade is left to run behind a
trailing stop — because capping these at 3R measured a holdout ratio of 0.14
against 0.78 for the trail. The whole point of the setup is the size of the
move, and a fixed target throws it away.

Entry (daily closes, long only):
  * anchor = highest high of the last LOOKBACK days
  * line   = the shallowest falling line from that anchor that no later high
             pokes through — the line a trader draws across the lower highs.
             Built only from bars BEFORE the signal bar, so it is knowable live.
  * the break must be at least MIN_SPAN days after the anchor  ("long term")
  * price must have fallen MIN_DROP_PCT beneath the anchor      (a real downtrend)
  * at least MIN_TOUCHES highs must sit within TOUCH_TOL of the line
  * signal = today closes above the line and yesterday closed below it
  * stop   = lowest low of the last STOP_LOOKBACK days, minus ATR_MULT x ATR(14)

Exit: stop, then a trailing stop TRAIL_R risk-units behind the running high
once the trade is that far in front. TIME_STOP_BARS days is the backstop.

Long only. The short mirror of every entry family tested in this project came
out negative; see research/HANDOVER.md.

Backtest with --timeframe-detail 1h. On daily candles alone freqtrade cannot
tell whether the stop or the high came first inside a bar.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, stoploss_from_absolute


class TrendlineBreakout(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    can_short = False

    # --- how the line is drawn ---
    LOOKBACK = 200              # days the anchor high may be found in
    MIN_SPAN = 60               # days from anchor to break
    MIN_TOUCHES = 3             # highs on the line, anchor included
    TOUCH_TOL = 0.03            # "on the line" means within this fraction
    MIN_DROP_PCT = 0.25         # fall from the anchor before the break
    VOL_MULT = 1.5              # break volume vs its own 20-day mean

    # --- risk and exit ---
    STOP_LOOKBACK = 20
    ATR_MULT = 1.5
    MAX_RISK_PCT = 0.25
    TRAIL_R = 3.0               # trail this many risk-units behind the high
    TIME_STOP_BARS = 365
    RISK_PER_TRADE = 0.01

    COOLDOWN = 20               # one event, one trade

    minimal_roi = {"0": 100}    # never take profit on ROI; the trail does it
    stoploss = -0.99
    use_custom_stoploss = True
    trailing_stop = False       # the trail is in custom_stoploss, in R units
    use_exit_signal = True      # gates custom_exit; see reference memory
    process_only_new_candles = True
    startup_candle_count = 260

    # ------------------------------------------------------------ indicators
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        n = len(df)
        signal = np.zeros(n, dtype=bool)
        stop = np.full(n, np.nan)

        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        vols = df["volume"].to_numpy(dtype=float)
        volmean = df["volume"].rolling(20).mean().to_numpy()
        atr = self._atr(df, 14)

        seen_anchor: set[int] = set()
        last_i = -10 ** 9

        for i in range(self.LOOKBACK + 1, n):
            # a break is an up close; skips about half the bars for free
            if closes[i] <= closes[i - 1] or i - last_i < self.COOLDOWN:
                continue

            lo_w = i - self.LOOKBACK
            a = lo_w + int(np.argmax(highs[lo_w:i]))     # strictly before i
            if i - a < self.MIN_SPAN or a in seen_anchor:
                continue

            # shallowest slope from the anchor that no later high pokes through
            ks = np.arange(a + 1, i)
            if ks.size == 0:
                continue
            slopes = (highs[a + 1:i] - highs[a]) / (ks - a)
            s = float(slopes.max())
            if s >= 0:                                    # must be FALLING
                continue

            level = highs[a] + s * (i - a)
            prev = highs[a] + s * (i - 1 - a)
            if not (closes[i] > level and closes[i - 1] <= prev):
                continue

            trough = float(lows[a:i].min())
            if highs[a] <= 0 or (highs[a] - trough) / highs[a] < self.MIN_DROP_PCT:
                continue

            line = highs[a] + s * (np.arange(a, i) - a)
            if int(np.sum(highs[a:i] >= line * (1.0 - self.TOUCH_TOL))) < self.MIN_TOUCHES:
                continue

            if self.VOL_MULT is not None:
                vm = volmean[i]
                if not np.isfinite(vm) or vm <= 0 or vols[i] < self.VOL_MULT * vm:
                    continue

            if not np.isfinite(atr[i]):
                continue
            swing_low = float(lows[max(0, i - self.STOP_LOOKBACK + 1):i + 1].min())
            stop_price = swing_low - self.ATR_MULT * atr[i]
            ref = float(closes[i])
            if stop_price <= 0 or ref <= 0:
                continue
            if (ref - stop_price) / ref > self.MAX_RISK_PCT:
                continue

            seen_anchor.add(a)
            last_i = i
            signal[i] = True
            stop[i] = stop_price

        dataframe["tl_stop"] = stop
        dataframe["tl_signal"] = signal.astype(int)
        return dataframe

    @staticmethod
    def _atr(df: DataFrame, length: int = 14) -> np.ndarray:
        prev_c = df["close"].shift(1)
        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - prev_c).abs(),
                        (df["low"] - prev_c).abs()], axis=1).max(axis=1)
        return tr.rolling(length, min_periods=length).mean().to_numpy()

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["tl_signal"] == 1,
                      ["enter_long", "enter_tag"]] = (1, "trendline_break")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    # -------------------------------------------------------------- per-trade
    SIGNAL_MAX_AGE = pd.Timedelta(days=3)

    def _signal_stop(self, pair: str, before: datetime) -> float | None:
        """The stop from the latest SIGNAL candle that closed before `before`.

        This used to read simply the last candle before the entry. That is the
        signal candle only when the fill lands on the next candle open. When it
        lands later -- a slot freeing up at 04:00 under --timeframe-detail, or a
        live bot restarting -- the last candle is an ordinary one with no stop.
        custom_stoploss then returned None, freqtrade fell back to the static
        -99% stop, and the trade ran with no stop and no trail. Four of 311
        trades did that in the 203-coin backtest, and one lost 54%. Searching
        for the signal candle itself fixes both the stop and the position size.
        """
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty:
            return None
        rows = df.loc[(df["date"] < before) & (df["tl_signal"] == 1)]
        if rows.empty:
            return None
        last = rows.iloc[-1]
        if before - last["date"] > self.SIGNAL_MAX_AGE:
            return None                  # an older setup, not this trade's signal
        stop = float(last["tl_stop"])
        return stop if np.isfinite(stop) else None

    def _stop_and_risk(self, pair: str, trade: Trade) -> tuple[float, float] | None:
        stop = self._signal_stop(pair, trade.open_date_utc)
        if stop is None:
            return None
        # A fill at or below the stop means the setup had already failed when
        # the order filled. confirm_trade_entry refuses those; this is the
        # fallback for anything that gets through. Keep the stop, with a token
        # risk, so the trade exits at once instead of running on the static
        # -99% stop. Returning None here is what left three trades in the
        # 203-coin backtest with no stop at all, one of them losing 54%.
        risk = max(trade.open_rate - stop, trade.open_rate * 1e-6)
        return stop, risk

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: str | None, side: str, **kwargs) -> bool:
        """Refuse a fill that is already at or below the setup's stop.

        The research engine fills at the next daily open, where price is above
        the stop. Freqtrade can fill later in the day -- when a slot frees up,
        or live after a delay -- and by then price may have fallen through the
        stop. That trade is a loss that has already happened, so it is not
        taken. With no stop found at all, the trade is refused too: it would
        otherwise run unprotected.
        """
        stop = self._signal_stop(pair, current_time)
        return stop is not None and rate > stop

    def custom_stake_amount(self, pair: str, current_time: datetime,
                            current_rate: float, proposed_stake: float,
                            min_stake: float | None, max_stake: float,
                            leverage: float, entry_tag: str | None,
                            side: str, **kwargs) -> float:
        stop = self._signal_stop(pair, current_time)
        if stop is None or current_rate <= 0:
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
        stop, risk = sr
        # Trail behind the highest price the trade has seen, in risk units, and
        # only ever ratchet up -- max() against the entry stop does that, so the
        # trail can never loosen the protection the setup started with.
        peak = float(trade.max_rate or trade.open_rate)
        if peak - trade.open_rate >= risk:
            stop = max(stop, peak - self.TRAIL_R * risk)
        return stoploss_from_absolute(stop, current_rate, is_short=False,
                                      leverage=trade.leverage)

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        if (current_time - trade.open_date_utc).days >= self.TIME_STOP_BARS:
            return "time_stop"
        return None


class TrendlineBreakoutWide(TrendlineBreakout):
    """No volume confirmation: ~50% more trades, thinner per trade."""

    VOL_MULT = None
