import numpy as np
import pandas as pd

from backend.indicators import common, wavetrend
from backend.indicators.vumanchu import VuManChuCipherB
from .util import make_ohlcv


def test_pivot_detection():
    s = pd.Series([5, 3, 1, 3, 5, 4, 2, 4, 6])
    lows = common.pivot_lows(s, 2, 2)
    highs = common.pivot_highs(s, 2, 2)
    assert bool(lows.iloc[2]) is True    # the 1 is a pivot low
    assert bool(highs.iloc[4]) is True   # value 5, unique local max (neighbours 1,3,4,2)
    assert bool(common.pivot_highs(pd.Series([1, 3, 5, 4, 2]), 2, 2).iloc[2]) is True


def test_wavetrend_finite():
    closes = list(np.linspace(100, 140, 120)) + list(np.linspace(140, 110, 40))
    df = make_ohlcv(closes, timeframe="1h")
    wt1, wt2 = wavetrend.wavetrend(df)
    assert wt1.notna().sum() > 100
    assert np.isfinite(wt1.iloc[-1])


def test_vumanchu_structure_and_signals():
    closes = list(np.linspace(100, 120, 100)) + list(np.linspace(120, 105, 30))
    df = make_ohlcv(closes, timeframe="1h")
    res = VuManChuCipherB().compute(df)
    assert set(["wt1", "wt2", "mfi"]).issubset(res.panes)
    for key in ("vumanchu_buy", "vumanchu_sell", "vumanchu_bull_div",
                "vumanchu_bear_div"):
        assert key in res.signals


def test_vumanchu_buy_on_oversold_reversal():
    # sharp decline into oversold, then a reversal -> expect a WT buy cross
    down = list(np.linspace(100, 60, 60))
    up = list(np.linspace(60, 95, 40))
    df = make_ohlcv(down + up, timeframe="1h")
    res = VuManChuCipherB().compute(df)
    assert any(m.kind == "buy" for m in res.markers)


# --- Technical Sentiment Composite --------------------------------------------
import pytest  # noqa: E402

from backend.indicators import sentiment as ts  # noqa: E402
from backend.indicators import wave_flow as wf  # noqa: E402
from backend.indicators.sentiment import TechnicalSentiment  # noqa: E402
from backend.indicators.wave_flow import WaveFlowMatrix  # noqa: E402
from .util import trend  # noqa: E402


def _noisy(n=400, drift=0.0, seed=5, timeframe="1h", volume_seed=None):
    df = make_ohlcv(trend(n, 100.0, drift, noise=0.01, seed=seed), timeframe=timeframe,
                    start="2026-01-01")
    df["high"] *= 1.002
    df["low"] *= 0.998
    if volume_seed is not None:
        df["volume"] = np.random.default_rng(volume_seed).lognormal(6, 0.5, n)
    return df


def test_zone_scale_maps_each_zone_to_a_quarter():
    s = pd.Series([0, 15, 30, 50, 70, 85, 100, np.nan])
    out = common.zone_scale(s, (0, 30, 50, 70, 100))
    assert list(out.iloc[:7]) == [0, 12.5, 25, 50, 75, 87.5, 100]
    assert np.isnan(out.iloc[7])
    wide = common.zone_scale(pd.Series([-500, -100, 0, 200, 900]), (-300, -100, 0, 100, 300))
    assert list(wide) == [0, 25, 50, 87.5, 100]            # clipped at the ends


def test_anchored_range_score_restarts_on_flips():
    close = pd.Series([10, 12, 11, 9, 13, 12, 8.0])
    buy = np.array([0, 0, 0, 0, 1, 0, 0], dtype=bool)
    sell = np.array([0, 0, 0, 0, 0, 0, 1], dtype=bool)
    out = ts.anchored_range_score(close, buy, sell, smooth=1)
    assert out.iloc[1] == 100 and out.iloc[3] == 0     # running range before any signal
    assert out.iloc[4] == 100                           # buy flip: the high restarts at the close
    assert out.iloc[5] == pytest.approx(75)             # 12 between low 9 and high 13
    assert out.iloc[6] == 0                             # sell flip: the low restarts at the close
    # a buy flip below the old low still reads as the top of the range, not a gap
    low_flip = ts.anchored_range_score(pd.Series([10, 12, 9, 8.0]), np.array([0, 0, 0, 1], dtype=bool),
                                       np.zeros(4, dtype=bool), smooth=1)
    assert low_flip.iloc[3] == 100 and low_flip.notna().iloc[1:].all()


