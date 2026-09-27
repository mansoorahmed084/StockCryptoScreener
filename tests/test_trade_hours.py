from datetime import datetime, timezone

import pandas as pd

from backend.screener import trade_hours as th


def _klines(busy_utc: set[int], days: int = 14) -> pd.DataFrame:
    idx = pd.date_range("2026-09-07", periods=days * 24 + 1, freq="h", tz="UTC")
    vol = [300.0 if ts.hour in busy_utc else 100.0 for ts in idx]
    return pd.DataFrame({"quote_volume": vol}, index=idx)


def test_busy_hours_are_good_and_labelled_in_ist():
    slots = th.hour_profile(_klines({13, 14}))
    good = [s for s in slots if s.good]
    assert [s.utc_hour for s in good] == [13, 14]
    assert [(s.ist_start, s.ist_end) for s in good] == [("18:30", "19:30"),
                                                        ("19:30", "20:30")]
    assert th.good_windows(slots) == [("18:30", "20:30")]


def test_slots_are_ordered_by_ist_time():
    slots = th.hour_profile(_klines({13}))
    assert len(slots) == 24
    assert slots[0].ist_start == "00:30" and slots[-1].ist_start == "23:30"


def test_weekends_are_ignored():
    df = _klines(set())
    weekend = df.index.dayofweek >= 5
    df.loc[weekend & (df.index.hour == 3), "quote_volume"] = 10_000.0
    assert not any(s.good for s in th.hour_profile(df))


def test_current_and_next_good_slot():
    slots = th.hour_profile(_klines({13, 14}))
    now = datetime(2026, 9, 28, 10, 15, tzinfo=timezone.utc)   # 15:45 IST
    assert th.current_slot(slots, now).ist_start == "15:30"
    assert th.next_good(slots, now).ist_start == "18:30"


def test_window_across_ist_midnight_is_one_window():
    slots = th.hour_profile(_klines({18, 19}))   # 23:30-01:30 IST
    assert th.good_windows(slots) == [("23:30", "01:30")]


def test_fallback_profile_has_the_overlap_hours():
    slots = th.fallback_profile()
    assert ("17:30", "23:30") in th.good_windows(slots)
