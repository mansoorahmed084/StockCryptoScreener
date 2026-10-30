"""Run `trade bot` (every account) with no window, for the log-in task.

    .venv\\Scripts\\pythonw.exe deploy\\trade_bot_bg.py     # what the task runs
    .venv\\Scripts\\python.exe  deploy\\trade_bot_bg.py     # same, in a console

* Output goes to data_cache/trade_bot.log (and the console, if there is one).
  A pythonw process has no console, so without the log nothing would show.
* Only ONE copy may run: it holds a lock on a local port, and a second copy
  exits at once. Two bots on one Telegram bot would fight over the taps.
  trade_bot_all.bat goes through this script too, so it shares the lock.
* If the bot stops with an error, it starts again after 30 seconds.

It places a trade only after the owner taps Place and then Confirm.
"""
from __future__ import annotations

import re
import socket
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOG = REPO / "data_cache" / "trade_bot.log"
LOCK_PORT = 47611              # 127.0.0.1 only; held for the life of the bot


# A failed Telegram call logs its URL, and the URL holds the bot token.
TOKEN = re.compile(r"bot\d+:[A-Za-z0-9_-]+")


class _Tee:
    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, x):
        x = TOKEN.sub("bot<redacted>", x)
        for s in self.streams:
            s.write(x)
            s.flush()
        return len(x)

    def flush(self):
        for s in self.streams:
            s.flush()


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG, "a", encoding="utf-8", buffering=1)
    sys.stdout = _Tee(sys.__stdout__, log)
    sys.stderr = _Tee(sys.__stderr__, log)
    stamp = lambda: time.strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731

    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        print(f"===== {stamp()} another trade bot is already running; this copy exits")
        return 0
    lock.listen(1)

    sys.path.insert(0, str(REPO))
    import os
    os.chdir(REPO)                     # config.yaml and data_cache/ are repo-relative
    from backend import cli

    while True:
        print(f"===== {stamp()} trade bot starting (all accounts)")
        try:
            cli.main(["trade", "bot"])
            print(f"===== {stamp()} trade bot returned")
        except KeyboardInterrupt:
            return 0
        except Exception:
            traceback.print_exc()
        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
