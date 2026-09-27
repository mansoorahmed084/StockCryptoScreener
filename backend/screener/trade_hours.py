"""When to trade: the hours of the day with the most liquidity, in IST.

Liquidity is measured as the median quote volume of BTCUSDT perpetual 1h
candles at each hour of the day, over the last ~6 weeks of weekdays. An hour is
"good" when its median volume is at least ``GOOD_RATIO`` times the average hour.
Binance candles open on the UTC hour, so every IST slot starts at :30.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))
GOOD_RATIO = 1.1

# Used when Binance cannot be reached: the London-open and London/New York
# overlap hours, as UTC candle-open hours.
FALLBACK_GOOD_UTC = frozenset({8, 12, 13, 14, 15, 16, 17})


@dataclass(frozen=True)
class HourSlot:
    utc_hour: int
    ratio: float | None      # median volume / average hour; None = fallback
    good: bool

    @property
    def ist_start(self) -> str:
        return _ist_label(self.utc_hour)

    @property
    def ist_end(self) -> str:
        return _ist_label((self.utc_hour + 1) % 24)


def _ist_label(utc_hour: int) -> str:
    t = datetime(2000, 1, 1, utc_hour, tzinfo=timezone.utc).astimezone(IST)
    return t.strftime("%H:%M")


def hour_profile(klines: pd.DataFrame, *, weekdays_only: bool = True,
                 good_ratio: float = GOOD_RATIO) -> list[HourSlot]:
    """24 slots ordered by IST start time (00:30 first). ``klines`` needs a
    UTC DatetimeIndex and a ``quote_volume`` column; the last row is dropped
    as the still-forming candle."""
    df = klines.iloc[:-1]
    if weekdays_only:
        df = df[df.index.dayofweek < 5]
    if df.empty:
        return fallback_profile()
    med = df.groupby(df.index.hour)["quote_volume"].median()
    med = med.reindex(range(24))
    ratio = med / med.mean()
    slots = [HourSlot(h, None if pd.isna(ratio[h]) else float(ratio[h]),
                      bool(ratio[h] >= good_ratio)) for h in range(24)]
    return _by_ist(slots)


def fallback_profile() -> list[HourSlot]:
    return _by_ist([HourSlot(h, None, h in FALLBACK_GOOD_UTC) for h in range(24)])


def _by_ist(slots: list[HourSlot]) -> list[HourSlot]:
    return sorted(slots, key=lambda s: s.ist_start)


def current_slot(slots: list[HourSlot], now: datetime | None = None) -> HourSlot:
    now = now or datetime.now(timezone.utc)
    hour = now.astimezone(timezone.utc).hour
    return next(s for s in slots if s.utc_hour == hour)


def next_good(slots: list[HourSlot], now: datetime | None = None) -> HourSlot | None:
    """The first good slot that starts after the current one."""
    now = now or datetime.now(timezone.utc)
    hour = now.astimezone(timezone.utc).hour
    by_utc = {s.utc_hour: s for s in slots}
    for step in range(1, 25):
        s = by_utc[(hour + step) % 24]
        if s.good:
            return s
    return None


def good_windows(slots: list[HourSlot]) -> list[tuple[str, str]]:
    """Runs of consecutive good hours as (IST start, IST end), in time order.
    A run that crosses IST midnight is joined into one window."""
    by_utc = {s.utc_hour: s for s in slots}
    starts = [h for h in range(24)
              if by_utc[h].good and not by_utc[(h - 1) % 24].good]
    out = []
    for h in starts:
        end = h
        while by_utc[(end + 1) % 24].good and (end + 1) % 24 != h:
            end = (end + 1) % 24
        out.append((by_utc[h].ist_start, by_utc[end].ist_end))
    return sorted(out)
