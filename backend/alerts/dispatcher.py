"""Alert dispatch on state changes, with de-dupe / cooldown (plan sec 4.12).

An alert fires only when a coin ENTERS a preset's match set (a state change since
the previous scan); a coin that stays matched scan after scan never re-fires.
The cooldown then only guards re-entries — a signal that wobbles out and back in
within the cooldown window is treated as noise and suppressed.
"""
from __future__ import annotations

import time

import pandas as pd

from backend.screener import rs
from backend.screener.filters import Filter
from backend.signals.journal import SignalEntry, SignalJournal
from .telegram import Notifier


class AlertDispatcher:
    def __init__(self, journal: SignalJournal, notifier: Notifier,
                 *, cooldown_s: float = 3600.0):
        self.journal = journal
        self.notifier = notifier
        self.cooldown_s = cooldown_s

    def dispatch_preset(self, df: pd.DataFrame, preset_name: str, flt: Filter,
                        *, base_for_strength: str | None = None,
                        now: float | None = None) -> list[SignalEntry]:
        """Evaluate a preset filter and alert on coins newly entering the match set."""
        now = now if now is not None else time.time()
        coins = sorted(flt.evaluate(df))
        previous = self.journal.matched_coins(preset_name)
        fired: list[SignalEntry] = []
        for coin in coins:
            if coin in previous:
                continue  # unchanged state -> no alert (plan sec 4.12)
            entry = self._entry_for(df, coin, preset_name, flt,
                                    base_for_strength, now)
            if self.journal.recently_fired(entry.dedup_key(), self.cooldown_s, now):
                continue  # re-entry within cooldown = wobble, suppress
            text = self._format(entry, flt)
            self.notifier.send(text)
            self.journal.log(entry)
            fired.append(entry)
        self.journal.record_matches(preset_name, set(coins), now=now)
        return fired

    def _entry_for(self, df: pd.DataFrame, coin: str, preset: str, flt: Filter,
                   base: str | None, now: float) -> SignalEntry:
        """Representative cell for the alert, chosen among the cells the filter
        actually tested (so the message never cites an unrelated base/timeframe)."""
        sub = df[(df["coin"] == coin) & (df["direction"] != rs.UNKNOWN)
                 & df["strength"].notna()]
        cells = flt.condition_cells()
        if cells and not sub.empty:
            in_cells = sub.apply(
                lambda r: (r["base"], r["timeframe"]) in cells, axis=1)
            if in_cells.any():
                sub = sub[in_cells]
        if base:
            scoped = sub[sub["base"] == base.upper()]
            if not scoped.empty:
                sub = scoped
        if not sub.empty:
            row = sub.loc[sub["strength"].abs().idxmax()]
            return SignalEntry(coin, row["base"], row["timeframe"], preset,
                               row["direction"], float(row["strength"]), now)
        return SignalEntry(coin, base or "", "", preset, "", float("nan"), now)

    @staticmethod
    def _format(entry: SignalEntry, flt: Filter) -> str:
        return (f"*{flt.name or entry.preset}*\n"
                f"{entry.coin} — {entry.direction} vs {entry.base} "
                f"@ {entry.timeframe} (strength {entry.strength:+.1f})")
