import numpy as np
import pandas as pd

from backend.screener import liquidation as liq
from backend.screener import market_read as mr


def _klines(closes):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="1h", tz="UTC")
    c = np.asarray(closes, float)
    return pd.DataFrame({"open": c, "high": c * 1.001, "low": c * 0.999, "close": c},
                        index=idx)


def _oi(values):
    idx = pd.date_range("2026-01-01", periods=len(values), freq="1h", tz="UTC")
    return pd.DataFrame({"oi": 0.0, "oi_value": np.asarray(values, float)}, index=idx)


def _map(price, longs, shorts):
    """A LiqMap with clusters at the given {price: usd} levels."""
    prices = np.geomspace(price * 0.8, price * 1.2, 2001)
    lv, sv = np.zeros_like(prices), np.zeros_like(prices)
    for p, usd in longs.items():
        lv[np.abs(prices - p).argmin()] += usd
    for p, usd in shorts.items():
        sv[np.abs(prices - p).argmin()] += usd
    candles = _klines([price] * 3)
    return liq.LiqMap(candles=candles, prices=prices, heat=np.zeros((3, 2001)),
                      longs=lv, shorts=sv)


UPTREND = list(np.linspace(90, 100, 120))
DOWNTREND = list(np.linspace(110, 100, 120))


def test_uptrend_with_bigger_closer_longs_below_is_dip_then_up():
    m = _map(100, longs={98: 100e6}, shorts={104: 80e6})     # below pulls harder
    r = mr.read_coin("BTC", "BTCUSDT", _klines(UPTREND), _oi([1e9] * 30), 0.0001, m, m)
    assert r.trend_1h == mr.UP
    assert r.lean == mr.DIP_THEN_UP
    assert abs(r.below.dist_pct + 2) < 0.1 and abs(r.above.dist_pct - 4) < 0.1


def test_downtrend_with_pull_above_is_bounce_then_down():
    m = _map(100, longs={95: 20e6}, shorts={101: 30e6})
    r = mr.read_coin("ZEC", "ZECUSDT", _klines(DOWNTREND), _oi([1e9] * 30), 0.0001, m, m)
    assert r.lean == mr.BOUNCE_THEN_DOWN


def test_crowded_pump_with_long_liquidity_below_is_down():
    closes = UPTREND[:-24] + list(np.linspace(100, 112, 24))   # +12% in a day
    m = _map(112, longs={109: 60e6}, shorts={122: 20e6})
    heavy = _map(112, longs={109: 60e6, 100: 90e6}, shorts={122: 20e6})
    oi = [1e9] * 5 + list(np.linspace(1e9, 1.3e9, 25))        # +30% in 24h
    r = mr.read_coin("DOGE", "DOGEUSDT", _klines(closes), _oi(oi), 0.0001, m, heavy)
    assert r.lean == mr.DOWN
    assert any("leveraged longs" in x for x in r.reasons)


def test_small_map_caps_confidence_and_summary_counts():
    m = _map(100, longs={98: 1e6}, shorts={104: 1e6})
    r = mr.read_coin("XMR", "XMRUSDT", _klines(UPTREND), _oi([1e9] * 30), 0.0006, m, m)
    assert r.confidence == "Low"
    assert any("funding" in x for x in r.reasons)
    text = mr.market_summary([r])
    assert "XMR" in text and "of 1 coins" in text
