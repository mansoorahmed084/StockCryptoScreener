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
