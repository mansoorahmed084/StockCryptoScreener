import pytest


@pytest.fixture(autouse=True)
def no_real_telegram(monkeypatch):
    """Tests never reach the owner's Telegram: the trade bot sees no Telegram set up
    unless a test hands it a fake one."""
    from backend.trading import tgbot

    monkeypatch.setattr(tgbot, "telegram_from_env", lambda: None)
