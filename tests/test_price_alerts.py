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


def test_close_above_waits_for_a_closed_candle_of_its_timeframe():
    q = 15 * MIN
    idx = pd.to_datetime([T0, T0 + q], unit="ms", utc=True)
    c = pd.DataFrame({"open": [100, 101], "high": [106, 107], "low": [99, 100],
                      "close": [101, 105.5], "volume": [1, 1]}, index=idx)
    a = _alert(kind="price", condition="close_above", level=105, timeframe="15m",
               created_ms=T0 + 5 * MIN)
    assert a.describe() == "BTC closes above price 105.00 on a 15m close"
    # The wick to 106 in the first candle closed at 101: no. The second closes
    # at 105.5 but is still forming at T0 + 20 min: no.
    assert pa.evaluate(a, c, T0 + 20 * MIN) is None
    hit = pa.evaluate(a, c, T0 + 2 * q)
    assert hit[0] == c.index[1] and hit[1] == 105.5
    below = _alert(kind="price", condition="close_below", level=100.5, timeframe="15m")
    assert pa.evaluate(below, c, T0 + 2 * q) is None
    # Wick conditions keep 1-minute candles whatever timeframe is passed.
    assert _alert(kind="price", condition="above", level=1, timeframe="4h").timeframe == "1m"
    with pytest.raises(ValueError):
        _alert(kind="price", condition="close_above", level=1, timeframe="2h")


def test_check_all_fetches_each_timeframe_and_old_dbs_upgrade(tmp_path):
    import sqlite3
    path = tmp_path / "alerts.db"
    con = sqlite3.connect(path)          # the table as the previous version made it
    con.execute("CREATE TABLE alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT, "
                "symbol TEXT, kind TEXT, condition TEXT, level REAL, t1 REAL, p1 REAL, "
                "t2 REAL, p2 REAL, low REAL, high REAL, note TEXT, created_ms REAL, "
                "last_checked_ms REAL, status TEXT, triggered_ms REAL, trigger_price REAL)")
    con.execute("INSERT INTO alerts (coin, symbol, kind, condition, level, note, "
                "created_ms, status) VALUES ('BTC', 'BTCUSDT', 'price', 'above', 1e9, '', ?, "
                "'active')", (T0,))
    con.commit()
    con.close()
    store = pa.AlertStore(path)
    assert store.list()[0].timeframe == "1m"
    store.add(_alert(kind="price", condition="close_above", level=105, timeframe="15m"))
    asked = []

    def fetch(symbol, tf, n):
        asked.append(tf)
        q = 15 * MIN if tf == "15m" else MIN
        idx = pd.to_datetime([T0, T0 + q], unit="ms", utc=True)
        return pd.DataFrame({"open": 100, "high": 106, "low": 99, "close": [106, 100],
                             "volume": 1}, index=idx)

    fired = pa.check_all(store, fetch, now_ms=T0 + 30 * MIN)
    assert sorted(asked) == ["15m", "1m"]
    assert [a.timeframe for a in fired] == ["15m"]


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
