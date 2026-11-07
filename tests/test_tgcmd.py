"""The owner's Telegram commands (backend/trading/tgcmd.py through tgbot.Listener),
on the fake exchange and a fake Telegram: nothing reaches CoinDCX or Telegram."""
import datetime as dt

import pytest

from backend.trading import ideas, tgbot, tgcmd

from .test_tgbot import Clock, FakeTelegram, tap
from .test_trading import PAIR, FakeExchange, manager

ARB = "B-ARB_USDT"


def say(tg, text, chat="42", uid=[1000]):
    uid[0] += 1
    tg.queue.append({"update_id": uid[0], "message": {
        "message_id": uid[0], "text": text, "chat": {"id": chat}}})


@pytest.fixture
def setup(tmp_path):
    ex = FakeExchange()
    ex.fill(PAIR, 2.0)
    ex.pos[PAIR].update(mark_price=110.0, leverage=5, liquidation_price=81.0)
    m = manager(tmp_path, ex)
    tg = FakeTelegram()
    listener = tgbot.Listener({"main": m}, ideas.Settings(), tg, clock=Clock(1_000_000))
    return ex, m, tg, listener


def test_parse_reads_commands_aliases_and_bot_names():
    assert tgcmd.parse("/close sol main") == ("close", ["sol", "main"])
    assert tgcmd.parse("/pnl@MyTradeBot") == ("pnl", [])
    assert tgcmd.parse("pos") == ("positions", [])
    assert tgcmd.parse("") == ("", [])


def test_positions_lists_each_position_with_profit_now(setup):
    ex, m, tg, listener = setup
    say(tg, "/positions")
    assert listener.poll() == ["/positions answered"]
    [(text, buttons)] = tg.sent
    # 2 SOL bought at 100, now 110: +20 USDT at 90 INR/USDT = +Rs 1,800
    assert buttons is None and "[main] 1 open, +Rs 1,800 now" in text
    assert "SOL LONG 2 @ 100, now 110 (+10.0%): +Rs 1,800" in text
    assert "SL NONE" in text and "[yours]" in text
    assert "message" in tg.allowed             # the bot now listens for text too
    assert ex.writes == []


def test_a_protected_coin_is_marked(setup):
    ex, m, tg, listener = setup
    ex.fill(ARB, 100.0)
    ex.pos[ARB].update(id="p2", mark_price=95.0)
    say(tg, "/positions")
    listener.poll()
    assert "ARB LONG 100" in tg.sent[0][0] and "[yours, protected]" in tg.sent[0][0]


def test_another_chat_gets_no_answer(setup):
    ex, m, tg, listener = setup
    say(tg, "/positions", chat="999")
    assert listener.poll() == ["ignored a message from chat 999"]
    say(tg, "/close sol", chat="999")
    listener.poll()
    assert tg.sent == [] and ex.writes == []


def test_close_asks_first_then_the_tap_closes_it(setup):
    ex, m, tg, listener = setup
    say(tg, "/close sol")
    listener.poll()
    [(text, buttons)] = tg.sent
    assert "Close this position at market?" in text and "SOL LONG 2" in text
    assert ex.writes == []                     # nothing closes on the command alone
    close = next(d for label, d in buttons if label == "Close it")
    tap(tg, close)
    listener.poll()
    assert ("exit_position", "p1") in ex.writes
    assert PAIR not in ex.pos
    assert "closed at market" in tg.edits[-1][1]


def test_cancel_and_an_old_button_close_nothing(setup):
    ex, m, tg, listener = setup
    say(tg, "/close sol")
    listener.poll()
    buttons = tg.sent[0][1]
    tap(tg, next(d for label, d in buttons if label == "Cancel"))
    listener.poll()
    assert "kept open" in tg.edits[-1][1]
    listener.clock = Clock(1_000_000 + tgbot.CONFIRM_S + 1)
    tap(tg, next(d for label, d in buttons if label == "Close it"))
    listener.poll()
    assert "expired" in tg.edits[-1][1]
    assert "exit_position" not in [w[0] for w in ex.writes] and PAIR in ex.pos


def test_close_of_a_protected_coin_warns_but_the_owner_may_close_it(setup):
    ex, m, tg, listener = setup
    ex.fill(ARB, 100.0)
    ex.pos[ARB].update(id="p2", mark_price=95.0)
    say(tg, "/close arb")
    listener.poll()
    text, buttons = tg.sent[0]
    assert "protected coins" in text
    tap(tg, next(d for label, d in buttons if label == "Close it"))
    listener.poll()
    assert ("exit_position", "p2") in ex.writes


def test_close_of_a_coin_not_held_says_so(setup):
    ex, m, tg, listener = setup
    say(tg, "/close btc")
    listener.poll()
    assert tg.sent == [("no open BTC position", None)]
    say(tg, "/close")
    listener.poll()
    assert "Which one?" in tg.sent[-1][0]


def test_pnl_sums_closed_trades_funding_and_fees_by_period(setup):
    ex, m, tg, listener = setup
    now = dt.datetime(2026, 11, 8, 12, 0, tzinfo=tgcmd.IST)
    ms = lambda d: (now - d).timestamp() * 1000          # noqa: E731
    ex.transactions = lambda page=1, size=100: [
        {"created_at": ms(dt.timedelta(hours=1)), "stage": "funding", "amount": -10,
         "fee_amount": 0},
        {"created_at": ms(dt.timedelta(days=3)), "stage": "default", "amount": 500,
         "fee_amount": 5},
        {"created_at": ms(dt.timedelta(days=20)), "stage": "default", "amount": -300,
         "fee_amount": 4},
    ] if page == 1 else []
    text = tgcmd.pnl_text({"main": m}, now)
    assert "Today (IST): net -Rs 10 (trades +Rs 0, funding -Rs 10, fees +Rs 0)" in text
    assert "7 days: net +Rs 485" in text
    assert "30 days: net +Rs 181" in text
    assert "Open now: +Rs 1,800 on 1 position(s)" in text


def test_help_for_anything_else(setup):
    ex, m, tg, listener = setup
    say(tg, "hello")
    listener.poll()
    assert tg.sent[0][0].startswith("Commands:")
