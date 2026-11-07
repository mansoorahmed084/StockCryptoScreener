import pytest

from backend.trading import ideas, risk, tgbot
from backend.trading.manager import DRY_RUN
from backend.trading.store import OPEN

from .test_trading import PAIR, FakeExchange, manager, req, scanner, setups


class FakeTelegram:
    chat_id = "42"

    def __init__(self):
        self.sent, self.edits, self.answers, self.queue = [], [], [], []

    def send_buttons(self, text, buttons, html=False):
        self.sent.append((text, buttons))
        return 100 + len(self.sent)

    def edit(self, message_id, text, buttons=None, html=False):
        self.edits.append((message_id, text, buttons))

    def answer(self, callback_id, text=""):
        self.answers.append(text)

    def send_text(self, text, html=False):
        self.sent.append((text, None))
        return 100 + len(self.sent)

    def updates(self, offset, timeout=20, allowed=("callback_query",)):
        self.allowed = allowed
        out, self.queue = self.queue, []
        return out


def tap(tg, data, chat="42", uid=[0]):
    uid[0] += 1
    tg.queue.append({"update_id": uid[0], "callback_query": {
        "id": f"cb{uid[0]}", "data": data,
        "message": {"message_id": 7, "chat": {"id": chat}}}})


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def tg(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(tgbot, "telegram_from_env", lambda: fake)
    return fake


def ready_setup(tmp_path, ex, **kw):
    m, s = scanner(tmp_path, ex, **kw)
    [idea] = ideas.scan(m, setups(), s)
    assert idea["status"] == ideas.READY
    return m, s, m.store.idea(idea["id"])


def test_a_ready_setup_is_sent_with_a_place_button(tmp_path, tg):
    ex = FakeExchange()
    m, s, idea = ready_setup(tmp_path, ex)
    [(text, buttons)] = tg.sent
    assert "SOL" in text and f"#{idea['id']}" in text
    assert buttons == [("Place", f"p|main|{idea['id']}")]
    assert m.store.idea(idea["id"])["tg_message_id"] == 101
    assert ex.writes == []


def test_place_then_confirm_places_the_trade(tmp_path, tg):
    ex = FakeExchange()
    m, s, idea = ready_setup(tmp_path, ex)
    clock = Clock(idea["ts_ms"] / 1000 + 5)
    bot = tgbot.Listener({"main": m}, s, tg, clock=clock)

    tap(tg, f"p|main|{idea['id']}")
    assert bot.poll() == [f"[main] #{idea['id']} SOL: plan shown"]
    assert ex.writes == []                                 # Place alone sends nothing
    _, text, buttons = tg.edits[-1]
    assert "<b>Risk:</b>" in text and [b[0] for b in buttons] == ["Confirm", "Skip"]

    tap(tg, buttons[0][1])
    [line] = bot.poll()
    assert "placed, trade #" in line
    assert [w[0] for w in ex.writes] == ["update_leverage", "create_order", "create_tpsl"]
    assert m.store.trades()[0]["status"] == OPEN
    assert m.store.idea(idea["id"])["status"] == ideas.PLACED


def test_an_old_confirm_button_places_nothing(tmp_path, tg):
    ex = FakeExchange()
    m, s, idea = ready_setup(tmp_path, ex)
    clock = Clock(idea["ts_ms"] / 1000 + 5)
    bot = tgbot.Listener({"main": m}, s, tg, clock=clock)
    tap(tg, f"p|main|{idea['id']}")
    bot.poll()
    confirm = tg.edits[-1][2][0][1]
    clock.t += tgbot.CONFIRM_S + 1
    tap(tg, confirm)
    assert bot.poll() == [f"[main] #{idea['id']} SOL: confirm expired"]
    assert ex.writes == []
    assert tg.edits[-1][2] == [("Place", f"p|main|{idea['id']}")]


def test_taps_from_another_chat_are_ignored(tmp_path, tg):
    ex = FakeExchange()
    m, s, idea = ready_setup(tmp_path, ex)
    bot = tgbot.Listener({"main": m}, s, tg, clock=Clock(idea["ts_ms"] / 1000))
    tap(tg, f"c|main|{idea['id']}|{int(idea['ts_ms'] / 1000)}", chat="999")
    assert bot.poll() == ["ignored a tap from chat 999"]
    assert ex.writes == [] and tg.answers == ["not allowed"]


def test_skip_and_unknown_account(tmp_path, tg):
    ex = FakeExchange()
    m, s, idea = ready_setup(tmp_path, ex)
    bot = tgbot.Listener({"main": m}, s, tg, clock=Clock(idea["ts_ms"] / 1000))
    tap(tg, f"x|main|{idea['id']}")
    tap(tg, f"p|sehe|{idea['id']}")
    assert bot.poll() == [f"[main] #{idea['id']} SOL: skipped", "tap for unwatched account sehe"]
    assert m.store.idea(idea["id"])["status"] == ideas.EXPIRED
    tap(tg, f"p|main|{idea['id']}")
    assert "(blocked)" in bot.poll()[0]                    # a skipped setup cannot be placed


def test_a_stale_setup_is_not_offered_for_confirm(tmp_path, tg):
    ex = FakeExchange()
    m, s, idea = ready_setup(tmp_path, ex)
    bot = tgbot.Listener({"main": m}, s, tg,
                         clock=Clock(idea["ts_ms"] / 1000 + s.max_age_minutes * 60 + 1))
    tap(tg, f"p|main|{idea['id']}")
    assert "(blocked)" in bot.poll()[0]
    assert m.store.idea(idea["id"])["status"] == ideas.EXPIRED


def test_dry_run_confirm_sends_nothing(tmp_path, tg):
    ex = FakeExchange()
    m, s, idea = ready_setup(tmp_path, ex, mode=DRY_RUN)
    bot = tgbot.Listener({"main": m}, s, tg, clock=Clock(idea["ts_ms"] / 1000))
    tap(tg, f"p|main|{idea['id']}")
    bot.poll()
    tap(tg, tg.edits[-1][2][0][1])
    assert "dry run, nothing sent" in bot.poll()[0]
    assert ex.writes == []


def test_a_proposed_short_with_its_own_risk(tmp_path, tg):
    ex = FakeExchange()
    m, s = scanner(tmp_path, ex)
    r = req(side=risk.SHORT, stop_loss=104.0, take_profit=90.0, risk_inr=300.0)
    idea = ideas.propose(m, r, timeframe="15m", why="rejected 4h resistance", settings=s)
    assert idea["status"] == ideas.READY and idea["side"] == risk.SHORT
    assert "SHORT SOL" in tg.sent[-1][0] and "rejected 4h resistance" in tg.sent[-1][0]
    assert ex.writes == []
    bot = tgbot.Listener({"main": m}, s, tg, clock=Clock(m.store.idea(idea["id"])["ts_ms"] / 1000))
    tap(tg, f"p|main|{idea['id']}")
    bot.poll()
    tap(tg, tg.edits[-1][2][0][1])
    assert "placed" in bot.poll()[0]
    order = next(w[1] for w in ex.writes if w[0] == "create_order")
    assert order["side"] == "sell"
    assert m.store.trades()[0]["risk_inr"] <= 300


def test_a_proposal_under_2r_is_blocked_and_not_sent(tmp_path, tg):
    ex = FakeExchange()
    m, s = scanner(tmp_path, ex)
    idea = ideas.propose(m, req(stop_loss=95.0, take_profit=103.0), timeframe="1h",
                         why="weak", settings=s)
    assert idea["status"] == ideas.BLOCKED and "2x the risk" in idea["reason"]
    assert tg.sent == []
