import pandas as pd

from backend.config import load_config
from backend.data.ohlcv import OHLCVService
from backend.data.pairs import RatioBuilder
from backend.screener import matrix as matrix_mod
from .util import FakeAdapter, make_ohlcv, trend


def _builder(frames, volumes=None):
    config = load_config()
    adapter = FakeAdapter(frames, volumes=volumes)
    service = OHLCVService(adapter, config, cache_ttl=0)
    return RatioBuilder(service, config, universe_coins=["SOL", "BTC"]), config


def test_matrix_has_expected_shape_and_ranks():
    frames = {
        ("SOL", "USDT", "1h"): make_ohlcv(
            trend(200, 100, 0.01, noise=0.001, seed=1), timeframe="1h"),
        ("BTC", "USDT", "1h"): make_ohlcv(
            trend(200, 100, 0.001, noise=0.001, seed=2), timeframe="1h"),
    }
    builder, config = _builder(frames)
    df = matrix_mod.build_matrix(builder, config, ["SOL", "BTC"], ["USDT"], ["1h"],
                                 apply_liquidity_gate=False)
    # one row per (coin, base, tf); SOL/USDT and BTC/USDT
    assert set(df["coin"]) == {"SOL", "BTC"}
    assert (df["timeframe"] == "1h").all()
    # SOL rising fast vs USDT -> bull
    sol = df[df["coin"] == "SOL"].iloc[0]
    assert sol["direction"] == "bull"
    # ranks populated for known cells
    assert df.loc[df["direction"] != "unknown", "rank"].notna().all()


def test_liquidity_gate_marks_unknown():
    frames = {
        ("SOL", "USDT", "1h"): make_ohlcv(
            trend(200, 100, 0.01, noise=0.001, seed=1), timeframe="1h"),
    }
    # SOL USDT volume below the (default) threshold -> gated out
    builder, config = _builder(frames, volumes={("SOL", "USDT"): 1.0})
    df = matrix_mod.build_matrix(builder, config, ["SOL"], ["USDT"], ["1h"],
                                 apply_liquidity_gate=True)
    assert (df["direction"] == "unknown").all()
    assert (df["quality_reason"] == "illiquid").all()