def test_structure_breaks_wait_for_the_swing_to_be_known():
    highs = [10, 11, 15, 11, 10, 10.5, 16, 17]
    df = pd.DataFrame({"high": highs, "low": [h - 1 for h in highs],
                       "close": [9.5, 10.5, 14.5, 10.5, 9.5, 10.2, 15.5, 16.5]})
    buy, sell = ts.structure_breaks(df, 2)
    assert list(np.where(buy)[0]) == [6]                # closes above the 15 swing, once
    assert not sell.any()


def test_sentiment_structure_and_range():
    res = TechnicalSentiment().compute(_noisy(volume_seed=1))
    assert set(ts.COMPONENTS) | {"sentiment", "momentum", "trend"} == set(res.panes)
    for name, series in res.panes.items():
        vals = series.dropna()
        assert len(vals) > 300, name
        assert vals.between(0, 100).all(), name
    for key in ("sentiment_bullish", "sentiment_bearish", "sentiment_strong_bullish",
                "sentiment_strong_bearish", "sentiment_bull_div", "sentiment_bear_div"):
        assert key in res.signals
    assert {m.kind for m in res.markers} <= {"bull_div", "bear_div"}


def test_sentiment_reads_trends():
    up = TechnicalSentiment().compute(_noisy(drift=0.004))
    down = TechnicalSentiment().compute(_noisy(drift=-0.004))
    assert up.panes["sentiment"].iloc[-150:].mean() > 60
    assert down.panes["sentiment"].iloc[-150:].mean() < 40
    assert up.panes["trend"].iloc[-150:].mean() > down.panes["trend"].iloc[-150:].mean() + 30


def test_sentiment_vwap_needs_volume_on_any_timeframe():
    # LuxAlgo anchors the VWAP by timeframe (day, week, month, quarter), so daily charts have one too
    assert "vwap" in TechnicalSentiment().compute(_noisy(volume_seed=1)).panes
    assert "vwap" in TechnicalSentiment().compute(_noisy(timeframe="1d", volume_seed=1)).panes
    flat = _noisy()
    flat["volume"] = 0.0
    res = TechnicalSentiment().compute(flat)
    assert "vwap" not in res.panes and res.panes["sentiment"].notna().sum() > 300


def test_sentiment_rating_bands():
    ind = TechnicalSentiment()
    assert [ind.rating(v) for v in (10, 30, 50, 65, 90)] == list(ts.RATINGS)
    assert ind.rating(float("nan")) == ""
    assert TechnicalSentiment().compute(_noisy(20)).panes == {}       # too short: nothing
    with pytest.raises(ValueError):
        TechnicalSentiment(rsi_len=0)


def test_sentiment_does_not_look_ahead():
    df = _noisy(volume_seed=2)
    full = TechnicalSentiment().compute(df)
    part = TechnicalSentiment().compute(df.iloc[:300])
    for name in ("sentiment", "structure", "supertrend", "vwap"):
        pd.testing.assert_series_equal(full.panes[name].iloc[:300], part.panes[name])


# --- Wave & Flow Matrix ---------------------------------------------------------
def test_matrix_structure_and_ranges():
    res = WaveFlowMatrix().compute(_noisy(volume_seed=3))
    assert set(res.panes) == {"wave", "signal", "flow", "flow_upper", "flow_lower",
                              "overflow", "confluence_up", "confluence_down", "meter"}
    for name in ("wave", "signal", "flow", "meter"):
        vals = res.panes[name].dropna()
        assert len(vals) > 300 and vals.between(0, 100).all(), name
    assert set(res.panes["confluence_up"].dropna().unique()) <= {0, 1, 2}
    both = res.panes["confluence_up"] + res.panes["confluence_down"]
    assert (both.dropna() <= 2).all()                    # a side each, never both
    assert (res.panes["flow_upper"].dropna() >= 50).all()
    assert (res.panes["flow_lower"].dropna() <= 50).all()
    assert all(k.startswith("matrix_") for k in res.signals) and len(res.signals) == 14
    kinds = {m.kind for m in res.markers}
    assert {"turn_up", "turn_down"} <= kinds
    assert [m.ts for m in res.markers] == sorted(m.ts for m in res.markers)


def test_matrix_reads_a_rally_and_a_slide():
    up = WaveFlowMatrix().compute(_noisy(drift=0.004, volume_seed=3))
    down = WaveFlowMatrix().compute(_noisy(drift=-0.004, volume_seed=3))
    assert up.panes["flow"].iloc[-150:].mean() > 55 > 45 > down.panes["flow"].iloc[-150:].mean()
    assert up.panes["wave"].iloc[-150:].mean() > 55 > 45 > down.panes["wave"].iloc[-150:].mean()
    assert up.panes["meter"].iloc[-150:].mean() > down.panes["meter"].iloc[-150:].mean() + 20
    assert (up.panes["confluence_up"].iloc[-150:] == 2).mean() > 0.5


