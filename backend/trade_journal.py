"""Paper-trade journal: the setups the scans called, replayed on real candles.

``journal/trades.csv`` keeps every setup as it was called (entry rule, stop,
target). ``python -m backend.cli journal`` replays each one on Binance futures
candles and rewrites the tables in ``journal/TRADE_JOURNAL.md`` between the
``<!-- AUTO:... -->`` markers. Notes on what worked and what didn't live outside
the markers, so an update never touches them.

The same rules for every trade:

* entry  ``now``: the price when the list was made.
         ``close_above``: the first closed candle of the trade's timeframe
         that closes above the trigger, a flat level or a line through two
         (time, price) points (read at mid-candle, as the alerts do).
* exit   the first 15-minute candle whose low reaches the stop (a wick
         counts) or whose high reaches the target; both in one candle counts
         as the stop.
* close-stop  the same trade if the stop needed a closed candle of the
         trade's timeframe to close below it, to test whether wick stops
         shake us out of good trades.
* P&L    % from entry to exit, or to the last price while open; $100 a
         trade, no fees.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

CSV = "journal/trades.csv"
MD = "journal/TRADE_JOURNAL.md"
BAR_MIN = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}
MIN_MS = 60_000
STAKE = 100.0
WAITING, OPEN, TARGET, STOPPED = "waiting", "open", "target", "stopped"
ICON = {WAITING: "💤 not triggered", OPEN: "⏳ open", TARGET: "🎯 target",
        STOPPED: "❌ stopped"}


def _num(v) -> float:
    return float(v) if v is not None and v == v and v != "" else float("nan")


def _ms(ts) -> int:
    return int(pd.Timestamp(ts).value // 1_000_000)


@dataclass
class Trade:
    id: int
    day: str
    list: str
    coin: str
    tf: str
    setup: str
    entry_rule: str             # now | close_above
    trigger: float              # flat level (close_above) ...
    t1: float                   # ... or a line through (t1, p1), (t2, p2)
    p1: float
    t2: float
    p2: float
    from_utc: str
    entry_price: float          # now
    stop: float
    target: float
    note: str = ""

    @property
    def from_ms(self) -> int:
        return _ms(pd.Timestamp(self.from_utc, tz="UTC"))

    @property
    def bar_ms(self) -> int:
        return BAR_MIN[self.tf] * MIN_MS

    def level_at(self, t_ms: float) -> float:
        if np.isfinite(self.trigger):
            return self.trigger
        return self.p1 + (self.p2 - self.p1) * (t_ms - self.t1) / (self.t2 - self.t1)


@dataclass
class Outcome:
    status: str
    entry_ms: int | None = None
    entry: float = float("nan")
    exit_ms: int | None = None
    exit: float = float("nan")           # the exit, or the last price while open
    pnl_pct: float = float("nan")
    best_pct: float = float("nan")
    worst_pct: float = float("nan")
    close_status: str = ""               # the same trade with a close-stop
    close_exit: float = float("nan")
    close_pnl_pct: float = float("nan")


def load(path: str | Path = CSV) -> list[Trade]:
    df = pd.read_csv(path, dtype={"note": str}, keep_default_na=True)
    out = []
    for r in df.to_dict("records"):
        out.append(Trade(
            id=int(r["id"]), day=str(r["day"]), list=str(r["list"]), coin=str(r["coin"]),
            tf=str(r["tf"]), setup=str(r["setup"]), entry_rule=str(r["entry_rule"]),
            trigger=_num(r["trigger"]), t1=_num(r["t1"]), p1=_num(r["p1"]),
            t2=_num(r["t2"]), p2=_num(r["p2"]), from_utc=str(r["from_utc"]),
            entry_price=_num(r["entry_price"]), stop=_num(r["stop"]),
            target=_num(r["target"]), note="" if r["note"] != r["note"] else str(r["note"])))
    return out


def _open_ms(df: pd.DataFrame) -> np.ndarray:
    """Candle open times in epoch ms, whatever unit the index is stored in."""
    if not len(df):
        return np.zeros(0, np.int64)
    return (pd.DatetimeIndex(df.index).as_unit("ns").asi8 // 1_000_000).astype(np.int64)


def replay(t: Trade, tf_candles: pd.DataFrame, exit_candles: pd.DataFrame,
           now_ms: int, exit_bar_ms: int = 15 * MIN_MS) -> Outcome:
    """Entry, exit and P&L of one trade. Candles are oldest first, indexed by
    open time (UTC); the last may still be forming."""
    bar = t.bar_ms
    tf_open = _open_ms(tf_candles)
    if t.entry_rule == "now":
        entry, entry_ms = t.entry_price, t.from_ms
    else:
        entry = entry_ms = None
        closes = tf_candles["close"].to_numpy(float)
        for o, c in zip(tf_open, closes):
            if o + bar <= t.from_ms or o + bar > now_ms:
                continue
            if c > t.level_at(o + bar / 2):
                entry, entry_ms = float(c), int(o + bar)
                break
        if entry is None:
            return Outcome(WAITING)

    ex_open = _open_ms(exit_candles)
    after = exit_candles[ex_open >= entry_ms]
    after_open = ex_open[ex_open >= entry_ms]
    last = float(exit_candles["close"].iloc[-1]) if len(exit_candles) else entry
    hi = after["high"].to_numpy(float)
    lo = after["low"].to_numpy(float)
    has_stop = np.isfinite(t.stop)

    # Wick rule: the first candle to touch the stop or the target.
    status, exit_px, exit_ms = OPEN, last, None
    for i in range(len(after)):
        if has_stop and lo[i] <= t.stop:
            status, exit_px, exit_ms = STOPPED, t.stop, int(after_open[i])
            break
        if hi[i] >= t.target:
            status, exit_px, exit_ms = TARGET, t.target, int(after_open[i])
            break

    # Close rule: the stop needs a closed candle of the trade's timeframe.
    tgt_hits = np.flatnonzero(hi >= t.target)
    tgt_ms = int(after_open[tgt_hits[0]]) if len(tgt_hits) else None
    stop_ms = stop_px = None
    if has_stop:
        closes = tf_candles["close"].to_numpy(float)
        for o, c in zip(tf_open, closes):
            if o >= entry_ms and o + bar <= now_ms and c < t.stop:
                stop_ms, stop_px = int(o + bar), float(c)
                break
    if tgt_ms is not None and (stop_ms is None or tgt_ms < stop_ms):
        c_status, c_exit = TARGET, t.target
    elif stop_ms is not None:
        c_status, c_exit = STOPPED, stop_px
    else:
        c_status, c_exit = OPEN, last

    return Outcome(
        status=status, entry_ms=entry_ms, entry=entry, exit_ms=exit_ms, exit=exit_px,
        pnl_pct=(exit_px / entry - 1) * 100,
        best_pct=(hi.max() / entry - 1) * 100 if len(hi) else float("nan"),
        worst_pct=(lo.min() / entry - 1) * 100 if len(lo) else float("nan"),
        close_status=c_status, close_exit=c_exit, close_pnl_pct=(c_exit / entry - 1) * 100)


def run(trades: list[Trade], fetch: Callable[[str, str, int], pd.DataFrame],
        symbols: dict[str, str], now_ms: int) -> list[Outcome]:
    """Replay every trade; ``fetch(symbol, timeframe, limit)`` gives candles."""
    out = []
    for t in trades:
        span = now_ms - t.from_ms
        # 15m exits while the fetch reaches back far enough, then coarser.
        ex_tf = next((tf for tf in ("15m", "1h", "4h") if span / (BAR_MIN[tf] * MIN_MS) < 1400),
                     "1d")
        sym = symbols[t.coin]
        try:
            tf_c = fetch(sym, t.tf, int(min(1500, span // t.bar_ms + 5)))
            ex_c = fetch(sym, ex_tf, int(min(1500, span // (BAR_MIN[ex_tf] * MIN_MS) + 5)))
        except Exception:
            out.append(Outcome("error"))
            continue
        out.append(replay(t, tf_c, ex_c, now_ms, BAR_MIN[ex_tf] * MIN_MS))
    return out


# -- markdown -----------------------------------------------------------------
def _p(v: float) -> str:
    if v is None or not np.isfinite(v):
        return "—"
    return f"{v:,.2f}" if abs(v) >= 1000 else f"{v:.5g}"


def _pct(v: float) -> str:
    return "—" if v is None or not np.isfinite(v) else f"{v:+.1f}%"


def _when(ms_: int | None) -> str:
    return pd.Timestamp(ms_, unit="ms", tz="UTC").strftime("%d %b %H:%M") if ms_ else ""


def _stats(pairs: list[tuple[Trade, Outcome]]) -> dict:
    trig = [o for _, o in pairs if o.status in (OPEN, TARGET, STOPPED)]
    pnl = [o.pnl_pct for o in trig]
    return {"setups": len(pairs), "triggered": len(trig),
            "target": sum(o.status == TARGET for o in trig),
            "stopped": sum(o.status == STOPPED for o in trig),
            "open": sum(o.status == OPEN for o in trig),
            "waiting": sum(o.status == WAITING for _, o in pairs),
            "up": sum(p > 0 for p in pnl), "down": sum(p <= 0 for p in pnl),
            "usd": sum(pnl) * STAKE / 100, "stake": len(trig) * STAKE,
            "avg": float(np.mean(pnl)) if pnl else float("nan"),
            "close_usd": sum(o.close_pnl_pct for o in trig) * STAKE / 100,
            "close_target": sum(o.close_status == TARGET for o in trig),
            "close_stopped": sum(o.close_status == STOPPED for o in trig)}


def _row(label: str, s: dict) -> str:
    return (f"| {label} | {s['setups']} | {s['triggered']} | {s['target']} | {s['stopped']} "
            f"| {s['open']} | {s['up']} / {s['down']} | **{s['usd']:+,.2f}** "
            f"(on ${s['stake']:,.0f}) | {s['close_usd']:+,.2f} |")


def render(trades: list[Trade], outcomes: list[Outcome], asof_ms: int) -> dict[str, str]:
    pairs = list(zip(trades, outcomes))
    head = ("| | Setups | Triggered | 🎯 Target | ❌ Stopped | ⏳ Open | Up / down "
            "| P&L, $100 a trade | P&L with close-stops |\n|---|---|---|---|---|---|---|---|---|")
    lines = [f"_Updated {pd.Timestamp(asof_ms, unit='ms', tz='UTC'):%d %b %Y %H:%M} UTC. "
             "Open trades are marked at the last price._", "", head,
             _row("**All**", _stats(pairs))]
    for rule, label in (("now", "Bought at once (\"buy now\")"),
                        ("close_above", "Waited for a close above the line")):
        sub = [p for p in pairs if p[0].entry_rule == rule]
        if sub:
            lines.append(_row(label, _stats(sub)))
    lines += ["", "By list:", "", head]
    for name in dict.fromkeys(t.list for t in trades):
        lines.append(_row(name, _stats([p for p in pairs if p[0].list == name])))
    summary = "\n".join(lines)

    blocks = []
    for name in reversed(list(dict.fromkeys(t.list for t in trades))):
        sub = [p for p in pairs if p[0].list == name]
        s = _stats(sub)
        blocks += [f"### {name} — {s['triggered']}/{s['setups']} triggered, "
                   f"{s['usd']:+,.2f} $", "",
                   "| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L "
                   "| With close-stop | Best / worst | Note |",
                   "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for t, o in sub:
            if o.status in (WAITING, "error"):
                trig = _p(t.trigger) if np.isfinite(t.trigger) else "line"
                entry = f"waits for a {t.tf} close above {trig}"
                res = ICON.get(o.status, o.status)
                pnl = close = best = "—"
            else:
                entry = f"{_p(o.entry)} ({_when(o.entry_ms)})"
                res = ICON[o.status] + (f" {_when(o.exit_ms)}" if o.exit_ms else "")
                pnl = f"**{_pct(o.pnl_pct)}**"
                close = f"{ICON[o.close_status].split()[0]} {_pct(o.close_pnl_pct)}"
                best = f"{_pct(o.best_pct)} / {_pct(o.worst_pct)}"
            blocks.append(f"| {t.id} | {t.coin} | {t.tf} | {t.setup} | {entry} | {_p(t.stop)} "
                          f"| {_p(t.target)} | {res} | {pnl} | {close} | {best} | {t.note} |")
        blocks.append("")
    return {"SUMMARY": summary, "TRADES": "\n".join(blocks).rstrip()}


def write_markdown(path: str | Path, blocks: dict[str, str]) -> None:
    """Replace each ``<!-- AUTO:NAME -->`` ... ``<!-- /AUTO:NAME -->`` block."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    for name, body in blocks.items():
        pat = re.compile(rf"(<!-- AUTO:{name} -->\r?\n).*?(<!-- /AUTO:{name} -->)", re.S)
        if not pat.search(text):
            raise ValueError(f"{path} has no AUTO:{name} markers")
        text = pat.sub(lambda m: m.group(1) + body + "\n" + m.group(2), text)
    path.write_text(text, encoding="utf-8")
