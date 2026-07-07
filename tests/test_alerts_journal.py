from backend.alerts.dispatcher import AlertDispatcher
from backend.alerts.telegram import NullNotifier
from backend.screener import filters
from backend.signals.journal import SignalEntry, SignalJournal
from .util import matrix_df


class RecordingNotifier(NullNotifier):
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return True


def test_journal_log_and_cooldown(tmp_path):
    j = SignalJournal(tmp_path / "sig.db")
    e = SignalEntry("SOL", "BTC", "1d", "full_stack_bull", "bull", 1.5, 1000.0)
    assert j.recently_fired(e.dedup_key(), 3600, now=1000.0) is False
    j.log(e)
    assert j.recently_fired(e.dedup_key(), 3600, now=1500.0) is True    # within cooldown
    assert j.recently_fired(e.dedup_key(), 3600, now=5000.0) is False   # cooled down
    assert len(j.to_frame()) == 1
    j.close()


def _bull_matrix():
    rows = []
    for tf in ("1h", "4h", "1d", "1w"):
        rows.append({"coin": "SOL", "base": "BTC", "timeframe": tf,
                     "direction": "bull", "strength": 1.6, "rank": 95})
    return matrix_df(rows)


def test_dispatch_fires_once_then_cooldown(tmp_path):
    j = SignalJournal(tmp_path / "sig.db")
    notifier = RecordingNotifier()
    disp = AlertDispatcher(j, notifier, cooldown_s=3600)
    flt = filters.full_stack_bull("BTC", timeframes=("1h", "4h", "1d", "1w"))

    fired1 = disp.dispatch_preset(_bull_matrix(), "full_stack_bull", flt, now=1000.0)
    assert [e.coin for e in fired1] == ["SOL"]
    assert len(notifier.sent) == 1

    # within cooldown -> suppressed
    fired2 = disp.dispatch_preset(_bull_matrix(), "full_stack_bull", flt, now=1500.0)
    assert fired2 == []
    assert len(notifier.sent) == 1
    j.close()
