import numpy as np
import pandas as pd

from backend import trade_journal as tj

T0 = pd.Timestamp("2026-09-25 10:00", tz="UTC")
Q = 15 * 60_000


def _candles(rows, start=T0, minutes=15):
    """rows: (high, low, close) per candle."""
    idx = pd.date_range(start, periods=len(rows), freq=f"{minutes}min")
    return pd.DataFrame([{"open": c, "high": h, "low": l, "close": c, "volume": 1.0}
                         for h, l, c in rows], index=idx)


def _trade(**kw):
    base = dict(id=1, day="2026-09-25", list="test", coin="X", tf="15m", setup="Bull flag",
                entry_rule="now", trigger=np.nan, t1=np.nan, p1=np.nan, t2=np.nan, p2=np.nan,
                from_utc="2026-09-25 10:00", entry_price=100.0, stop=95.0, target=110.0)
    return tj.Trade(**{**base, **kw})


def _now(df):
    return int(df.index[-1].value // 1_000_000) + Q


def test_buy_now_hits_the_target():
    c = _candles([(101, 99, 100), (106, 100, 105), (111, 104, 108)])
    o = tj.replay(_trade(), c, c, _now(c))
    assert o.status == tj.TARGET and o.exit == 110 and round(o.pnl_pct, 6) == 10
    assert o.close_status == tj.TARGET


def test_a_wick_stops_the_trade_but_a_close_stop_keeps_it():
    # The second candle wicks to 94 but closes at 99; then price runs to 111.
    c = _candles([(101, 99, 100), (100, 94, 99), (111, 98, 109)])
    o = tj.replay(_trade(), c, c, _now(c))
    assert o.status == tj.STOPPED and o.exit == 95
    assert o.close_status == tj.TARGET and o.close_pnl_pct > 0
    assert round(o.best_pct, 6) == 11 and round(o.worst_pct, 6) == -6


def test_stop_and_target_in_one_candle_counts_as_the_stop():
    c = _candles([(112, 94, 100)])
    assert tj.replay(_trade(), c, c, _now(c)).status == tj.STOPPED


def test_close_above_waits_for_a_closed_candle():
    c = _candles([(101, 99, 100), (104, 100, 103), (106, 102, 104)])
    t = _trade(entry_rule="close_above", trigger=102.5, entry_price=np.nan)
    o = tj.replay(t, c, c, _now(c))
    assert o.status == tj.OPEN and o.entry == 103
    assert o.entry_ms == int(c.index[1].value // 1_000_000) + Q
    # While that candle is still forming, nothing has triggered.
    forming = tj.replay(t, c.iloc[:2], c.iloc[:2], int(c.index[1].value // 1_000_000) + 60_000)
    assert forming.status == tj.WAITING


def test_close_above_a_falling_line():
    t1 = int(T0.value // 1_000_000)
    # 110 at T0, falling 1 per candle: mid-candle 2 is 107.5, so a close at 108 breaks it.
    t = _trade(entry_rule="close_above", entry_price=np.nan, t1=t1, p1=110.0,
               t2=t1 + 10 * Q, p2=100.0, target=120.0)
    c = _candles([(109, 100, 105), (109, 104, 107), (109, 105, 108)])
    o = tj.replay(t, c, c, _now(c))
    assert o.entry == 108


def test_render_and_write_keep_the_notes(tmp_path):
    md = tmp_path / "j.md"
    md.write_text("# J\nmy notes\n<!-- AUTO:SUMMARY -->\nold\n<!-- /AUTO:SUMMARY -->\n"
                  "more notes\n<!-- AUTO:TRADES -->\n<!-- /AUTO:TRADES -->\n", encoding="utf-8")
    c = _candles([(101, 99, 100), (111, 100, 108)])
    trades = [_trade(), _trade(id=2, entry_rule="close_above", trigger=200.0,
                               entry_price=np.nan)]
    outs = [tj.replay(t, c, c, _now(c)) for t in trades]
    tj.write_markdown(md, tj.render(trades, outs, _now(c)))
    text = md.read_text(encoding="utf-8")
    assert "my notes" in text and "more notes" in text and "old" not in text
    assert "🎯 target" in text and "💤 not triggered" in text
    assert "**+10.00** (on $100)" in text


def test_load_reads_the_journal_csv():
    trades = tj.load("journal/trades.csv")
    assert trades and all(t.entry_rule in ("now", "close_above") for t in trades)
    assert len({t.id for t in trades}) == len(trades)
    for t in trades:
        if t.entry_rule == "now":
            assert np.isfinite(t.entry_price)
        else:
            assert np.isfinite(t.trigger) or np.isfinite(t.p2)
