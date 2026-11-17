"""Download closed candles from Binance's public market-data API into a CSV.

    .venv/bin/python -m calibration.fetch_candles BTCUSDT 15m 10000 calibration/data/btcusdt_15m.csv

The CSV has the same columns as a TradingView export (time in Unix seconds, open, high, low, close,
volume), so every tool here reads it the same way. Only the public klines endpoint is used.
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request

URL = "https://api.binance.com/api/v3/klines?symbol={sym}&interval={iv}&limit=1000&endTime={end}"
STEP_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def fetch(symbol: str, interval: str, bars: int) -> list[list]:
    end = int(time.time() * 1000)
    rows: list[list] = []
    while len(rows) < bars:
        req = urllib.request.Request(URL.format(sym=symbol, iv=interval, end=end),
                                     headers={"User-Agent": "calibration-fetch/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            batch = json.load(resp)
        if not batch:
            break
        rows = batch + rows
        end = batch[0][0] - 1
        time.sleep(0.2)
    rows = rows[-bars:]
    # drop a still-forming last candle: keep only bars whose close time is in the past
    now = int(time.time() * 1000)
    return [r for r in rows if r[6] < now]


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 4:
        print(__doc__)
        return 2
    symbol, interval, bars, out = args[0], args[1], int(args[2]), args[3]
    rows = fetch(symbol, interval, bars)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for r in rows:
            w.writerow([r[0] // 1000, r[1], r[2], r[3], r[4], r[5]])
    print(f"{symbol} {interval}: {len(rows)} bars -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
