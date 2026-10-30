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
import smc_paper  # noqa: E402

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
    bar: tuple | None = None # the forming candle so far: (open, high, low, close)
    dbar: tuple | None = None  # the forming DAILY candle: (open ts, o, h, l, c)


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
    out = {"new": None, "open": None, "closed": None, "trades": None}
    if len(closed) < 100 or len(htf) < 30:
        return out
    last_ts = closed.index[-1]

    tr, L = smc.run_frames(coin, CFG, closed, htf, htf)
    out["trades"] = tr
    held = tr[tr.why == "data_end"]
    if len(held):
        t = held.iloc[-1]
        lvl = L["lsl"][-1] if t.dir > 0 else L["lsh"][-1]
        out["open"] = dict(t, choch_level=float(lvl))
    ended = tr[(tr.exit_time == last_ts) & (tr.why != "data_end")]
    if len(ended):
        out["closed"] = dict(ended.iloc[-1])

    tr2, L2 = smc.run_frames(coin, CFG, ltf, htf, htf)
    fresh = tr2[tr2.sig == last_ts]
    if len(fresh):
        t = fresh.iloc[-1]
        # the level a 4h CLOSE must cross to end the trade, as of the signal
        # candle (index -2: the last row is the forming candle's open)
        lvl = L2["lsl"][-2] if t.dir > 0 else L2["lsh"][-2]
        out["new"] = dict(t, choch_level=float(lvl))
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
    bar = None
    if len(forming):
        f = forming.iloc[0]
        open_ts, open_px = forming.index[0], float(f["open"])
        last = float(f["close"])
        bar = (open_px, float(f["high"]), float(f["low"]), last)
    else:                       # between candles: the next one opens now
        open_ts = closed4.index[-1] + BAR
        open_px = last = float(closed4["close"].iloc[-1])
    fd = kd[kd.index + smc.TF_DELTA[CFG.htf] > now]
    dbar = None
    if len(fd):
        r = fd.iloc[0]
        dbar = (fd.index[0], float(r["open"]), float(r["high"]), float(r["low"]),
                float(r["close"]))
    return Live(coin, sym, with_open_bar(closed4, open_ts, open_px),
                closed_only(kd, CFG.htf, now), last, coin in dcx, bar, dbar)


def watch(live: Live, near: float = 0.03) -> list[dict]:
    """Setups the FORMING 4h candle would trigger if it closed at a price.

    Two questions per coin, both answered by the real simulation on a
    hypothetical close (nothing is re-implemented):
      * if the candle closed at the current price, would it signal?
      * if it closed just past the live 4h swing high (long) or swing low
        (short), within `near` of the price, would it signal?
    The second is only a guide: the sweep and the daily trend are checked,
    but the stop is read at the trigger price and the real close decides.
    """
    if live.bar is None:
        return []
    closed = live.ltf.iloc[:-1]
    if len(closed) < 100 or len(live.htf) < 30:
        return []
    o, h, l, c = live.bar
    ts = live.ltf.index[-1]
    S = smc.struct_of(closed, CFG.k_ltf)
    tests = [(0, c)]
    for d, lvl in ((1, S["lsh"][-1]), (-1, S["lsl"][-1])):
        if np.isfinite(lvl) and d * (lvl - c) > 0 and abs(lvl / c - 1) <= near:
            tests.append((d, lvl * (1 + d * 1e-4)))
    # the 20:00 UTC candle closes together with the daily candle, so its
    # signal is judged on that day's close too: close the day hypothetically
    day = smc.TF_DELTA[CFG.htf]
    closes_day = live.dbar is not None and ts + BAR == live.dbar[0] + day
    out: dict[int, dict] = {}
    for want, px in tests:
        bar = pd.DataFrame({"open": [o], "high": [max(h, px)], "low": [min(l, px)],
                            "close": [px], "volume": [0.0]}, index=[ts])
        frame = with_open_bar(pd.concat([closed[bar.columns], bar]), ts + BAR, px)
        htf = live.htf
        if closes_day:
            dts, do, dh, dl, _dc = live.dbar
            drow = pd.DataFrame({"open": [do], "high": [max(dh, px)],
                                 "low": [min(dl, px)], "close": [px],
                                 "volume": [0.0]}, index=[dts])
            htf = pd.concat([htf[drow.columns], drow])
        tr, _ = smc.run_frames(live.coin, CFG, frame, htf, htf)
        hit = tr[tr.sig == ts]
        if not len(hit):
            continue
        t = dict(hit.iloc[-1])
        if want and t["dir"] != want:
            continue
        if t["dir"] not in out:          # "fires now" beats "fires at the level"
            out[t["dir"]] = dict(t, close_px=px, now=want == 0)
    return list(out.values())


# ------------------------------------------------------------------ report
def _p(x: float) -> str:
    return f"{x:.6g}"


