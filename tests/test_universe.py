from backend.screener import universe
from .util import FakeAdapter, make_ohlcv, trend

FLOOR = 100_000  # USDT


def _adapter():
    """SOL: deep USDT book, dead native INR book. USDT/INR is liquid."""
    frames = {
        ("SOL", "USDT", "1h"): make_ohlcv(trend(50, 80, 0.01, seed=1), timeframe="1h"),
        ("SOL", "INR", "1h"): make_ohlcv(trend(50, 6640, 0.01, seed=2), timeframe="1h"),
        ("USDT", "INR", "1h"): make_ohlcv([83.0] * 50, timeframe="1h"),
        ("BTC", "USDT", "1h"): make_ohlcv(trend(50, 60000, 0.001, seed=3), timeframe="1h"),
    }
    volumes = {
        ("SOL", "USDT"): 50_000_000,   # $50M — liquid
        ("SOL", "INR"): 100.0,         # 100 INR/day — a dead book
        ("USDT", "INR"): 8_000_000_000,  # INR volume, liquid once converted
        ("BTC", "USDT"): 1_000_000_000,
    }
    prices = {
        ("SOL", "USDT"): 80.0,
        ("SOL", "INR"): 6640.0,
        ("USDT", "INR"): 83.0,         # 83 INR per USDT
        ("BTC", "USDT"): 60000.0,
    }
    return FakeAdapter(frames, volumes=volumes, prices=prices)


def test_native_dead_inr_book_is_gated():
    a = _adapter()
    # SOL is hugely liquid vs USDT ...
    assert universe.liquidity_ok(a, "SOL", "USDT", FLOOR) is True
    # ... but the native SOL/INR book (100 INR ~= 1.2 USDT) must be gated out
    assert universe.liquidity_ok(a, "SOL", "INR", FLOOR) is False


def test_synthesized_pair_checks_both_legs():
    a = _adapter()
    # SOL/BTC has no native market -> gate SOL/USDT and BTC/USDT legs (both deep)
    assert universe.liquidity_ok(a, "SOL", "BTC", FLOOR) is True


def test_synthesized_pair_fails_when_coin_leg_thin():
    frames = {("XYZ", "USDT", "1h"): make_ohlcv([1.0] * 50, timeframe="1h"),
              ("BTC", "USDT", "1h"): make_ohlcv([60000.0] * 50, timeframe="1h")}
    a = FakeAdapter(frames, volumes={("XYZ", "USDT"): 500.0,
                                     ("BTC", "USDT"): 1e9})
    assert universe.liquidity_ok(a, "XYZ", "BTC", FLOOR) is False


def test_zero_floor_disables_gate():
    a = _adapter()
    assert universe.liquidity_ok(a, "SOL", "INR", 0) is True
