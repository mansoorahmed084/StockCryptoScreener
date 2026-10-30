"""SMC Sweep-Break -> trade bot bridge (freqtrade-lab/research/smc_trade.py),
on the fake exchange: nothing here reaches CoinDCX or Telegram."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "freqtrade-lab" / "research"))

import smc_trade  # noqa: E402

from backend.trading import ideas, tgbot  # noqa: E402

from .test_tgbot import Clock, FakeTelegram, tap  # noqa: E402
from .test_trading import PAIR, FakeExchange, manager  # noqa: E402


@pytest.fixture
def tg(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(tgbot, "telegram_from_env", lambda: fake)
    return fake


def call(**kw):
    """A journal row as smc_paper.load() gives it: every field a string."""
    row = dict(id="7", coin="SOL", side="long", entry="100", stop="95",
               target="130", seen_px="100", last_px="100", exit_level="96.5")
    return pd.Series({**row, **kw})


def bot(tmp_path, ex, **kw):
    ex.active_pairs = lambda: [PAIR]
    return manager(tmp_path, ex, **kw), ideas.Settings()


def test_check_sizes_the_call_and_sends_nothing(tmp_path):
    ex = FakeExchange()
    m, _ = bot(tmp_path, ex)
    out = smc_trade.check(m, call(), 100.0, 5)
    # the size rounds DOWN to the exchange step, so the risk lands just under
    assert out.startswith("ok: ") and PAIR in out and "risk Rs 97" in out
    assert ex.writes == []


@pytest.mark.parametrize("kw, text", [
    (dict(last_px="120"), "do not carry over"),       # a 1000x contract or stale book
    (dict(coin="PEPE"), "not an INR future"),
])
def test_check_refuses_levels_that_do_not_fit_coindcx(tmp_path, kw, text):
    ex = FakeExchange()
    m, _ = bot(tmp_path, ex)
    out = smc_trade.check(m, call(**kw), 100.0, 5)
    assert out.startswith("refused: ") and text in out


def test_offer_sends_a_place_button_and_places_nothing(tmp_path, tg):
    ex = FakeExchange()
    m, s = bot(tmp_path, ex)
    idea_id, msg = smc_trade.offer(m, s, call(), 100.0, 5)
    assert idea_id and "Place button" in msg
    [(text, buttons)] = tg.sent
    assert "SMC Sweep-Break #7" in text and "below 96.5" in text
    assert buttons == [("Place", f"p|main|{idea_id}")]
    assert ex.writes == []


def test_an_unfit_call_is_not_offered(tmp_path, tg):
    ex = FakeExchange()
    m, s = bot(tmp_path, ex)
    idea_id, msg = smc_trade.offer(m, s, call(last_px="120"), 100.0, 5)
    assert idea_id is None and msg.startswith("not offered")
    assert tg.sent == [] and ex.writes == []


def test_two_taps_place_it_with_stop_and_target_and_it_is_found_held(tmp_path, tg):
    ex = FakeExchange()
    m, s = bot(tmp_path, ex)
    idea_id, _ = smc_trade.offer(m, s, call(), 100.0, 5)
    assert smc_trade.held_from_idea(m, idea_id) is None
    idea = m.store.idea(idea_id)
    listener = tgbot.Listener({"main": m}, s, tg, clock=Clock(idea["ts_ms"] / 1000 + 5))
    tap(tg, f"p|main|{idea_id}")
    listener.poll()
    confirm = next(d for label, d in tg.edits[-1][2] if label == "Confirm")
    tap(tg, confirm)
    listener.poll()
    kinds = [w[0] for w in ex.writes]
    assert "create_order" in kinds and "create_tpsl" in kinds
    sl_tp = next(w for w in ex.writes if w[0] == "create_tpsl")
    assert sl_tp[1:] == (95.0, 130.0)
    held = smc_trade.held_from_idea(m, idea_id)
    assert held and held["pair"] == PAIR
