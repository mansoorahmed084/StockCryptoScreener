import numpy as np
import pandas as pd

from backend.config import load_config
from backend.data.ohlcv import OHLCVService
from backend.data.pairs import RatioBuilder
from backend.indicators.base import IndicatorResult, Marker
from backend.screener import confluence
from .util import FakeAdapter, make_ohlcv, trend

TFS = ("1h", "4h")  # 4h is resampled from the 1h frames


def _builder(frames):
    config = load_config()
    adapter = FakeAdapter(frames)
    service = OHLCVService(adapter, config, cache_ttl=0)
    return RatioBuilder(service, config, universe_coins=["SOL", "DOGE"]), config


def _frames():
    # SOL rising strongly vs USDT, DOGE falling; 500 x 1h candles so the
    # resampled 4h series still has enough rows to classify.
    return {
        ("SOL", "USDT", "1h"): make_ohlcv(
            trend(500, 100, 0.01, noise=0.002, seed=1), timeframe="1h"),
        ("DOGE", "USDT", "1h"): make_ohlcv(
            trend(500, 100, -0.01, noise=0.002, seed=2), timeframe="1h"),
    }


class BullDivStub:
    """Indicator stub: always reports a bull divergence two candles ago."""

    def compute(self, df: pd.DataFrame) -> IndicatorResult:
        res = IndicatorResult()
        if len(df) >= 2:
            ts = df.index[-2]
            res.markers = [Marker(ts, "bull_div", float(df["close"].iloc[-2]))]
        return res


class NoDivStub:
    def compute(self, df: pd.DataFrame) -> IndicatorResult:
        return IndicatorResult()


def _params(**kw):
    defaults = dict(base="USDT", timeframes=TFS, div_lookback=5,
                    liquidity_gate=False)
    defaults.update(kw)
    return confluence.ConfluenceParams(**defaults)


def test_all_bull_flag_and_ranking():
    builder, config = _builder(_frames())
    df = confluence.build_report(builder, config, ["SOL", "DOGE"], _params(),
                                 indicator_factory=NoDivStub)
    sol = df[df["coin"] == "SOL"].iloc[0]
    doge = df[df["coin"] == "DOGE"].iloc[0]
    assert sol["all_bull"] and sol["bull_tf_count"] == len(TFS)
    assert not doge["all_bull"] and doge["bull_tf_count"] == 0
    # SOL must rank above DOGE
    assert df.index[df["coin"] == "SOL"][0] < df.index[df["coin"] == "DOGE"][0]


def test_multi_tf_divergence_flagged():
    builder, config = _builder(_frames())
    df = confluence.build_report(builder, config, ["SOL"], _params(),
                                 indicator_factory=BullDivStub)
    sol = df.iloc[0]
    assert sol["multi_tf_bull_div"]                # div on both timeframes
    assert sol["bull_div_tfs"] == ",".join(TFS)
    for tf in TFS:
        assert sol[f"div_{tf}"] == confluence.DIV_BULL


def test_div_outside_lookback_ignored():
    builder, config = _builder(_frames())
    df = confluence.build_report(builder, config, ["SOL"],
                                 _params(div_lookback=1),   # marker sits at -2
                                 indicator_factory=BullDivStub)
    sol = df.iloc[0]
    assert not sol["multi_tf_bull_div"]
    assert sol["bull_div_tfs"] == ""


def test_require_all_bull_filters_rows():
    builder, config = _builder(_frames())
    df = confluence.build_report(builder, config, ["SOL", "DOGE"],
                                 _params(require_all_bull=True),
                                 indicator_factory=NoDivStub)
    assert df["coin"].tolist() == ["SOL"]


def test_unknown_when_no_data():
    builder, config = _builder(_frames())
    df = confluence.build_report(builder, config, ["XRP"], _params(),
                                 indicator_factory=NoDivStub)
    xrp = df.iloc[0]
    assert xrp["known_tf_count"] == 0
    assert not xrp["all_bull"]
    for tf in TFS:
        assert xrp[f"dir_{tf}"] == "unknown"
