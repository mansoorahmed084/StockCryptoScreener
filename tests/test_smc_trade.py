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


# ---------------------------------------------------------------- auto mode
def test_auto_open_places_with_fixed_stop_target_and_no_trail(tmp_path, tg):
    ex = FakeExchange()
    m, s = bot(tmp_path, ex)
    idea_id, trade_id, msg = smc_trade.auto_open(m, s, call(), 100.0, 5)
    assert trade_id and msg.startswith("traded: ")
    kinds = [w[0] for w in ex.writes]
    assert "create_order" in kinds
    assert next(w for w in ex.writes if w[0] == "create_tpsl")[1:] == (95.0, 130.0)
    t = next(x for x in m.store.trades() if x["id"] == trade_id)
    assert t["trail"] == 0                       # the strategy keeps a fixed stop
    assert m.store.idea(idea_id)["status"] == ideas.PLACED
    assert tg.sent == []                         # no Place button: nothing to tap
    assert smc_trade.held_from_idea(m, idea_id)["id"] == trade_id


@pytest.mark.parametrize("coin", ["S", "ARB", "APT"])
def test_auto_open_never_trades_the_owners_coins(tmp_path, tg, coin):
    ex = FakeExchange()
    m, s = bot(tmp_path, ex)
    idea_id, trade_id, msg = smc_trade.auto_open(m, s, call(coin=coin), 100.0, 5)
    assert (idea_id, trade_id) == (None, None) and "protected" in msg
    assert ex.writes == []


def test_auto_open_never_adds_to_a_coin_already_held(tmp_path, tg):
    ex = FakeExchange()
    ex.fill(PAIR, 3.0)                           # a position opened by hand
    m, s = bot(tmp_path, ex)
    _, trade_id, msg = smc_trade.auto_open(m, s, call(), 100.0, 5)
    assert trade_id is None and "already hold" in msg
    assert ex.writes == []


def test_auto_open_sizes_down_when_a_tight_stop_needs_too_much_margin(tmp_path, tg):
    ex = FakeExchange()                          # free Rs 50,000: margin budget Rs 2,500
    m, s = bot(tmp_path, ex)
    _, trade_id, msg = smc_trade.auto_open(m, s, call(stop="99.5"), 1000.0, 5)
    assert trade_id and "sized down" in msg
    t = next(x for x in m.store.trades() if x["id"] == trade_id)
    assert t["margin_inr"] <= 2500 and t["risk_inr"] < 1000
    assert next(w for w in ex.writes if w[0] == "create_tpsl")[1] == 99.5


def test_auto_close_closes_the_bots_trade_on_the_choch_exit_only(tmp_path, tg):
    ex = FakeExchange()
    m, s = bot(tmp_path, ex)
    idea_id, trade_id, _ = smc_trade.auto_open(m, s, call(), 100.0, 5)
    row = call(idea=str(idea_id), why="stop")
    assert smc_trade.auto_close(m, row) is None  # the exchange stop handles that
    assert "exit_position" not in [w[0] for w in ex.writes]
    msg = smc_trade.auto_close(m, call(idea=str(idea_id), why="choch"))
    assert msg and f"#{trade_id}" in msg
    assert [w for w in ex.writes if w[0] == "exit_position"] == [("exit_position", "p1")]
    assert smc_trade.auto_close(m, call(idea=str(idea_id), why="choch")) is None  # gone


def test_auto_close_never_touches_a_hand_position_or_a_protected_coin(tmp_path, tg,
                                                                    monkeypatch):
    ex = FakeExchange()
    m, s = bot(tmp_path, ex)
    idea_id, _, _ = smc_trade.auto_open(m, s, call(), 100.0, 5)
    assert smc_trade.auto_close(m, call(idea="-", why="choch")) is None
    assert smc_trade.auto_close(m, call(idea="", why="time")) is None
    monkeypatch.setattr(smc_trade, "PROTECTED", frozenset({"SOL"}))
    assert smc_trade.auto_close(m, call(idea=str(idea_id), why="choch")) is None
    assert "exit_position" not in [w[0] for w in ex.writes]


def test_auto_dry_run_sends_nothing(tmp_path, tg):
    from backend.trading.manager import DRY_RUN
    ex = FakeExchange()
    m, s = bot(tmp_path, ex, mode=DRY_RUN)
    _, trade_id, msg = smc_trade.auto_open(m, s, call(), 100.0, 5)
    assert trade_id and msg.startswith("dry run") and ex.writes == []


def test_the_client_refuses_any_spot_write():
    from backend.trading.client import CoinDcxError, FuturesClient
    c = FuturesClient("k", "s")
    with pytest.raises(CoinDcxError, match="never places spot orders"):
        c._write("/exchange/v1/orders/create", {"market": "SOLINR"})


def test_journal_auto_mode_trades_a_fresh_call_then_closes_it_on_choch(tmp_path, tg):
    pytest.importorskip("numba")             # smc_paper -> smc needs it
    import smc_paper
    ex = FakeExchange()
    m, s = bot(tmp_path, ex)
    b = object.__new__(smc_paper.Bot)            # no config.yaml, no real exchange
    b.t, b.check, b.offer, b.auto = smc_trade, False, False, True
    b.dry, b.live, b.settings = m, m, s
    b.risk_pct, b.risk_cap_inr, b.leverage = 1.0, 100.0, 5
    now = pd.Timestamp("2026-11-07 16:10", tz="UTC")
    row = {c: "" for c in smc_paper.COLS}
    row.update(call().to_dict(), status="open", late="no", entry_utc="2026-11-07 16:00")
    df = pd.DataFrame([row], columns=smc_paper.COLS)
    b.handle_new(df, now)
    assert df.at[0, "note"].startswith("traded: ") and df.at[0, "idea"] not in ("", "-")
    assert "create_order" in [w[0] for w in ex.writes]
    b.handle_new(df, now)                        # the next run never trades it twice
    assert [w[0] for w in ex.writes].count("create_order") == 1
    df.loc[0, ["status", "why"]] = ["closed", "choch"]
    b.handle_closed(df)
    assert df.at[0, "note"].startswith("auto-closed trade #")
    assert ("exit_position", "p1") in ex.writes
