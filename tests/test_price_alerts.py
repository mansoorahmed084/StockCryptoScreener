import pandas as pd
import pytest

from backend.alerts import price_alerts as pa

T0 = int(pd.Timestamp("2026-09-22 10:00", tz="UTC").value // 1_000_000)   # ms
MIN = 60_000


def _candles(rows, start_ms=T0):
    """rows: (high, low, close) per minute from start_ms."""
    idx = pd.to_datetime([start_ms + i * MIN for i in range(len(rows))], unit="ms", utc=True)
    return pd.DataFrame([{"open": c, "high": h, "low": l, "close": c, "volume": 1.0}
                         for h, l, c in rows], index=idx)


def _alert(**kw):
    base = dict(coin="BTC", symbol="BTCUSDT", created_ms=T0)
    return pa.Alert(**{**base, **kw})


NOW = T0 + 10 * MIN


def test_price_above_below_and_touch_fire_on_wicks():
    c = _candles([(100, 99, 99.5), (101, 99, 100), (103.2, 100, 101)])
    hit = pa.evaluate(_alert(kind="price", condition="above", level=103), c, NOW)
    assert hit and hit[1] == 103 and hit[0] == c.index[2]          # a wick counts
    assert pa.evaluate(_alert(kind="price", condition="below", level=98), c, NOW) is None
    assert pa.evaluate(_alert(kind="price", condition="touch", level=100.5), c, NOW)[0] == c.index[1]


def test_line_touch_and_close_breaks():
    # A rising line: 100 at T0, +1 per minute (101.5 mid-candle 1, 102.5 mid-candle 2).
    line = dict(kind="line", t1=T0, p1=100.0, t2=T0 + 10 * MIN, p2=110.0)
    c = _candles([(99, 98, 98.5), (101.6, 99.5, 100.6), (104, 101, 103.8)])
    touch = pa.evaluate(_alert(condition="touch", **line), c, NOW)
    assert touch[0] == c.index[1]
    up = pa.evaluate(_alert(condition="break_up", **line), c, NOW)
    assert up[0] == c.index[2] and up[1] == 103.8                  # closed above 102.5
    # The same close in a candle that is still forming does not count.
    forming = pa.evaluate(_alert(condition="break_up", **line), c, T0 + 2 * MIN + 1000)
    assert forming is None


def test_zone_enter_and_validation():
    c = _candles([(100, 99, 99.5), (97.4, 95, 96)])
    hit = pa.evaluate(_alert(kind="zone", condition="enter", low=96.5, high=97.5), c, NOW)
    assert hit[0] == c.index[1]
    with pytest.raises(ValueError):
        _alert(kind="price", condition="break_up", level=1)
    with pytest.raises(ValueError):
        _alert(kind="line", condition="touch", t1=1, p1=1, t2=1, p2=2)


def test_candles_before_the_alert_was_set_are_ignored():
    c = _candles([(110, 99, 100), (101, 99, 100)])
    a = _alert(kind="price", condition="above", level=105, created_ms=T0 + MIN + 5000)
    assert pa.evaluate(a, c, NOW) is None
    assert pa.already_met(_alert(kind="price", condition="above", level=105), 106)


def test_store_check_all_fires_once_and_rearms(tmp_path):
    store = pa.AlertStore(tmp_path / "alerts.db")
    a_id = store.add(_alert(kind="price", condition="above", level=103, note="breakout"))
    store.add(_alert(kind="price", condition="below", level=90))
    c = _candles([(101, 99, 100), (104, 100, 103.5)])
    sent = []
    fired = pa.check_all(store, lambda s, tf, n: c, notify=lambda a: sent.append(pa.message(a)),
                         now_ms=NOW)
    assert [a.id for a in fired] == [a_id] and "breakout" in sent[0]
    assert "BTC goes above price 103" in sent[0]
    # A second checker sees nothing new: the alert was claimed once.
    assert pa.check_all(store, lambda s, tf, n: c, now_ms=NOW) == []
    assert len(store.list(pa.ACTIVE)) == 1 and len(store.list(pa.TRIGGERED)) == 1
    assert [a.id for a in store.fired_since(T0)] == [a_id]
    store.rearm(a_id)
    assert len(store.list(pa.ACTIVE)) == 2
    store.delete(a_id)
    assert len(store.list()) == 1
