"""Alert dispatch with de-dupe / cooldown (plan sec 4.12).

Given candidate signals, suppresses ones that fired within the cooldown window
(tracked in the SignalJournal), sends the survivors via the notifier, and logs
them. This is what stops one wobbling signal from spamming.
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
        """Evaluate a preset filter and alert on newly-matched coins."""
        now = now if now is not None else time.time()
        coins = sorted(flt.evaluate(df))
        fired: list[SignalEntry] = []
        for coin in coins:
            entry = self._entry_for(df, coin, preset_name, base_for_strength, now)
            if self.journal.recently_fired(entry.dedup_key(), self.cooldown_s, now):
                continue
            text = self._format(entry, flt)
            self.notifier.send(text)
            self.journal.log(entry)
            fired.append(entry)
        return fired

    def _entry_for(self, df: pd.DataFrame, coin: str, preset: str,
                   base: str | None, now: float) -> SignalEntry:
        sub = df[(df["coin"] == coin) & (df["direction"] != rs.UNKNOWN)]
        if base:
            sub = sub[sub["base"] == base.upper()]
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
