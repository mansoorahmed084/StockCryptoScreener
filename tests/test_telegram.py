"""TelegramNotifier: Markdown with a plain-text fallback, and no token in logs."""
import logging

import httpx

from backend.alerts.telegram import TelegramNotifier

TOKEN = "123456:SECRET-token_value"
PARSE_ERROR = ("Bad Request: can't parse entities: Can't find end of the entity "
               "starting at byte offset 12")


class Resp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


class FakeClient:
    """Answers each post with the next scripted response (or raises it)."""

    def __init__(self, *answers):
        self.answers, self.posts = list(answers), []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, dict(json)))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def ok(result=None):
    return Resp(200, {"ok": True, "result": result or {"message_id": 1}})


def test_markdown_is_kept_when_it_parses():
    c = FakeClient(ok())
    assert TelegramNotifier(TOKEN, "42", client=c).send("*bold* SOL") is True
    assert len(c.posts) == 1 and c.posts[0][1]["parse_mode"] == "Markdown"


def test_an_underscore_pair_name_is_resent_as_plain_text():
    c = FakeClient(Resp(400, {"ok": False, "description": PARSE_ERROR}), ok())
    n = TelegramNotifier(TOKEN, "42", client=c)
    assert n.send("[CoinDCX] B-BNB_USDT: position closed") is True
    assert len(c.posts) == 2
    assert "parse_mode" not in c.posts[1][1]
    assert c.posts[1][1]["text"] == "[CoinDCX] B-BNB_USDT: position closed"


def test_other_errors_are_not_retried_and_the_log_has_no_token(caplog):
    c = FakeClient(Resp(403, {"ok": False, "description": "Forbidden: bot was blocked"}))
    with caplog.at_level(logging.WARNING):
        assert TelegramNotifier(TOKEN, "42", client=c).send("hi") is False
    assert len(c.posts) == 1
    assert "403" in caplog.text and TOKEN not in caplog.text


def test_a_network_error_is_logged_without_the_url(caplog):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    c = FakeClient(httpx.ConnectError(f"failed to reach {url}"))
    with caplog.at_level(logging.WARNING):
        assert TelegramNotifier(TOKEN, "42", client=c).send("hi") is False
    assert TOKEN not in caplog.text and "<token>" in caplog.text


def test_button_calls_return_the_result_or_none(caplog):
    c = FakeClient(ok({"message_id": 7}),
                   Resp(400, {"ok": False, "description": "Bad Request: message is not modified"}))
    n = TelegramNotifier(TOKEN, "42", client=c)
    assert n.send_buttons("pick", [("Place", "p|main|1")]) == 7
    with caplog.at_level(logging.WARNING):
        assert n._call("editMessageText", chat_id="42", message_id=7, text="x") is None
    assert TOKEN not in caplog.text
