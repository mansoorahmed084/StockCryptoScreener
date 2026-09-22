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