def test_adaptive_wave_is_quick_in_trends_and_slow_in_chop():
    line = make_ohlcv(list(np.linspace(100, 130, 60)), start="2026-01-01")
    assert wf.adaptive_wave(line, 7).iloc[-1] > 95
    chop = make_ohlcv([100 + (1 if i % 2 else -1) for i in range(60)], start="2026-01-01")
    wave = wf.adaptive_wave(chop, 7)
    raw = common.stochastic(chop["close"], chop["high"], chop["low"], 7)
    assert wave.iloc[-20:].std() < raw.iloc[-20:].std() / 3


def test_swing_divergences_are_read_at_the_turn():
    nan = np.nan
    #            up-swing 1        down      up-swing 2 (lower wave, higher price)
    wave = np.array([nan, 60, 85, 70, 40, 30, 45, 70, 60, 50.0])
    high = np.array([10, 11, 12, 11, 10, 9, 10, 13, 12, 11.0])
    low = high - 1
    turn_up = np.zeros(10, dtype=bool)
    turn_down = np.zeros(10, dtype=bool)
    turn_down[[3, 8]] = True
    turn_up[5] = True
    bull, bear = wf.swing_divergences(wave, high, low, turn_up, turn_down, min_gap=10)
    assert bear == [8] and bull == []
    # a wave peak only 5 lower is inside the dead band
    wave[7] = 80
    assert wf.swing_divergences(wave, high, low, turn_up, turn_down, min_gap=10) == ([], [])


def test_matrix_reversal_after_a_volume_climax():
    closes = list(np.linspace(100, 70, 60)) + list(np.linspace(71, 85, 25))
    df = make_ohlcv(closes, start="2026-01-01")
    quiet = WaveFlowMatrix().compute(df)
    assert not any(m.kind.startswith("rev_") for m in quiet.markers)   # flat volume: no climax
    df.iloc[58:60, df.columns.get_loc("volume")] = 5000.0              # capitulation at the low
    loud = WaveFlowMatrix().compute(df)
    revs = [m for m in loud.markers if m.kind == "rev_up_major"]
    assert revs and df.index[59] <= revs[0].ts <= df.index[63]


def test_matrix_overflow_needs_a_long_one_sided_run():
    flow = pd.Series([50.0] * 5 + [60.0] * 4 + [40.0] * 4 + [60.0] * 3 + [90.0] * 12)
    upper = pd.Series(70.0, index=flow.index)
    lower = pd.Series(30.0, index=flow.index)
    over = wf.overflow(flow, upper, lower, length=6)
    # runs of 4 and 4 bars pull the usual run from 6 down to 5.125, so the
    # third run (from bar 13) only counts as late from its 6th bar
    assert (over.iloc[:18] == 0).all()                   # beyond the level, but the run is young
    assert (over.iloc[18:] == 20).all()                  # still beyond it once the run is old


def test_matrix_options_and_fallbacks():
    df = _noisy(volume_seed=4)
    trail = WaveFlowMatrix(signal_type="trail").compute(df)
    sma = WaveFlowMatrix().compute(df)
    assert not trail.panes["signal"].equals(sma.panes["signal"])
    assert trail.panes["signal"].dropna().between(0, 100).all()
    turns = lambda r: sum(m.kind.startswith("turn_") for m in r.markers)   # noqa: E731
    assert turns(trail) < turns(sma)                     # the stop ignores small wiggles
    novol = df.assign(volume=0.0)
    res = WaveFlowMatrix().compute(novol)
    assert res.panes["flow"].dropna().between(0, 100).all() and res.panes["flow"].notna().sum() > 300
    assert WaveFlowMatrix().compute(df.iloc[:20]).panes == {}
    for bad in ({"signal_type": "x"}, {"wave_len": 0}, {"reversal_factor": 0}):
        with pytest.raises(ValueError):
            WaveFlowMatrix(**bad)


def test_matrix_does_not_look_ahead():
    df = _noisy(volume_seed=6)
    full = WaveFlowMatrix().compute(df)
    part = WaveFlowMatrix().compute(df.iloc[:300])
    for name, series in part.panes.items():
        pd.testing.assert_series_equal(full.panes[name].iloc[:300], series, check_names=False)
    cut = df.index[299]
    early = [(m.ts, m.kind) for m in full.markers if m.ts <= cut]
    assert early == [(m.ts, m.kind) for m in part.markers]              # signals never move
