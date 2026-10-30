"""Run the SMC scan 5 minutes after every 4h candle close, forever.

    python research/smc_runner.py                 # the cloud default below
    python research/smc_runner.py --log --watch 3 # any scan_smc.py arguments

The cloud service (deploy/docker-compose.yml) runs this instead of the
Windows scheduled task. Each scan runs in its own process, so a crash or a
hung request in one run never stops the next. It also scans once at start,
which catches a call whose entry candle is still forming.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DEFAULT = ["--log", "--min-vol", "5", "--watch", "3", "--telegram",
           "--dcx-check", "--offer"]
BAR = pd.Timedelta("4h")
AFTER = pd.Timedelta("5min")      # let the exchange settle the closed candle


def next_run(now: pd.Timestamp) -> pd.Timestamp:
    t = now.floor("4h") + AFTER
    return t if t > now else t + BAR


def scan(args: list[str]) -> None:
    started = pd.Timestamp.now(tz="UTC")
    print(f"[runner] {started:%Y-%m-%d %H:%M} UTC scan {' '.join(args)}", flush=True)
    try:
        r = subprocess.run([sys.executable, str(HERE / "scan_smc.py"), *args],
                           cwd=HERE.parent, timeout=20 * 60)
        print(f"[runner] exit {r.returncode}", flush=True)
    except subprocess.TimeoutExpired:
        print("[runner] scan took over 20 minutes and was stopped", flush=True)


def main() -> None:
    args = sys.argv[1:] or DEFAULT
    scan(args)
    while True:
        now = pd.Timestamp.now(tz="UTC")
        at = next_run(now)
        print(f"[runner] next scan {at:%Y-%m-%d %H:%M} UTC", flush=True)
        time.sleep(max(1.0, (at - now).total_seconds()))
        scan(args)


if __name__ == "__main__":
    main()
