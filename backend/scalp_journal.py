"""Scalp journal: every exhaustion scalp the scanner called, replayed as a
paper trade in R (multiples of the risk to the stop). See SCALP.md.

``journal/scalps.csv`` holds each call (side, trigger, stop, targets, score).
``python -m backend.cli scalp --journal`` adds the calls of a scan;
``python -m backend.cli scalp-journal`` replays them on Binance futures
candles and rewrites the AUTO blocks of ``journal/SCALP_JOURNAL.md``.

The plan from SCALP.md, applied the same way to every call:

* entry    "triggered": the price when the scan ran. "armed": the first
           candle of the call's timeframe that closes through the trigger
           within EXPIRY_BARS candles, else "expired". Price reaching the
           stop before that makes the call "invalid".
* exits    checked on 1-minute candles (coarser for older calls):
           - the stop before T1: -1R
           - T1: half off, the stop moves to break-even, the rest rides to T2
             for at most HOLD_BARS more candles, then closes at market
           - neither T1 nor the stop within TIME_STOP_BARS candles: closed at
             that candle's close (the scalp lost its reason)
           - a candle touching both the stop and a target counts as the stop
* result   in R; a win is R > 0. Open trades are marked at the last price.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

CSV = "journal/scalps.csv"
MD = "journal/SCALP_JOURNAL.md"
COLUMNS = ["id", "time_utc", "coin", "symbol", "tf", "side", "status", "price", "trigger",
           "stop", "t1", "t2", "t3", "score", "checks", "note"]
BAR_MIN = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
EXPIRY_BARS = 4
TIME_STOP_BARS = 8
HOLD_BARS = 16
MIN_MS = 60_000

WAITING, EXPIRED, INVALID, OPEN = "waiting", "expired", "invalid", "open"
STOPPED, BREAKEVEN, TARGET, TIMED = "stopped", "T1 then break-even", "T1 + T2", "time stop"
ICON = {WAITING: "⏳ waiting", EXPIRED: "💤 expired", INVALID: "🚫 invalid", OPEN: "⏳ open",
        STOPPED: "❌ stopped", BREAKEVEN: "🟡 T1 then break-even", TARGET: "🎯 T1 + T2",
        TIMED: "⌛ time stop"}


@dataclass
class Call:
    id: int
    time_utc: str
    coin: str
    symbol: str
    tf: str
    side: str          # short | long
    status: str        # armed | triggered (when the scan ran)
    price: float
    trigger: float
    stop: float
    t1: float
    t2: float
    t3: float
    score: int
    checks: str = ""
    note: str = ""

    @property
    def time_ms(self) -> int:
        return int(pd.Timestamp(self.time_utc, tz="UTC").value // 1_000_000)

    @property
    def bar_ms(self) -> int:
        return BAR_MIN[self.tf] * MIN_MS

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1


@dataclass
class Result:
    status: str
    entry_ms: int | None = None
    entry: float = float("nan")
    exit_ms: int | None = None
    r: float = float("nan")
    t1_hit: bool = False
    mfe: float = float("nan")      # best excursion, in R
    mae: float = float("nan")      # worst excursion, in R


def load(path: str | Path = CSV) -> list[Call]:
    df = pd.read_csv(path, dtype={"checks": str, "note": str})
    out = []
    for r in df.to_dict("records"):
        out.append(Call(**{k: (("" if v != v else v) if k in ("checks", "note") else v)
                           for k, v in r.items() if k in COLUMNS}))
    return out


def _ms(df: pd.DataFrame) -> np.ndarray:
    if not len(df):
        return np.zeros(0, np.int64)
    return (pd.DatetimeIndex(df.index).as_unit("ns").asi8 // 1_000_000).astype(np.int64)


def replay(c: Call, tf_candles: pd.DataFrame, exit_candles: pd.DataFrame, now_ms: int,
           exit_bar_ms: int = MIN_MS) -> Result:
    """Entry, exits and R of one call. Candles are oldest first, indexed by
    open time (UTC); the last one may still be forming."""
    s, bar = c.sign, c.bar_ms
    ex_open = _ms(exit_candles)
    hi, lo, cl = (exit_candles[k].to_numpy(float) for k in ("high", "low", "close"))

    # Entry.
    if c.status == "triggered":
        entry, entry_ms = float(c.price), c.time_ms
    else:
        tf_open = _ms(tf_candles)
        closes = tf_candles["close"].to_numpy(float)
        entry = entry_ms = None
        deadline = c.time_ms + EXPIRY_BARS * bar
        for o, x in zip(tf_open, closes):
            close_ms = o + bar
            if close_ms <= c.time_ms or close_ms > now_ms or close_ms > deadline:
                continue
            # The stop reached before the trigger: the setup is gone.
            seen = (ex_open >= c.time_ms) & (ex_open < close_ms)
            if seen.any() and ((s < 0 and hi[seen].max() >= c.stop)
                               or (s > 0 and lo[seen].min() <= c.stop)):
                return Result(INVALID)
            if (s < 0 and x < c.trigger) or (s > 0 and x > c.trigger):
                entry, entry_ms = float(x), int(close_ms)
                break
        if entry is None:
            return Result(EXPIRED if now_ms >= deadline else WAITING)
    risk = s * (entry - c.stop)
    if not risk > 0:
        return Result(INVALID)

    def in_r(px: float) -> float:
        return s * (px - entry) / risk

    after = ex_open >= entry_ms
    idx = np.flatnonzero(after)
    phase, realized, t1_at = 1, 0.0, None
    best, worst = 0.0, 0.0
    for i in idx:
        fav = hi[i] if s > 0 else lo[i]
        adv = lo[i] if s > 0 else hi[i]
        best, worst = max(best, in_r(fav)), min(worst, in_r(adv))
        if phase == 1:
            if (s > 0 and adv <= c.stop) or (s < 0 and adv >= c.stop):
                return Result(STOPPED, entry_ms, entry, int(ex_open[i]), -1.0, False, best, worst)
            if (s > 0 and fav >= c.t1) or (s < 0 and fav <= c.t1):
                phase, realized, t1_at = 2, 0.5 * in_r(c.t1), int(ex_open[i])
                if (s > 0 and fav >= c.t2) or (s < 0 and fav <= c.t2):
                    return Result(TARGET, entry_ms, entry, int(ex_open[i]),
                                  realized + 0.5 * in_r(c.t2), True, best, worst)
                continue
            if ex_open[i] + exit_bar_ms >= entry_ms + TIME_STOP_BARS * bar:
                return Result(TIMED, entry_ms, entry, int(ex_open[i]), in_r(cl[i]), False,
                              best, worst)
        else:
            if (s > 0 and adv <= entry) or (s < 0 and adv >= entry):
                return Result(BREAKEVEN, entry_ms, entry, int(ex_open[i]), realized, True,
                              best, worst)
            if (s > 0 and fav >= c.t2) or (s < 0 and fav <= c.t2):
                return Result(TARGET, entry_ms, entry, int(ex_open[i]),
                              realized + 0.5 * in_r(c.t2), True, best, worst)
            if ex_open[i] + exit_bar_ms >= t1_at + HOLD_BARS * bar:
                return Result(TIMED, entry_ms, entry, int(ex_open[i]),
                              realized + 0.5 * in_r(cl[i]), True, best, worst)
    last = float(cl[-1]) if len(cl) else entry
    r = in_r(last) if phase == 1 else realized + 0.5 * in_r(last)
    return Result(OPEN, entry_ms, entry, None, r, phase == 2, best, worst)


def run(calls: list[Call], fetch: Callable[[str, str, int], pd.DataFrame],
        now_ms: int) -> list[Result]:
    out = []
    for c in calls:
        age_min = (now_ms - c.time_ms) / MIN_MS
        ex_tf = next((tf for tf in ("1m", "5m", "15m") if age_min / BAR_MIN[tf] < 1400), "1h")
        try:
            tf_c = fetch(c.symbol, c.tf, int(min(1500, age_min // BAR_MIN[c.tf] + 5)))
            ex_c = fetch(c.symbol, ex_tf, int(min(1500, age_min // BAR_MIN[ex_tf] + 5)))
        except Exception:
            out.append(Result("error"))
            continue
        out.append(replay(c, tf_c, ex_c, now_ms, BAR_MIN[ex_tf] * MIN_MS))
    return out


def rows_from_setups(setups, *, first_id: int, when_utc: str, tf: str) -> list[dict]:
    """journal/scalps.csv rows for scanner setups (backend.screener.scalp)."""
    return [{"id": first_id + i, "time_utc": when_utc, "coin": s.coin, "symbol": s.symbol,
             "tf": tf, "side": s.side, "status": s.status, "price": s.price,
             "trigger": s.trigger, "stop": s.stop, "t1": s.t1, "t2": s.t2, "t3": s.t3,
             "score": s.score, "checks": " ".join(s.checks),
             "note": f"move {s.move_pct:+.1f}%, funding {s.funding_pct:.4f}%"}
            for i, s in enumerate(setups)]


# -- markdown -----------------------------------------------------------------
def _p(v: float) -> str:
    if v is None or not np.isfinite(v):
        return "—"
    return f"{v:,.2f}" if abs(v) >= 1000 else f"{v:.5g}"


def _when(ms_: int | None) -> str:
    return pd.Timestamp(ms_, unit="ms", tz="UTC").strftime("%d %b %H:%M") if ms_ else ""


def _stats(pairs: list[tuple[Call, Result]]) -> dict:
    done = [(c, r) for c, r in pairs if r.status in (STOPPED, BREAKEVEN, TARGET, TIMED, OPEN)]
    closed = [r for _, r in done if r.status != OPEN]
    rs = [r.r for _, r in done if np.isfinite(r.r)]
    return {"calls": len(pairs), "entered": len(done),
            "expired": sum(r.status in (EXPIRED, INVALID) for _, r in pairs),
            "open": sum(r.status == OPEN for _, r in done),
            "wins": sum(r.r > 0 for r in closed), "losses": sum(r.r <= 0 for r in closed),
            "t1": sum(r.t1_hit for _, r in done),
            "total_r": sum(rs), "avg_r": float(np.mean(rs)) if rs else float("nan")}


def _row(label: str, s: dict) -> str:
    wr = f"{s['wins'] / (s['wins'] + s['losses']) * 100:.0f}%" if s["wins"] + s["losses"] else "—"
    t1 = f"{s['t1'] / s['entered'] * 100:.0f}%" if s["entered"] else "—"
    avg = f"{s['avg_r']:+.2f}R" if np.isfinite(s["avg_r"]) else "—"
    return (f"| {label} | {s['calls']} | {s['entered']} | {s['expired']} | {s['open']} "
            f"| {s['wins']} / {s['losses']} | {wr} | {t1} | **{s['total_r']:+.2f}R** | {avg} |")


def render(calls: list[Call], results: list[Result], asof_ms: int) -> dict[str, str]:
    pairs = list(zip(calls, results))
    head = ("| | Calls | Entered | Expired / invalid | Open | Wins / losses | Win rate "
            "| Reached T1 | Total | Average |\n|---|---|---|---|---|---|---|---|---|---|")
    lines = [f"_Updated {pd.Timestamp(asof_ms, unit='ms', tz='UTC'):%d %b %Y %H:%M} UTC. "
             "Open trades are marked at the last price._", "", head, _row("**All**", _stats(pairs))]
    for side in ("short", "long"):
        sub = [x for x in pairs if x[0].side == side]
        if sub:
            lines.append(_row(f"{side.title()}s", _stats(sub)))
    for tf in BAR_MIN:
        sub = [x for x in pairs if x[0].tf == tf]
        if sub:
            lines.append(_row(f"{tf} calls", _stats(sub)))
    for lo_, hi_ in ((3, 3), (4, 4), (5, 99)):
        sub = [x for x in pairs if lo_ <= int(x[0].score) <= hi_]
        if sub:
            lines.append(_row(f"Score {lo_}" + ("+" if hi_ == 99 else ""), _stats(sub)))
    summary = "\n".join(lines)

    rows = ["| # | Called (UTC) | Coin | TF | Side | Score | Checks | Entry | Stop | T1 | T2 "
            "| Result | R | Best / worst |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c, r in reversed(pairs):
        entry = f"{_p(r.entry)} ({_when(r.entry_ms)})" if r.entry_ms else \
            f"{c.status} at {_p(c.trigger)}"
        res = ICON.get(r.status, r.status) + (f" {_when(r.exit_ms)}" if r.exit_ms else "")
        rr = f"**{r.r:+.2f}**" if np.isfinite(r.r) else "—"
        be = f"{r.mfe:+.1f} / {r.mae:+.1f}" if np.isfinite(r.mfe) else "—"
        rows.append(f"| {c.id} | {_when(c.time_ms)} | {c.coin} | {c.tf} | {c.side} | {c.score} "
                    f"| {c.checks} | {entry} | {_p(c.stop)} | {_p(c.t1)} | {_p(c.t2)} | {res} "
                    f"| {rr} | {be} |")
    return {"SUMMARY": summary, "TRADES": "\n".join(rows)}


def write_markdown(path: str | Path, blocks: dict[str, str]) -> None:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    for name, body in blocks.items():
        pat = re.compile(rf"(<!-- AUTO:{name} -->\r?\n).*?(<!-- /AUTO:{name} -->)", re.S)
        if not pat.search(text):
            raise ValueError(f"{path} has no AUTO:{name} markers")
        text = pat.sub(lambda m: m.group(1) + body + "\n" + m.group(2), text)
    path.write_text(text, encoding="utf-8", newline="\n")
