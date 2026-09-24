import numpy as np
import pandas as pd

from backend.screener import patterns as pt


def _frame(mid, wick=0.3):
    mid = np.asarray(mid, float)
    idx = pd.date_range("2026-01-01", periods=len(mid), freq="1h", tz="UTC")
    op = np.concatenate([[mid[0]], mid[:-1]])
    return pd.DataFrame({"open": op, "high": np.maximum(op, mid) + wick,
                         "low": np.minimum(op, mid) - wick, "close": mid,
                         "volume": 1.0}, index=idx)


def _between(lower, upper, period=20):
    t = np.arange(len(lower))
    wave = 0.5 + 0.5 * np.sin(2 * np.pi * t / period)
    return lower + (upper - lower) * wave


def test_finds_the_ascending_triangle_and_its_lines():
    t = np.arange(200)
    df = _frame(_between(80 + 0.08 * t, np.full(200, 100.0)))
    a = pt.analyse(df, pivot=4)
    top, bottom = a.resistances[0], a.supports[0]
    assert abs(top.slope) < 0.01 and top.touches >= 4          # flat top at ~100
    assert abs(top.at(199) - 100.3) < 0.5
    assert bottom.slope > 0.05 and bottom.touches >= 4         # rising support
    p = a.patterns[0]
    assert p.name == "Ascending triangle" and p.bias == "bullish"
    assert p.status == "inside" and p.target_up > p.breakout_up
    top_level = [lv for lv in a.levels if lv.kind == pt.RESISTANCE][0]
    assert abs(top_level.price - 100.3) < 0.5 and top_level.touches >= 4


def test_finds_a_falling_channel():
    t = np.arange(200)
    lower = 100 - 0.1 * t
    df = _frame(_between(lower, lower + 10))
    names = [p.name for p in pt.analyse(df, pivot=4).patterns]
    assert "Falling channel" in names


def test_fibonacci_of_an_up_leg():
    df = _frame(np.concatenate([np.linspace(100, 50, 50), np.linspace(50, 150, 100),
                                np.linspace(150, 120, 30)]), wick=0.0)
    f = pt.fibonacci(df)
    assert f.direction == "up" and f.start == 50 and f.end == 150
    assert abs(f.levels[0.618] - (150 - 0.618 * 100)) < 1e-9
    assert abs(f.levels[1.618] - (50 + 1.618 * 100)) < 1e-9


def test_double_top_forming_then_confirmed():
    up = np.linspace(80, 100, 40)
    down = np.linspace(100, 90, 20)
    back = np.linspace(90, 100, 20)
    fade = np.linspace(100, 95, 15)
    df = _frame(np.concatenate([up, down, back, fade]), wick=0.05)
    pats = pt.double_top_bottom(df, pivot=4, tol=0.5)
    top = [p for p in pats if p.name == "Double top"][0]
    assert top.status == "forming" and abs(top.breakout_down - 89.95) < 0.2
    df2 = _frame(np.concatenate([up, down, back, np.linspace(100, 85, 25)]), wick=0.05)
    top2 = [p for p in pt.double_top_bottom(df2, pivot=4, tol=0.5)
            if p.name == "Double top"][0]
    assert top2.status == "confirmed" and top2.target_down < top2.breakout_down


def test_a_fresh_breakout_keeps_the_line_and_reports_it():
    t = np.arange(200)
    mid = _between(80 + 0.08 * t, np.full(200, 100.0))
    mid[-3:] = [101.5, 102.5, 103.0]                 # closes above the flat top
    a = pt.analyse(_frame(mid), pivot=4)
    top = a.resistances[0]
    assert top.broken and abs(top.slope) < 0.01
    p = a.patterns[0]
    assert p.name == "Ascending triangle" and p.status == "broke up"


def _ohlc(rows, freq="1D"):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx) \
        .assign(volume=1.0)


def _supply_then_crash(recover_to):
    rows = [(100, 101, 99, 100)] * 20                   # a flat base
    rows += [(100, 104, 99.5, 103)]                     # last up candle = supply
    rows += [(103, 103, 95, 96), (96, 96.5, 88, 89), (89, 90, 85, 86)]  # crash
    rows += [(86, 87, 85, 86.5)] * 10
    rows += [(86.5, recover_to + 0.5, 86, recover_to)]  # rally back
    return _ohlc(rows)


def test_order_block_marks_the_last_up_candle_before_a_crash():
    obs = pt.order_blocks(_supply_then_crash(98))
    sup = [ob for ob in obs if ob.kind == pt.SUPPLY]
    assert len(sup) == 1
    z = sup[0]
    assert (z.bottom, z.top) == (99.5, 104) and z.role == pt.RESISTANCE
    assert not z.broken and z.move_pct < -15 and "fresh" in z.label


def test_order_block_broken_by_a_close_flips_to_support():
    obs = pt.order_blocks(_supply_then_crash(106))
    z = [ob for ob in obs if ob.kind == pt.SUPPLY][0]
    assert z.broken and z.role == pt.SUPPORT and "flipped" in z.label


