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
        """Markdown first (alerts use *bold*). If Telegram cannot parse it -- a
        pair such as B-BNB_USDT has an underscore, which Markdown reads as the
        start of italics -- the same text goes again as plain text."""
        body = {"chat_id": self.chat_id, "text": text,
                "parse_mode": "Markdown", "disable_web_page_preview": True}
        status, desc, _ = self._post("sendMessage", body)
        if status == 400 and "parse" in desc.lower():
            body.pop("parse_mode")
            status, desc, _ = self._post("sendMessage", body)
        if status == 200:
            return True
        log.warning("Telegram send failed: %s %s", status or "no answer", desc)
        return False

    def _post(self, method: str, body: dict,
              timeout: float | None = None) -> tuple[int, str, dict]:
        """(HTTP status, Telegram's description, the JSON). Status 0 = no answer.
        Never raises, and never puts the URL in a message: it holds the token."""
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        try:
            resp = (self._client.post(url, json=body, timeout=timeout) if timeout
                    else self._client.post(url, json=body))
        except httpx.HTTPError as exc:
            return 0, self._redact(f"{type(exc).__name__}: {exc}"), {}
        try:
            data = resp.json()
        except ValueError:
            data = {}
        return resp.status_code, self._redact(str(data.get("description", ""))), data

    def _redact(self, text: str) -> str:
        return text.replace(self.token, "<token>") if self.token else text

    # -- buttons (the trade bot) -------------------------------------------------
    def _call(self, method: str, **body) -> dict | None:
        status, desc, data = self._post(method, body, timeout=body.get("timeout", 0) + 15)
        if status != 200:
            log.warning("Telegram %s failed: %s %s", method, status or "no answer", desc)
            return None
        return data.get("result")

    @staticmethod
    def _keyboard(buttons: list[tuple[str, str]]) -> dict:
        return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in buttons]]}

    def send_buttons(self, text: str, buttons: list[tuple[str, str]]) -> int | None:
        """Send plain text with one row of (label, callback data) buttons; the message id."""
        res = self._call("sendMessage", chat_id=self.chat_id, text=text,
                         reply_markup=self._keyboard(buttons))
        return res.get("message_id") if res else None

    def edit(self, message_id: int, text: str,
             buttons: list[tuple[str, str]] | None = None) -> None:
        body = {"chat_id": self.chat_id, "message_id": message_id, "text": text}
        if buttons:
            body["reply_markup"] = self._keyboard(buttons)
        self._call("editMessageText", **body)

    def answer(self, callback_id: str, text: str = "") -> None:
        self._call("answerCallbackQuery", callback_query_id=callback_id, text=text)

    def updates(self, offset: int | None, timeout: int = 20) -> list[dict]:
        body = {"timeout": timeout, "allowed_updates": ["callback_query"]}
        if offset is not None:
            body["offset"] = offset
        return self._call("getUpdates", **body) or []


def telegram_from_env() -> TelegramNotifier | None:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return TelegramNotifier(token, chat) if token and chat else None


class DesktopNotifier(Notifier):
    """A Windows toast, through PowerShell's built-in WinRT classes (no extra
    package). Best-effort: it does nothing on other systems or if it fails."""

    # Windows PowerShell's own app id: toasts need a registered app to show.
    APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

    def send(self, text: str) -> bool:
        if os.name != "nt":
            return False
        import subprocess
        from xml.sax.saxutils import escape
        title, _, body = text.partition(" — ")
        xml = (f"<toast><visual><binding template='ToastGeneric'><text>{escape(title)}</text>"
               f"<text>{escape(body)}</text></binding></visual></toast>")
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
            " ContentType = WindowsRuntime] > $null;"
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument,"
            " ContentType = WindowsRuntime] > $null;"
            "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
            f"$x.LoadXml(\"{xml}\");"
            "$t = [Windows.UI.Notifications.ToastNotification]::new($x);"
            f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{self.APP_ID}').Show($t)"
        )
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        except OSError as exc:
            log.warning("desktop notification failed: %s", exc)
            return False


class MultiNotifier(Notifier):
    """Send through every notifier; True if any of them delivered."""

    def __init__(self, *notifiers: Notifier):
        self.notifiers = notifiers

    def send(self, text: str) -> bool:
        return any([n.send(text) for n in self.notifiers])


def load_dotenv(path: str | os.PathLike | None = None) -> None:
    """Read KEY=value lines from the repo's .env into os.environ, without
    overriding variables that are already set."""
    from pathlib import Path
    p = Path(path) if path else Path(__file__).resolve().parents[2] / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def notifier_from_env() -> Notifier:
    """Build a Telegram notifier from env vars, else a NullNotifier."""
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat:
        return TelegramNotifier(token, chat)
    return NullNotifier()
