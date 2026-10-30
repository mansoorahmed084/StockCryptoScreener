"""Live scan for SMC Sweep-Break (STRATEGY_SMC_SweepBreak.md).

    python research/scan_smc.py                 # Binance USDT perps, 24h vol >= $10M
    python research/scan_smc.py --min-vol 3     # include smaller coins ($3M)
    python research/scan_smc.py --dcx-only      # only coins on CoinDCX futures
    python research/scan_smc.py --coins BTC,ETH,SOL

It runs the backtested config, B_final, unchanged on live Binance futures
candles and prints three lists:

  NEW    the 4h candle that just CLOSED made a signal. The backtest buys at the
         open of the candle that is forming now. "now R" shows how far price
         has already moved from that open.
  OPEN   trades the strategy would be holding right now, with the stop, the
         6R target and the 4h close that would end them (the CHoCH level).
  CLOSED trades that ended on the last closed 4h candle, and why.

How it stays honest:
  * every 4h and daily candle that has not closed is dropped
  * the forming 4h candle is kept only as its OPEN (o = h = l = c), because
    that open is the backtest's fill price and it is already known
  * the daily trend uses closed daily candles only (yesterday back)
  * scan_smc_check.py replays this exact code on the backtest data at many
    past dates and checks it agrees with the backtest trade for trade

Read-only. It places nothing.
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402,F401  (puts the repo root on sys.path)
import smc      # noqa: E402
import smc_oos  # noqa: E402

from backend.data.binance_futures import BinanceFutures  # noqa: E402
from backend.data.futures import fetch_futures           # noqa: E402

CFG = smc_oos.FINALISTS["B_final"]
# 1000 x 4h = 166 days and 400 daily candles: enough swings for the
# structure state to settle (scan_smc_check.py tests these exact windows),
# and light on Binance's request weight (5 + 2 per coin)
N_LTF, N_HTF = 1000, 400
BAR = smc.TF_DELTA[CFG.ltf]


@dataclass
class Live:
    coin: str
    symbol: str
    ltf: pd.DataFrame        # closed 4h candles + the forming candle's open
    htf: pd.DataFrame        # closed daily candles
    last: float              # last traded price
    dcx: bool


def closed_only(df: pd.DataFrame, tf: str, now: pd.Timestamp) -> pd.DataFrame:
    return df[df.index + smc.TF_DELTA[tf] <= now]


def with_open_bar(closed: pd.DataFrame, open_ts: pd.Timestamp,
                  open_px: float) -> pd.DataFrame:
    """Append the forming candle, known only by its open."""
    row = pd.DataFrame({"open": [open_px], "high": [open_px], "low": [open_px],
                        "close": [open_px], "volume": [0.0]}, index=[open_ts])
    return pd.concat([closed[["open", "high", "low", "close", "volume"]], row])


def evaluate(coin: str, ltf: pd.DataFrame, htf: pd.DataFrame,
             now: pd.Timestamp) -> dict:
    """NEW / OPEN / CLOSED for one coin.

    `ltf` is closed candles plus a last open-only row; `htf` is closed only.
    Two passes: closed candles alone give the trades held now and the ones
    that just ended; the extra open-only row lets a signal on the last closed
    candle take its entry, exactly as the backtest's next-open fill does.
    """
    closed = ltf.iloc[:-1]
    out = {"new": None, "open": None, "closed": None}
    if len(closed) < 100 or len(htf) < 30:
        return out
    last_ts = closed.index[-1]

    tr, L = smc.run_frames(coin, CFG, closed, htf, htf)
    held = tr[tr.why == "data_end"]
    if len(held):
        t = held.iloc[-1]
        lvl = L["lsl"][-1] if t.dir > 0 else L["lsh"][-1]
        out["open"] = dict(t, choch_level=float(lvl))
    ended = tr[(tr.exit_time == last_ts) & (tr.why != "data_end")]
    if len(ended):
        out["closed"] = dict(ended.iloc[-1])

    tr2, _ = smc.run_frames(coin, CFG, ltf, htf, htf)
    fresh = tr2[tr2.sig == last_ts]
    if len(fresh):
        out["new"] = dict(fresh.iloc[-1])
    return out


# ------------------------------------------------------------------ fetch
STABLES = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "USDE", "BUSD", "EUR"}


def universe(bf: BinanceFutures, min_vol: float, dcx_only: bool,
             coins: list[str] | None) -> tuple[list[tuple[str, str, float]], set]:
    """Crypto USDT perpetuals only, like the backtest's universe: no indexes,
    pre-market contracts, gold tokens (RWA) or stablecoins."""
    perps = bf.perpetuals()
    kind = {s["symbol"]: (s.get("underlyingType"), s.get("underlyingSubType") or [])
            for s in bf._get("/fapi/v1/exchangeInfo")["symbols"]}
    vols = {r["symbol"]: float(r["quoteVolume"])
            for r in bf._get("/fapi/v1/ticker/24hr")}
    dcx = set(fetch_futures().keys())
    out = []
    for coin, sym in perps.items():
        typ, sub = kind.get(sym, (None, []))
        if typ != "COIN" or "RWA" in sub or coin in STABLES:
            continue
        if coins and coin not in coins:
            continue
        if dcx_only and coin not in dcx:
            continue
        v = vols.get(sym, 0.0)
        if not coins and v < min_vol * 1e6:
            continue
        out.append((coin, sym, v))
    return sorted(out, key=lambda x: -x[2]), dcx


def fetch(bf: BinanceFutures, coin: str, sym: str, dcx: set,
          now: pd.Timestamp) -> Live | None:
    k4 = bf.klines(sym, CFG.ltf, N_LTF)
    kd = bf.klines(sym, CFG.htf, N_HTF)
    if len(k4) < 2 or len(kd) < 2:
        return None
    closed4 = closed_only(k4, CFG.ltf, now)
    forming = k4[k4.index + BAR > now]
    if len(forming):
        open_ts, open_px = forming.index[0], float(forming["open"].iloc[0])
        last = float(forming["close"].iloc[-1])
    else:                       # between candles: the next one opens now
        open_ts = closed4.index[-1] + BAR
        open_px = last = float(closed4["close"].iloc[-1])
    return Live(coin, sym, with_open_bar(closed4, open_ts, open_px),
                closed_only(kd, CFG.htf, now), last, coin in dcx)


# ------------------------------------------------------------------ report
def _p(x: float) -> str:
    return f"{x:.6g}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--min-vol", type=float, default=10.0,
                    help="min 24h quote volume, $ millions (default 10)")
    ap.add_argument("--dcx-only", action="store_true",
                    help="only coins listed on CoinDCX futures")
    ap.add_argument("--coins", default="", help="comma list, e.g. BTC,ETH")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    bf = BinanceFutures(cache_ttl=0)
    now = pd.Timestamp.now(tz="UTC")
    coins = [c.strip().upper() for c in a.coins.split(",") if c.strip()] or None
    uni, dcx = universe(bf, a.min_vol, a.dcx_only, coins)
    print(f"SMC Sweep-Break scan  {now:%Y-%m-%d %H:%M} UTC  "
          f"({len(uni)} Binance perps, 24h vol >= ${a.min_vol:g}M"
          f"{', CoinDCX only' if a.dcx_only else ''})", file=sys.stderr)

    def one(item):
        coin, sym, vol = item
        for attempt in range(3):
            try:
                live = fetch(bf, coin, sym, dcx, now)
                break
            except Exception as exc:  # network: retry, then skip the coin
                if attempt == 2:
                    print(f"  skip {coin}: {exc}", file=sys.stderr)
                    return None
                time.sleep(1 + attempt)
        if live is None:
            return None
        return live, vol, evaluate(coin, live.ltf, live.htf, now)

    with ThreadPoolExecutor(a.workers) as ex:
        results = [r for r in ex.map(one, uni) if r]

    new, held, ended = [], [], []
    for live, vol, ev in results:
        tag = "yes" if live.dcx else "-"
        if ev["new"]:
            t = ev["new"]
            risk = abs(t["entry"] - t["stop"])
            new.append({"coin": live.coin, "side": "LONG" if t["dir"] > 0 else "SHORT",
                        "entry (4h open)": _p(t["entry"]), "stop": _p(t["stop"]),
                        "stop %": f"{100 * t['risk_pct']:.1f}",
                        "6R target": _p(t["entry"] + t["dir"] * CFG.tp_r * risk),
                        "now": _p(live.last),
                        "now R": f"{t['dir'] * (live.last - t['entry']) / risk:+.2f}",
                        "CoinDCX": tag, "vol $M": f"{vol / 1e6:.0f}"})
        if ev["open"]:
            t = ev["open"]
            risk = abs(t["entry"] - t["stop"])
            days = (now - t["entry_time"]).total_seconds() / 86400
            lvl = t["choch_level"]
            held.append({"coin": live.coin, "side": "LONG" if t["dir"] > 0 else "SHORT",
                         "entered": f"{t['entry_time']:%m-%d %H:%M}",
                         "days": f"{days:.1f}", "entry": _p(t["entry"]),
                         "stop": _p(t["stop"]),
                         "6R target": _p(t["entry"] + t["dir"] * CFG.tp_r * risk),
                         "exit on 4h close": (
                             ("below " if t["dir"] > 0 else "above ") + _p(lvl)
                             if np.isfinite(lvl) else "no level yet"),
                         "now": _p(live.last),
                         "now R": f"{t['dir'] * (live.last - t['entry']) / risk:+.2f}",
                         "CoinDCX": tag})
        if ev["closed"]:
            t = ev["closed"]
            ended.append({"coin": live.coin, "side": "LONG" if t["dir"] > 0 else "SHORT",
                          "why": {"choch": "4h CHoCH", "stop": "stop", "target": "6R target",
                                  "time": "28 days"}.get(t["why"], t["why"]),
                          "R": f"{t['r']:+.2f}", "CoinDCX": tag})

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    last_close = now.floor("4h")
    print(f"\nLast closed 4h candle: {last_close - BAR:%Y-%m-%d %H:%M} UTC "
          f"(closed {last_close:%H:%M} UTC). Next scan after "
          f"{last_close + BAR:%H:%M} UTC.")
    for title, rows in (("NEW  - signal on the candle that just closed; enter at this candle's open", new),
                        ("OPEN - trades the strategy holds now", held),
                        ("CLOSED - ended on the last closed candle", ended)):
        print(f"\n{title}: {len(rows)}")
        if rows:
            print(pd.DataFrame(rows).to_string(index=False))
    print("\nRules: risk 0.5-1% of equity per trade, at most 10 open. "
          "Size = risk / stop %. Backtest, not advice.")


if __name__ == "__main__":
    main()