def test_scan_lists_the_triangle_with_the_daily_supply_above_it():
    from backend.screener import pattern_scan as ps
    t = np.arange(200)
    tri = _frame(_between(80 + 0.08 * t, np.full(200, 100.0)))
    daily = _supply_then_crash(98)
    daily[["open", "high", "low", "close"]] *= 1.0      # supply 99.5-104

    def fetch(symbol, tf, limit):
        return daily if tf == "1d" else tri

    out = ps.scan(fetch, {"AAA": "AAAUSDT"}, ["1h"], workers=1)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["pattern"] == "Ascending triangle" and row["timeframe"] == "1h"
    assert "99.5–104" in row["zone_above"]
    assert row["setup"].startswith(("Near breakout", "Forming"))
    # Patterns not asked for are left out
    assert ps.scan(fetch, {"AAA": "AAAUSDT"}, ["1h"], patterns=("Rising wedge",),
                   workers=1).empty


def test_price_action_reads_structure_and_labels_swings():
    t = np.arange(200)
    up = pt.price_action(_frame(_between(80 + 0.1 * t, 90 + 0.1 * t)), pivot=4)
    assert up.structure == "uptrend"
    assert {lab for _, _, lab in up.labels} <= {"HH", "HL"}
    down = pt.price_action(_frame(_between(100 - 0.1 * t, 110 - 0.1 * t)), pivot=4)
    assert down.structure == "downtrend"
    squeeze = pt.price_action(_frame(_between(80 + 0.08 * t, 120 - 0.08 * t)), pivot=4)
    assert squeeze.structure == "squeeze"


def test_price_action_sees_a_break_and_the_last_candle():
    t = np.arange(120)
    mid = list(_between(np.full(120, 90.0), np.full(120, 100.0)))
    df = _frame(mid + [101.0, 106.0, 106.2])       # a big up candle, then one forming
    pa = pt.price_action(df, pivot=4)
    text = " ".join(pa.notes)
    assert "bullish break of structure" in text
    assert "strong bullish body" in text


def test_equal_lows_inside_an_uptrend_are_not_a_double_bottom():
    # Rally, pull back to 90, rally, pull back to 90 again: a higher low
    # retested, with lower lows before it. That is continuation (the LTC case).
    rise = list(np.linspace(70, 95, 60))
    leg = list(np.linspace(95, 88, 10)) + list(np.linspace(88, 100, 15))
    test = list(np.linspace(100, 90, 12)) + list(np.linspace(90, 99, 12)) \
        + list(np.linspace(99, 90.1, 12)) + list(np.linspace(90.1, 96, 8))
    df = _frame(rise + leg + test, wick=0.05)
    assert not [p for p in pt.double_top_bottom(df, pivot=4, tol=0.5)
                if p.name == "Double bottom"]


def test_a_real_double_bottom_follows_a_fall():
    fall = list(np.linspace(120, 90, 40))
    w = list(np.linspace(90, 100, 20)) + list(np.linspace(100, 90.1, 20)) \
        + list(np.linspace(90.1, 96, 15))
    df = _frame(fall + w, wick=0.05)
    bottoms = [p for p in pt.double_top_bottom(df, pivot=4, tol=0.5)
               if p.name == "Double bottom"]
    assert bottoms and bottoms[0].status == "forming"
    assert abs(bottoms[0].breakout_up - 100.05) < 0.2


def test_a_retested_low_in_an_uptrend_still_reads_as_uptrend():
    rise = list(np.linspace(70, 95, 60))
    leg = list(np.linspace(95, 88, 10)) + list(np.linspace(88, 100, 15))
    test = list(np.linspace(100, 90, 12)) + list(np.linspace(90, 103, 14)) \
        + list(np.linspace(103, 89.95, 14)) + list(np.linspace(89.95, 98, 8))
    pa = pt.price_action(_frame(rise + leg + test, wick=0.05), pivot=4)
    assert pa.structure == "uptrend" and "held" in pa.notes[0]


def _pole_and_flag(n_flag=40, breakout=()):
    pole = list(np.linspace(80, 100, 40))
    t = np.arange(n_flag)
    upper = 100 - 0.12 * t
    wave = 0.5 + 0.5 * np.cos(2 * np.pi * t / 10)   # starts at the top, lower highs
    flag = list(upper - 3 + 3 * wave)
    return pole + flag + list(breakout)


def test_bull_flag_inside_then_broken():
    inside = [p for p in pt.analyse(_frame(_pole_and_flag(), wick=0.1), pivot=3).patterns
              if p.name == "Bull flag"]
    assert inside and inside[0].status == "inside"
    f = inside[0]
    assert f.upper.slope < 0 and f.upper.touches >= 2          # the falling line
    assert f.target_up > f.breakout_up > f.breakout_down        # target above, fail below
    broke = [p for p in pt.analyse(_frame(_pole_and_flag(breakout=(97, 98.5, 99)),
                                          wick=0.1), pivot=3).patterns
             if p.name == "Bull flag"]
    assert broke and broke[0].status == "broke up"


def test_bear_flag_is_the_mirror():
    df = _frame([200 - v for v in _pole_and_flag()], wick=0.1)
    bear = [p for p in pt.analyse(df, pivot=3).patterns if p.name == "Bear flag"]
    assert bear and bear[0].status == "inside" and bear[0].lower.slope > 0
    assert bear[0].target_down < bear[0].breakout_down < bear[0].breakout_up


def test_no_flag_without_a_pole():
    t = np.arange(80)
    flat = list(95 + 0.5 * np.sin(t / 3)) + list(95 - 0.05 * np.arange(40))
    assert not [p for p in pt.analyse(_frame(flat, wick=0.1), pivot=3).patterns
                if p.name == "Bull flag"]
