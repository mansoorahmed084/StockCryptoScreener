"""Notifiers. Telegram is primary; NullNotifier is the no-op fallback."""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)


class Notifier:
    def send(self, text: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class NullNotifier(Notifier):
    """Logs instead of sending — used when no credentials are configured."""

    def send(self, text: str) -> bool:
        log.info("[alert:null] %s", text)
        return False


class TelegramNotifier(Notifier):
    def __init__(self, token: str, chat_id: str, *,
                 client: httpx.Client | None = None, timeout: float = 10.0):
        self.token = token
        self.chat_id = chat_id
        self._client = client or httpx.Client(timeout=timeout)

    def send(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            resp = self._client.post(url, json={
                "chat_id": self.chat_id, "text": text,
                "parse_mode": "Markdown", "disable_web_page_preview": True,
            })
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            log.warning("Telegram send failed: %s", exc)
            return False


def notifier_from_env() -> Notifier:
    """Build a Telegram notifier from env vars, else a NullNotifier."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat:
        return TelegramNotifier(token, chat)
    return NullNotifier()
