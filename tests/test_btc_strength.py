import math

import pandas as pd

from backend.config import load_config
from backend.data.frames import empty_ohlcv, resample_ohlcv
from backend.data.ohlcv import OHLCVService
from backend.data.pairs import RatioBuilder
from backend.screener import btc_strength as bs
from backend.screener import rs
from .util import FakeAdapter, make_ohlcv, trend


class FakeDominance:
    """BtcDominance stand-in: canned BTCDOM frames, no network."""

    def __init__(self, frames: dict[str, pd.DataFrame], pct: float | None = 57.0):
        self.frames = frames
        self.pct = pct

    def candles(self, timeframe, limit=500):
        return self.frames.get(timeframe, empty_ohlcv())

    def current_pct(self):
        return self.pct


def _series(tf, n, drift, seed):
    return make_ohlcv(trend(n, 100, drift, noise=0.002, seed=seed), timeframe=tf)


def test_change_since_reads_the_last_finished_candle():
    frame = make_ohlcv([100, 110, 120, 130, 150], timeframe="1h",
                       start="2026-01-01 00:00")
    now = pd.Timestamp("2026-01-01 04:30", tz="UTC")   # inside the 04:00 candle
    # 2h back = 02:30; the last candle finished by then is 01:00-02:00 (close 110)
    assert math.isclose(bs.change_since(frame, "1h", 2 * 3600, now=now),
                        (150 / 110 - 1) * 100)
    # Window longer than the history -> no answer
    assert math.isnan(bs.change_since(frame, "1h", 10 * 3600, now=now))


def test_trend_state_up_down_sideways_unknown():
    up = pd.Series(trend(80, 100, 0.01))
    down = pd.Series(trend(80, 100, -0.01))
    assert bs.trend_state(up, 20)[0] == bs.UP
    assert bs.trend_state(down, 20)[0] == bs.DOWN
    # Long rise, then a sharp drop below the still-rising EMA
    dip = pd.Series(trend(80, 100, 0.01) + [150.0, 150.0])
    assert bs.trend_state(dip, 50)[0] == bs.SIDEWAYS
    assert bs.trend_state(up, 200)[0] == rs.UNKNOWN


def test_one_month_timeframe_resamples_from_daily():
    config = load_config()
    service = OHLCVService(FakeAdapter({}), config)
    assert service.source_for("1M") == ("1d", 30)
    daily = make_ohlcv(list(range(1, 91)), timeframe="1d", start="2026-01-01")
    monthly = resample_ohlcv(daily, "1M")
    assert list(monthly.index.strftime("%Y-%m-%d")) == [
        "2026-01-01", "2026-02-01", "2026-03-01"]
    assert monthly["close"].iloc[0] == 31      # Jan 31 close


def test_board_ranks_coins_against_btc_and_uses_btc_d_for_btc():
    frames = {}
    for coin, drift, seed in (("BTC", 0.0005, 1), ("SOL", 0.004, 2),
                              ("ADA", -0.003, 3)):
        frames[(coin, "USDT", "15m")] = _series("15m", 200, drift, seed)
        frames[(coin, "USDT", "1h")] = _series("1h", 200, drift, seed)
        frames[(coin, "USDT", "1d")] = _series("1d", 260, drift * 4, seed)
    # A native SOL/BTC book quantised flat (CoinDCX's 6-decimal BTC books):
    # the board must ignore it and divide the USDT legs instead.
    for tf, n in (("15m", 200), ("1h", 200), ("1d", 260)):
        frames[("SOL", "BTC", tf)] = make_ohlcv([0.000001] * n, timeframe=tf)
    config = load_config()
    service = OHLCVService(FakeAdapter(frames), config, cache_ttl=0)
    builder = RatioBuilder(service, config, universe_coins=["BTC", "SOL", "ADA"])
    dominance = FakeDominance({
        "15m": _series("15m", 200, -0.001, 4),
        "1h": _series("1h", 200, -0.002, 4),
        "4h": _series("4h", 200, -0.004, 4),
        "1d": _series("1d", 260, -0.004, 4),
    })

    board = bs.build_board(builder, config, ["BTC", "SOL", "ADA"], dominance,
                           ["1h", "4h", "1d"], liquidity_gate=True)

    s = board.strength.set_index(["asset", "timeframe"])
    # BTC is the benchmark: its strength comes from BTC.D, not BTC/BTC
    assert "BTC" not in board.strength["asset"].values
    assert s.loc[("BTC.D", "1h"), "direction"] == rs.BEAR
    assert s.loc[("SOL", "1h"), "direction"] == rs.BULL
    assert s.loc[("ADA", "1h"), "direction"] == rs.BEAR
    assert s.loc[("SOL", "1d"), "pct_vs_btc"] > 0 > s.loc[("ADA", "1d"), "pct_vs_btc"]

    assert board.order[:2] == ["BTC.D", "BTC"]
    assert board.order[2:] == ["SOL", "ADA"]          # strongest first
    summary = board.summary().set_index("asset")
    assert summary.loc["SOL", "beats"] == 3 and summary.loc["ADA", "lags"] == 3

    breadth = board.breadth().set_index("timeframe")
    assert breadth.loc["1h", "stronger"] == 1 and breadth.loc["1h", "weaker"] == 1

    t = board.trends.set_index(["asset", "horizon"])
    assert t.loc[("BTC", "short"), "state"] == bs.UP
    assert t.loc[("ADA", "long"), "state"] == bs.DOWN
    assert t.loc[("BTC.D", "medium"), "state"] == bs.DOWN
    assert board.btc_dominance_pct == 57.0


def test_board_marks_illiquid_coins_unknown():
    frames = {("SOL", "USDT", "1h"): _series("1h", 200, 0.004, 2),
              ("BTC", "USDT", "1h"): _series("1h", 200, 0.0005, 1)}
    config = load_config()
    adapter = FakeAdapter(frames, volumes={("SOL", "USDT"): 1.0})
    builder = RatioBuilder(OHLCVService(adapter, config, cache_ttl=0), config,
                           universe_coins=["BTC", "SOL"])
    board = bs.build_board(builder, config, ["SOL"], FakeDominance({}, pct=None),
                           ["1h"])
    sol = board.strength[board.strength["asset"] == "SOL"].iloc[0]
    assert sol["direction"] == rs.UNKNOWN and sol["reason"] == "illiquid"
    # No BTCDOM data -> BTC.D unknown, not a crash
    btcd = board.strength[board.strength["asset"] == "BTC.D"].iloc[0]
    assert btcd["direction"] == rs.UNKNOWN
