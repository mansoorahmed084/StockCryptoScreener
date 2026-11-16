"""The compiled kernel must agree with the readable pandas indicator."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.indicators.sentiment import TechnicalSentiment
from calibration.data import candles_from_frame, synthetic_candles
from calibration.kernel import (COMPONENTS, DEFAULTS, PARAM_NAMES, components_kernel, snap)

CASES = [
    {},
    {"rsi_len": 9, "ma_len": 50, "bb_mult": 2.6, "st_len": 7, "st_mult": 2.2},
    {"stoch_len": 21, "stoch_smooth": 5, "cci_len": 30, "linreg_len": 60, "structure_len": 8,
     "norm_smooth": 1},
]


def _theta(over: dict) -> np.ndarray:
    t = DEFAULTS.copy()
    for k, v in over.items():
        t[PARAM_NAMES.index(k)] = v
    return snap(t)


@pytest.mark.parametrize("step_minutes", [15, 240, 1440, 10080])   # 15m, 4h, daily, weekly
@pytest.mark.parametrize("over", CASES)
def test_kernel_matches_pandas(over, step_minutes):
    candles = synthetic_candles(2500, step_minutes=step_minutes, seed=3)
    ours = components_kernel(*candles.args(), _theta(over))
    theirs = TechnicalSentiment(**over).components(candles.frame())
    assert candles.use_vwap == ("vwap" in theirs)
    for j, name in enumerate(COMPONENTS):
        if name not in theirs:
            assert np.isnan(ours[:, j]).all()
            continue
        a, b = ours[:, j], theirs[name].to_numpy()
        assert (np.isnan(a) == np.isnan(b)).all(), f"{name}: warm-up differs"
        ok = ~np.isnan(a)
        np.testing.assert_allclose(a[ok], b[ok], rtol=0, atol=1e-6, err_msg=name)


# ---- behaviours matched to LuxAlgo's Market Sentiment Technicals (checked against a PineTS run) ----
def test_swings_follow_pines_tie_rule():
    """A swing may tie the bars to its left but must beat every bar to its right."""
    from backend.indicators.sentiment import _pine_pivots

    highs = np.array([1.0, 3.0, 3.0, 1.0, 0.5])
    assert _pine_pivots(highs, 1, top=True).tolist() == [False, False, True, False, False]
    lows = np.array([5.0, 2.0, 2.0, 5.0, 6.0])
    assert _pine_pivots(lows, 1, top=False).tolist() == [False, False, True, False, False]


def test_vwap_uses_close_and_first_bar_is_exact():
    """The session's first bar has one sample: both bands are the close itself, with no rounding."""
    from backend.indicators.sentiment import _anchored_vwap_bands

    idx = pd.date_range("2024-03-01 23:15", periods=6, freq="15min", tz="UTC")   # bar 3 is 00:00
    close = np.array([83083.99, 83100.5, 83090.1, 83083.99, 83120.7, 83111.3])   # bar 3 opens a new day
    df = pd.DataFrame({"open": close, "high": close + 5, "low": close - 5, "close": close,
                       "volume": [3.1, 7.7, 2.9, 4.4, 5.6, 1.3]}, index=idx)
    upper, lower = _anchored_vwap_bands(df, 2.0)
    assert idx[3].floor("D") != idx[2].floor("D")
    assert upper.iloc[3] == lower.iloc[3] == close[3]
    assert upper.iloc[0] == lower.iloc[0] == close[0]
    # a later bar: bands straddle the volume-weighted mean of the CLOSE
    v, p = df["volume"].to_numpy()[3:5], close[3:5]
    mean = (p * v).sum() / v.sum()
    sd = np.sqrt((p * p * v).sum() / v.sum() - mean * mean)
    assert upper.iloc[4] == pytest.approx(mean + 2 * sd) and lower.iloc[4] == pytest.approx(mean - 2 * sd)


def test_vwap_anchor_follows_the_timeframe():
    """LuxAlgo's Auto anchor: day (<=15m), week (intraday above), month (daily), quarter (weekly)."""
    from backend.indicators.sentiment import vwap_anchor_ids

    def changes(start, periods, freq):
        ids = vwap_anchor_ids(pd.date_range(start, periods=periods, freq=freq, tz="UTC"))
        return (np.flatnonzero(ids[1:] != ids[:-1]) + 1).tolist()

    assert changes("2024-03-03 22:30", 8, "15min") == [6]        # midnight, Sunday -> Monday
    assert changes("2024-03-03 12:00", 12, "4h") == [3]          # Monday 00:00 only, not Tuesday's
    assert changes("2024-01-29", 6, "D") == [3]                  # 1 February
    assert changes("2024-03-11", 6, "7D") == [3]                 # the week opening Monday 1 April


def test_missing_vwap_counts_as_a_neutral_50():
    """Without volume there is no VWAP; LuxAlgo averages in 50 for it instead of dropping it."""
    from backend.indicators.sentiment import COMPONENTS, TechnicalSentiment

    df = synthetic_candles(1500, seed=5).frame()
    df["volume"] = 0.0
    res = TechnicalSentiment().compute(df)
    assert "vwap" not in res.panes
    parts = [res.panes[n] for n in COMPONENTS if n in res.panes]
    assert len(parts) == 10
    expected = (sum(parts) + 50.0) / 11
    ok = res.panes["sentiment"].notna()
    assert ok.sum() > 300
    np.testing.assert_allclose(res.panes["sentiment"][ok], expected[ok], atol=1e-9)
