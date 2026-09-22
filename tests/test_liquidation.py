import numpy as np
import pandas as pd

from backend.data.binance_futures import coin_of
from backend.screener import liquidation as liq


def _market(closes, oi_values, *, buy_share=0.5, spread=0.001):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="5min", tz="UTC")
    c = np.asarray(closes, dtype=float)
    candles = pd.DataFrame({
        "open": c, "high": c * (1 + spread), "low": c * (1 - spread), "close": c,
        "volume": 10.0, "quote_volume": c * 10.0,
        "taker_buy_quote": c * 10.0 * buy_share}, index=idx)
    oi = pd.DataFrame({"oi": 0.0, "oi_value": np.asarray(oi_values, float)}, index=idx)
    return candles, oi


def _one_leverage(lev=10):
    return liq.LiqParams(leverages={lev: 1.0}, mmr=0.0, bins=2000)


def test_new_oi_lands_at_the_leverage_liquidation_prices():
    candles, oi = _market([100.0] * 5, [1000, 2000, 2000, 2000, 2000], buy_share=0.75)
    m = liq.build(candles, oi, _one_leverage(10))
    # 1000 USDT opened at 100: 75% longs liquidate near 90, 25% shorts near 110
    assert np.isclose(m.longs.sum(), 750) and np.isclose(m.shorts.sum(), 250)
    assert abs(m.prices[m.longs.argmax()] - 90) < 0.1
    assert abs(m.prices[m.shorts.argmax()] - 110) < 0.1


def test_price_crossing_a_level_wipes_it():
    closes = [100.0, 100.0, 100.0, 89.0, 95.0]    # dips through the 90 long level
    candles, oi = _market(closes, [1000, 2000, 2000, 2000, 2000])
    m = liq.build(candles, oi, _one_leverage(10))
    assert m.longs.sum() == 0 and m.shorts.sum() > 0
    assert m.heat[1].sum() > m.heat[-1].sum()     # the heatmap shows it vanish


def test_falling_oi_shrinks_every_level():
    candles, oi = _market([100.0] * 4, [1000, 2000, 1000, 1000])
    m = liq.build(candles, oi, _one_leverage(10))
    assert np.isclose(m.longs.sum() + m.shorts.sum(), 500)   # half closed


def test_zones_pick_the_biggest_cluster_each_side():
    candles, oi = _market([100.0] * 6, [1000, 3000, 3000, 3000, 3000, 3000])
    m = liq.build(candles, oi, liq.LiqParams(leverages={10: 0.6, 25: 0.4},
                                             mmr=0.0, bins=2000))
    z = liq.zones(m, k=2)
    above = z[z["side"] == liq.SHORT]
    below = z[z["side"] == liq.LONG]
    assert abs(below["price"].iloc[0] - 90) < 0.2      # 10x holds the most
    assert abs(below["price"].iloc[1] - 96) < 0.2      # then 25x
    assert abs(above["price"].iloc[0] - 110) < 0.2
    assert (above["dist_pct"] > 0).all() and (below["dist_pct"] < 0).all()
    s = liq.summary(m)
    assert np.isclose(s["above_usd"] + s["below_usd"], 2000)


def test_coin_of_strips_contract_multipliers():
    assert coin_of("1000PEPE") == "PEPE" and coin_of("1MBABYDOGE") == "BABYDOGE"
    assert coin_of("BTC") == "BTC" and coin_of("1INCH") == "1INCH"
