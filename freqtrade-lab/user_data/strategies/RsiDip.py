# Mean reversion: buy a scared dip, sell the bounce. Take small profits fast.
from pandas import DataFrame
from freqtrade.strategy import IStrategy
import talib.abstract as ta


class RsiDip(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False

    minimal_roi = {"0": 0.04, "120": 0.02, "360": 0.01, "720": 0}
    stoploss = -0.10

    trailing_stop = False
    process_only_new_candles = True
    use_exit_signal = True
    startup_candle_count = 200

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=200)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["rsi"] < 30)
                & (dataframe["close"] > dataframe["ema_trend"])
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            ((dataframe["rsi"] > 70) & (dataframe["volume"] > 0)),
            "exit_long",
        ] = 1
        return dataframe
