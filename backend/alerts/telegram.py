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