def scan(min_vol: float = 10.0, dcx_only: bool = False,
         coins: list[str] | None = None, workers: int = 4,
         now: pd.Timestamp | None = None) -> tuple[list, pd.Timestamp]:
    """Fetch and evaluate every coin. Returns [(Live, 24h vol, evaluate())]."""
    bf = BinanceFutures(cache_ttl=0)
    now = now or pd.Timestamp.now(tz="UTC")
    uni, dcx = universe(bf, min_vol, dcx_only, coins)
    print(f"SMC Sweep-Break scan  {now:%Y-%m-%d %H:%M} UTC  "
          f"({len(uni)} Binance perps, 24h vol >= ${min_vol:g}M"
          f"{', CoinDCX only' if dcx_only else ''})", file=sys.stderr)

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

    with ThreadPoolExecutor(workers) as ex:
        return [r for r in ex.map(one, uni) if r], now


def watch_report(results: list, now: pd.Timestamp, near: float) -> tuple[str, list]:
    """The WATCH table as text, and its rows (for the journal)."""
    rows = []
    for live, vol, _ev in results:
        for t in watch(live, near):
            risk = abs(t["entry"] - t["stop"])
            d = t["dir"]
            rows.append({
                "coin": live.coin, "side": "LONG" if d > 0 else "SHORT",
                "trigger": ("fires if it closes here" if t["now"] else
                            ("4h close above " if d > 0 else "4h close below ")
                            + _p(t["close_px"])),
                "away %": f"{100 * d * (t['close_px'] - live.last) / live.last:+.2f}"
                          if not t["now"] else "0",
                "now": _p(live.last),
                "stop": _p(t["stop"]), "stop %": f"{100 * t['risk_pct']:.1f}",
                "6R target": _p(t["entry"] + d * CFG.tp_r * risk),
                "CoinDCX": "yes" if live.dcx else "-",
                "vol $M": f"{vol / 1e6:.0f}", "_k": (not t["now"], abs(t["close_px"] / live.last - 1))})
    rows.sort(key=lambda r: r.pop("_k"))
    close = now.floor("4h") + BAR
    mins = int((close - now).total_seconds() // 60)
    out = [f"\nWATCH - setups the forming 4h candle would trigger (it closes "
           f"{close:%H:%M} UTC, in {mins} min). Daily trend and sweep are already "
           f"in place; only the close is missing. Entry = next 4h open, so the "
           f"stop % and target move with it: {len(rows)}"]
    if rows:
        out.append(pd.DataFrame(rows).to_string(index=False))
    return "\n".join(out), rows


def report(results: list, now: pd.Timestamp) -> str:
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
                          "why": WHY_TEXT.get(t["why"], t["why"]),
                          "R": f"{t['r']:+.2f}", "CoinDCX": tag})

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    last_close = now.floor("4h")
    out = [f"SMC Sweep-Break scan {now:%Y-%m-%d %H:%M} UTC, {len(results)} coins. "
           f"Last closed 4h candle: {last_close - BAR:%Y-%m-%d %H:%M} UTC "
           f"(closed {last_close:%H:%M} UTC). Next scan after "
           f"{last_close + BAR:%H:%M} UTC."]
    for title, rows in (("NEW  - signal on the candle that just closed; enter at this candle's open", new),
                        ("OPEN - trades the strategy holds now", held),
                        ("CLOSED - ended on the last closed candle", ended)):
        out.append(f"\n{title}: {len(rows)}")
        if rows:
            out.append(pd.DataFrame(rows).to_string(index=False))
    out.append("\nRules: risk 0.5-1% of equity per trade, at most 10 open. "
               "Size = risk / stop %. Backtest, not advice.")
    return "\n".join(out)


WHY_TEXT = {"choch": "4h CHoCH", "stop": "stop", "target": "6R target",
            "time": "28 days"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--min-vol", type=float, default=10.0,
                    help="min 24h quote volume, $ millions (default 10)")
    ap.add_argument("--dcx-only", action="store_true",
                    help="only coins listed on CoinDCX futures")
    ap.add_argument("--coins", default="", help="comma list, e.g. BTC,ETH")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--watch", type=float, nargs="?", const=3.0, default=None,
                    metavar="PCT", help="also list setups the forming 4h candle "
                    "would trigger, within PCT%% of price (default 3)")
    ap.add_argument("--log", action="store_true",
                    help="also update the paper journal (journal/smc_paper.csv)")
    ap.add_argument("--telegram", action="store_true",
                    help="with --log: message the trade bot on each NEW call "
                         "and each closed paper trade (text only)")
    ap.add_argument("--telegram-dry", action="store_true",
                    help="with --log: print those messages instead of sending")
    a = ap.parse_args()
    if a.log:
        smc_paper.attach_log()      # scheduled runs have no console
    coins = [c.strip().upper() for c in a.coins.split(",") if c.strip()] or None
    try:
        results, now = scan(a.min_vol, a.dcx_only, coins, a.workers)
        text = report(results, now)
        print(text)
        watching = None
        if a.watch is not None:
            wtext, watching = watch_report(results, now, a.watch / 100)
            print(wtext)
            text += "\n" + wtext
        if a.log:
            tg = (smc_paper.Telegram(dry=True) if a.telegram_dry else
                  smc_paper.Telegram() if a.telegram else None)
            smc_paper.update(results, now, text, watching, tg)
    except Exception:
        if not a.log:
            raise
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
