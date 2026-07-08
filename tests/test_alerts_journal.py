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


def test_journal_preset_state_roundtrip(tmp_path):
    j = SignalJournal(tmp_path / "sig.db")
    assert j.matched_coins("p") == set()
    j.record_matches("p", {"SOL", "ETH"}, now=1000.0)
    assert j.matched_coins("p") == {"SOL", "ETH"}
    j.record_matches("p", {"SOL"}, now=2000.0)  # ETH dropped out
    assert j.matched_coins("p") == {"SOL"}
    j.close()


def _bull_matrix():
    rows = []
    for tf in ("1h", "4h", "1d", "1w"):
        rows.append({"coin": "SOL", "base": "BTC", "timeframe": tf,
                     "direction": "bull", "strength": 1.6, "rank": 95})
    return matrix_df(rows)


def _empty_matrix():
    return matrix_df([])


def test_dispatch_fires_only_on_state_change(tmp_path):
    j = SignalJournal(tmp_path / "sig.db")
    notifier = RecordingNotifier()
    disp = AlertDispatcher(j, notifier, cooldown_s=3600)
    flt = filters.full_stack_bull("BTC", timeframes=("1h", "4h", "1d", "1w"))

    # first scan: SOL enters the match set -> fires
    fired1 = disp.dispatch_preset(_bull_matrix(), "full_stack_bull", flt, now=1000.0)
    assert [e.coin for e in fired1] == ["SOL"]
    assert len(notifier.sent) == 1

    # unchanged state -> never re-fires, even after the cooldown has expired
    fired2 = disp.dispatch_preset(_bull_matrix(), "full_stack_bull", flt, now=9000.0)
    assert fired2 == []
    assert len(notifier.sent) == 1
    j.close()


def test_dispatch_reentry_cooldown(tmp_path):
    j = SignalJournal(tmp_path / "sig.db")
    notifier = RecordingNotifier()
    disp = AlertDispatcher(j, notifier, cooldown_s=3600)
    flt = filters.full_stack_bull("BTC", timeframes=("1h", "4h", "1d", "1w"))

    disp.dispatch_preset(_bull_matrix(), "full_stack_bull", flt, now=1000.0)
    disp.dispatch_preset(_empty_matrix(), "full_stack_bull", flt, now=1200.0)  # exits

    # wobbles back in within cooldown -> suppressed as noise
    fired = disp.dispatch_preset(_bull_matrix(), "full_stack_bull", flt, now=1500.0)
    assert fired == []

    # drops out again, then a genuine re-entry after cooldown -> fires again
    disp.dispatch_preset(_empty_matrix(), "full_stack_bull", flt, now=2000.0)
    fired = disp.dispatch_preset(_bull_matrix(), "full_stack_bull", flt, now=9000.0)
    assert [e.coin for e in fired] == ["SOL"]
    assert len(notifier.sent) == 2
    j.close()


def test_alert_cites_a_cell_the_filter_tested(tmp_path):
    j = SignalJournal(tmp_path / "sig.db")
    notifier = RecordingNotifier()
    disp = AlertDispatcher(j, notifier, cooldown_s=3600)
    flt = filters.full_stack_bull("BTC", timeframes=("1h", "4h", "1d", "1w"))

    rows = _bull_matrix()
    # a MUCH stronger cell on a base/timeframe the preset never tested
    distractor = matrix_df([{"coin": "SOL", "base": "INDEX", "timeframe": "3m",
                             "direction": "bear", "strength": -2.9, "rank": 1}])
    import pandas as pd
    df = pd.concat([rows, distractor], ignore_index=True)

    fired = disp.dispatch_preset(df, "full_stack_bull", flt, now=1000.0)
    assert fired[0].base == "BTC"          # not INDEX
    assert fired[0].timeframe in ("1h", "4h", "1d", "1w")   # not 3m
    j.close()
