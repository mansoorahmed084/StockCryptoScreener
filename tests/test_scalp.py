import numpy as np
import pandas as pd

from backend.screener import scalp as sc

P = sc.Params(min_quote_volume=0)


def _frame(closes, vols, buy_share, spread=0.2):
    closes = np.asarray(closes, float)
    idx = pd.date_range("2026-10-01", periods=len(closes), freq="15min", tz="UTC")
    opens = np.r_[closes[0], closes[:-1]]
    high = np.maximum(opens, closes) + spread
    low = np.minimum(opens, closes) - spread
    qv = np.asarray(vols, float) * closes
    return pd.DataFrame({"open": opens, "high": high, "low": low, "close": closes,
                         "volume": vols, "quote_volume": qv,
                         "taker_buy_quote": qv * np.asarray(buy_share, float)}, index=idx)


def _pump_with_fading_second_push():
    """Flat, a strong push to 130 on heavy buying, a pullback, then a slow
    low-volume grind to a slightly higher high: momentum is fading."""
    rng = np.random.default_rng(0)
    c = list(100 + rng.normal(0, 0.05, 100))
    c += list(np.linspace(101.5, 130, 20))          # strong push
    c += list(np.linspace(129.4, 124, 10))          # pullback
    c += list(np.linspace(124.3, 131, 30))          # slow grind to a higher high
    c += [130.6, 130.55, 130.5]                     # two closed dips + the forming candle
    v = [500] * 100 + [1000] * 20 + [400] * 10 + [300] * 30 + [300] * 3
    b = [0.5] * 100 + [0.7] * 20 + [0.45] * 10 + [0.45] * 30 + [0.45] * 3
    return _frame(c, v, b)


def test_a_fading_pump_is_a_short_scalp():
    s = sc.evaluate(_pump_with_fading_second_push(), tf="15m", funding=0.0005, p=P)
    assert s is not None and s.side == "short"
    for check in ("rsi_div", "vol_fade", "cvd_fade", "rsi_ext", "crowded"):
        assert check in s.checks, s.checks
    assert s.score >= 5 and s.move_pct > 25
    assert s.stop > s.extreme > s.price > s.t1 > s.t2
    assert s.rr2 > 1.5


def test_the_mirror_is_a_long_scalp():
    df = _pump_with_fading_second_push()
    m = df.copy()
    m["close"], m["open"] = 260 - df["close"], 260 - df["open"]
    m["high"], m["low"] = 260 - df["low"], 260 - df["high"]
    m["quote_volume"] = m["volume"] * m["close"]
    m["taker_buy_quote"] = m["quote_volume"] * (1 - df["taker_buy_quote"] / df["quote_volume"])
    s = sc.evaluate(m, tf="15m", funding=-0.0005, p=P)
    assert s is not None and s.side == "long"
    assert {"rsi_div", "vol_fade", "cvd_fade", "crowded"} <= set(s.checks)
    assert s.stop < s.extreme < s.price < s.t1 < s.t2


def test_funding_against_the_trade_costs_a_point():
    df = _pump_with_fading_second_push()
    with_crowd = sc.evaluate(df, tf="15m", funding=0.0005, p=P)
    squeeze = sc.evaluate(df, tf="15m", funding=-0.0005, p=P)
    assert squeeze is not None and squeeze.score == with_crowd.score - 2
    assert "crowded" not in squeeze.checks


def test_a_clean_trend_without_fading_is_skipped():
    c = list(np.full(100, 100.0)) + list(np.linspace(100.5, 140, 70))
    df = _frame(c, [500] * 100 + list(np.linspace(600, 1500, 70)), [0.5] * 100 + [0.65] * 70)
    assert sc.evaluate(df, tf="15m", p=P) is None


def test_a_move_that_already_reversed_is_skipped():
    df = _pump_with_fading_second_push()
    c = list(df["close"]) + list(np.linspace(129, 118, 8))
    late = _frame(c, list(df["volume"]) + [400] * 8, list(df["taker_buy_quote"] / df["quote_volume"]) + [0.4] * 8)
    assert sc.evaluate(late, tf="15m", funding=0.0005, p=P) is None


def test_scan_ranks_and_fills_coin_names():
    good = _pump_with_fading_second_push()
    flat = _frame(np.full(170, 100.0), [500] * 170, [0.5] * 170)
    frames = {"AUSDT": good, "BUSDT": flat}
    out = sc.scan(lambda sym, tf, n: frames[sym] if tf == "15m" else frames[sym].iloc[::4],
                  {"A": "AUSDT", "B": "BUSDT"}, funding={"AUSDT": 0.0005}, p=P,
                  open_interest=lambda sym: 12.5)
    assert [s.coin for s in out] == ["A"] and out[0].oi_24h_pct == 12.5
