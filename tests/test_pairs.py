import numpy as np
import pandas as pd

from backend.config import load_config
from backend.data.ohlcv import OHLCVService
from backend.data.pairs import RatioBuilder
from .util import FakeAdapter, make_ohlcv, trend


def _service(frames, volumes=None):
    config = load_config()
    adapter = FakeAdapter(frames, volumes=volumes)
    return OHLCVService(adapter, config, cache_ttl=0), config


def test_direct_pair_used_when_available():
    sol_btc = make_ohlcv(trend(100, 0.01, 0.001, seed=1), timeframe="1h")
    frames = {("SOL", "BTC", "1h"): sol_btc}
    service, config = _service(frames)
    builder = RatioBuilder(service, config, universe_coins=["SOL", "BTC"])
    res = builder.ratio("SOL", "BTC", "1h")
    assert res.method == "direct"
    assert res.synthetic is False
    assert len(res.frame) == 100


def test_synthesised_divide_ratio():
    sol = make_ohlcv(trend(120, 100, 0.02, seed=1), timeframe="1h")   # rising fast
    btc = make_ohlcv(trend(120, 100, 0.005, seed=2), timeframe="1h")  # rising slow
    frames = {("SOL", "USDT", "1h"): sol, ("BTC", "USDT", "1h"): btc}
    service, config = _service(frames)
    builder = RatioBuilder(service, config, universe_coins=["SOL", "BTC"])
    res = builder.ratio("SOL", "BTC", "1h")
    assert res.method == "divide"
    assert res.synthetic is True
    # ratio close equals sol/btc elementwise
    expected = (sol["close"] / btc["close"])
    np.testing.assert_allclose(res.close.to_numpy(), expected.to_numpy(), rtol=1e-9)
    # SOL outpacing BTC -> ratio trends up
    assert res.close.iloc[-1] > res.close.iloc[0]


def test_inr_multiply_synthesis():
    sol_usdt = make_ohlcv(trend(120, 100, 0.01, seed=1), timeframe="1h")
    usdt_inr = make_ohlcv([83.0] * 120, timeframe="1h")
    frames = {("SOL", "USDT", "1h"): sol_usdt, ("USDT", "INR", "1h"): usdt_inr}
    service, config = _service(frames)
    builder = RatioBuilder(service, config, universe_coins=["SOL"])
    res = builder.ratio("SOL", "INR", "1h")
    assert res.method == "multiply"
    np.testing.assert_allclose(
        res.close.to_numpy(),
        (sol_usdt["close"] * usdt_inr["close"]).to_numpy(), rtol=1e-9)


def test_identity_when_coin_equals_base():
    service, config = _service({})
    builder = RatioBuilder(service, config)
    res = builder.ratio("BTC", "BTC", "1h")
    assert res.method == "identity"
    assert res.frame.empty


def test_index_rebased_at_common_window_start():
    # AAA has 300 candles (tripled since its start); BBB has only 100 flat ones.
    # The index must rebase at the COMMON window start, i.e. begin at 1.0 —
    # rebasing each member at its own first candle would start it at ~1.7.
    frames = {
        ("AAA", "USDT", "1h"): make_ohlcv(list(np.linspace(100, 300, 300)),
                                          timeframe="1h"),
        ("BBB", "USDT", "1h"): make_ohlcv([50.0] * 100, timeframe="1h"),
    }
    service, config = _service(frames)
    builder = RatioBuilder(service, config, universe_coins=["AAA", "BBB"])
    lvl = builder.index_level("1h")
    assert abs(lvl.iloc[0] - 1.0) < 1e-9


def test_index_base_equal_weight():
    frames = {
        ("SOL", "USDT", "1h"): make_ohlcv(trend(120, 100, 0.02, seed=1), timeframe="1h"),
        ("ETH", "USDT", "1h"): make_ohlcv(trend(120, 100, 0.005, seed=2), timeframe="1h"),
        ("BNB", "USDT", "1h"): make_ohlcv(trend(120, 100, 0.005, seed=3), timeframe="1h"),
    }
    service, config = _service(frames)
    builder = RatioBuilder(service, config, universe_coins=["SOL", "ETH", "BNB"])
    res = builder.ratio("SOL", "INDEX", "1h")
    assert res.method == "index"
    assert not res.frame.empty
    # SOL is the strongest -> SOL/INDEX rises
    assert res.close.iloc[-1] > res.close.iloc[0]
