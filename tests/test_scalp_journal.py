from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backend import scalp_journal as sj

T0 = pd.Timestamp("2026-10-06 10:00", tz="UTC")
Q = 15 * 60_000


def _candles(rows):
    """rows: (high, low, close) per 15m candle from T0."""
    idx = pd.date_range(T0, periods=len(rows), freq="15min")
    return pd.DataFrame([{"open": c, "high": h, "low": l, "close": c, "volume": 1.0}
                         for h, l, c in rows], index=idx)


def _call(**kw):
    base = dict(id=1, time_utc=T0.strftime("%Y-%m-%d %H:%M"), coin="X", symbol="XUSDT",
                tf="15m", side="short", status="armed", price=101.0, trigger=100.0,
                stop=104.0, t1=98.0, t2=95.0, t3=94.0, score=4, checks="rsi_div wt_div")
    return sj.Call(**{**base, **kw})


def _end(df):
    return int(df.index[-1].value // 1_000_000) + Q


def _replay(call, df, now=None):
    return sj.replay(call, df, df, now if now is not None else _end(df), Q)


def test_armed_short_triggers_then_reaches_t1_and_t2():
    df = _candles([(102, 100.5, 101), (101.5, 99.5, 99.8), (100.2, 97.5, 98), (98.5, 94.8, 95.2)])
    r = _replay(_call(), df)
    assert r.status == sj.TARGET and r.t1_hit and r.entry == 99.8
    risk = 104 - 99.8
    assert r.r == pytest.approx(0.5 * (99.8 - 98) / risk + 0.5 * (99.8 - 95) / risk)


def test_triggered_long_hits_its_stop():
    df = _candles([(50.5, 49.5, 50), (50.2, 47.9, 48.5)])
    c = _call(side="long", status="triggered", price=50.0, trigger=50.0, stop=48.0,
              t1=52.0, t2=55.0)
    r = _replay(c, df)
    assert r.status == sj.STOPPED and r.r == -1.0 and r.mae <= -1


def test_t1_then_back_to_break_even():
    df = _candles([(101.5, 99.5, 99.8), (100.0, 97.9, 98.2), (100.1, 98.0, 100.0)])
    r = _replay(_call(status="triggered", price=99.8), df)
    assert r.status == sj.BREAKEVEN and r.r == pytest.approx(0.5 * (99.8 - 98) / 4.2)


def test_an_armed_call_that_never_triggers_expires():
    df = _candles([(101.5, 100.4, 101)] * 6)
    assert _replay(_call(), df).status == sj.EXPIRED
    assert _replay(_call(), df.iloc[:2], now=_end(df.iloc[:2])).status == sj.WAITING


def test_the_stop_before_the_trigger_makes_the_call_invalid():
    df = _candles([(105, 100.5, 101), (101, 98.5, 99)])
    assert _replay(_call(), df).status == sj.INVALID


def test_time_stop_closes_a_scalp_that_goes_nowhere():
    df = _candles([(100.6, 99.4, 100.0 - i * 0.05) for i in range(10)])
    r = _replay(_call(status="triggered", price=100.0), df)
    assert r.status == sj.TIMED and not r.t1_hit
    assert r.exit_ms == int(df.index[7].value // 1_000_000)
    assert r.r == pytest.approx((100.0 - df["close"].iloc[7]) / 4.0)


def test_render_write_and_load(tmp_path):
    csv = tmp_path / "scalps.csv"
    setup = SimpleNamespace(coin="X", symbol="XUSDT", side="short", status="armed", price=101.0,
                            trigger=100.0, stop=104.0, t1=98.0, t2=95.0, t3=94.0, score=4,
                            checks=["rsi_div", "wt_div"], move_pct=12.3, funding_pct=0.01)
    rows = sj.rows_from_setups([setup], first_id=1, when_utc=T0.strftime("%Y-%m-%d %H:%M"),
                               tf="15m")
    pd.DataFrame(rows)[sj.COLUMNS].to_csv(csv, index=False)
    calls = sj.load(csv)
    assert calls[0].checks == "rsi_div wt_div" and calls[0].side == "short"
    df = _candles([(102, 100.5, 101), (101.5, 99.5, 99.8), (100.2, 97.5, 98), (98.5, 94.8, 95.2)])
    results = [_replay(c, df) for c in calls]
    md = tmp_path / "j.md"
    md.write_text("notes\n<!-- AUTO:SUMMARY -->\n<!-- /AUTO:SUMMARY -->\nmore\n"
                  "<!-- AUTO:TRADES -->\nold\n<!-- /AUTO:TRADES -->\n", encoding="utf-8")
    sj.write_markdown(md, sj.render(calls, results, _end(df)))
    text = md.read_text(encoding="utf-8")
    assert "notes" in text and "more" in text and "old" not in text
    assert "🎯 T1 + T2" in text and "Shorts" in text and "Score 4" in text


def test_an_empty_journal_renders(tmp_path):
    csv = tmp_path / "scalps.csv"
    csv.write_text(",".join(sj.COLUMNS) + "\n", encoding="utf-8")
    calls = sj.load(csv)
    assert calls == []
    blocks = sj.render(calls, [], 0)
    assert "**All** | 0 | 0" in blocks["SUMMARY"]
