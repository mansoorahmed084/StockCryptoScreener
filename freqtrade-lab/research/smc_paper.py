"""Paper journal for SMC Sweep-Break: every NEW call the live scan makes, and
how each one ends, in R.

    python research/scan_smc.py --log     # what the scheduled task runs
    python research/smc_paper.py          # rebuild SMC_PAPER.md from the csv

Files:
  journal/smc_paper.csv     one row per call -- the record
  journal/SMC_PAPER.md      tables rebuilt on every run; text outside the
                            AUTO markers is kept, so notes can go there
  freqtrade-lab/user_data/logs/smc_scan.log   every run's output (gitignored)

Rules:
  * a call is logged when the scan reports it NEW. Its entry is the backtest's
    fill, the open of the 4h candle after the signal. `seen_px` is the price
    when the scan ran (about 5 minutes later), to show what a real fill costs.
  * a trade the scan reports OPEN that is not in the journal (a run was
    missed, or it was already open when logging began) is logged with
    late=yes and kept out of the on-time numbers.
  * exits come from the same simulation as the backtest, rerun each time, so
    an exit that happened while the PC was asleep is still recorded right.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smc_oos  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CSV = REPO / "journal" / "smc_paper.csv"
MD = REPO / "journal" / "SMC_PAPER.md"
# the main trade journal gets a short SMC section too (its own AUTO block);
# its long-only replay cannot price shorts or a structure exit, so SMC calls
# are kept out of trades.csv
TRADE_MD = REPO / "journal" / "TRADE_JOURNAL.md"
LOG = REPO / "freqtrade-lab" / "user_data" / "logs" / "smc_scan.log"

CFG = smc_oos.FINALISTS["B_final"]
BAR = pd.Timedelta("4h")
IST = pd.Timedelta(hours=5, minutes=30)
COLS = ["id", "coin", "symbol", "side", "signal_utc", "entry_utc", "entry",
        "stop", "target", "stop_pct", "seen_utc", "seen_px", "late", "dcx",
        "status", "exit_utc", "exit_px", "why", "r", "last_utc", "last_px",
        "last_r", "exit_level", "dcx_check", "idea", "told", "note"]
# dcx_check: the CoinDCX dry-run check of an on-time call (smc_trade.check)
# idea: the trade bot's setup id when the call was offered with a Place button
# told: which Telegram alert went out -- "" none yet, "new", "closed".
# A failed send leaves it unchanged, so the next run tries again.
WHY_TEXT = {"choch": "4h CHoCH", "stop": "stop", "target": "6R target",
            "time": "28 days"}


# ------------------------------------------------------------------ log
class _Tee:
    # a failed Telegram call logs its URL, and the URL holds the bot token
    TOKEN = re.compile(r"bot\d+:[A-Za-z0-9_-]+")

    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, x):
        x = self.TOKEN.sub("bot<redacted>", x)
        for s in self.streams:
            s.write(x)
            s.flush()

    def flush(self):
        for s in self.streams:
            s.flush()


def attach_log() -> None:
    """Send stdout/stderr to the log file too. A scheduled pythonw run has no
    console at all (sys.stdout is None), so without this it would crash."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    f = open(LOG, "a", encoding="utf-8", buffering=1)
    f.write(f"\n===== {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M:%S} UTC =====\n")
    sys.stdout = _Tee(sys.__stdout__, f)
    sys.stderr = _Tee(sys.__stderr__, f)


# ------------------------------------------------------------------ csv
def load() -> pd.DataFrame:
    if not CSV.exists():
        return pd.DataFrame(columns=COLS)
    df = pd.read_csv(CSV, dtype=str, keep_default_na=False)
    return df.reindex(columns=COLS, fill_value="")


def save(df: pd.DataFrame) -> None:
    CSV.parent.mkdir(parents=True, exist_ok=True)
    df[COLS].to_csv(CSV, index=False)


def _ts(x: pd.Timestamp) -> str:
    return pd.Timestamp(x).strftime("%Y-%m-%d %H:%M")


def _f(x: float) -> str:
    return f"{x:.10g}"


def _side(d: int) -> str:
    return "long" if d > 0 else "short"


def exit_price(entry: float, stop: float, d: int, r: float) -> float:
    """Undo the cost-netted R back to the exit price the simulation used."""
    risk = abs(entry - stop)
    c = CFG.cost
    return (r * risk + entry * (d + c)) / (d - c)


def _add(df: pd.DataFrame, live, t: dict, now: pd.Timestamp, late: bool) -> pd.DataFrame:
    side = _side(int(t["dir"]))
    entry_utc = _ts(t["entry_time"])
    have = (df.coin == live.coin) & (df.side == side) & (df.entry_utc == entry_utc)
    if have.any():
        return df
    risk = abs(t["entry"] - t["stop"])
    late = late or now > pd.Timestamp(t["entry_time"]) + BAR
    row = {c: "" for c in COLS}
    row.update(
        id=str(int(df.id.astype(int).max()) + 1 if len(df) else 1),
        coin=live.coin, symbol=live.symbol, side=side,
        signal_utc=_ts(t["sig"]), entry_utc=entry_utc,
        entry=_f(t["entry"]), stop=_f(t["stop"]),
        target=_f(t["entry"] + t["dir"] * CFG.tp_r * risk),
        stop_pct=f"{100 * t['risk_pct']:.2f}",
        seen_utc=_ts(now), seen_px=_f(live.last),
        late="yes" if late else "no", dcx="yes" if live.dcx else "no",
        status="open")
    lvl = t.get("choch_level", float("nan"))
    if lvl is not None and np.isfinite(lvl):
        row["exit_level"] = _f(lvl)
    print(f"  journal: logged {'LATE ' if late else ''}{live.coin} {side} "
          f"entry {row['entry']} stop {row['stop']}")
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)


# ------------------------------------------------------------------ update
def update(results: list, now: pd.Timestamp, scan_text: str,
           watching: list[dict] | None = None, telegram: "Telegram | None" = None,
           bot: "Bot | None" = None) -> None:
    import scan_smc   # here, not at the top: scan_smc imports this module

    df = load()
    by = {live.coin: (live, ev) for live, _vol, ev in results}
    for coin, (live, ev) in by.items():
        if ev["new"]:
            df = _add(df, live, ev["new"], now, late=False)
        if ev["open"]:
            df = _add(df, live, ev["open"], now, late=True)

    for i in df.index[df.status == "open"]:
        coin = df.at[i, "coin"]
        if coin not in by:       # fell under the volume floor: fetch it alone
            res, _ = scan_smc.scan(coins=[coin], now=now, workers=1)
            if res:
                by[coin] = (res[0][0], res[0][2])
        if coin not in by:
            df.at[i, "note"] = f"no data at {_ts(now)}"
            continue
        live, ev = by[coin]
        d = 1 if df.at[i, "side"] == "long" else -1
        entry_ts = pd.Timestamp(df.at[i, "entry_utc"], tz="UTC")
        entry, stop = float(df.at[i, "entry"]), float(df.at[i, "stop"])
        risk = abs(entry - stop)
        tr = ev["trades"]
        m = tr[(tr.entry_time == entry_ts) & (tr.dir == d)] if tr is not None else []
        if len(m) and m.iloc[0].why != "data_end":
            t = m.iloc[0]
            df.loc[i, ["status", "exit_utc", "exit_px", "why", "r"]] = [
                "closed", _ts(t.exit_time), _f(exit_price(entry, stop, d, t.r)),
                t.why, f"{t.r:.3f}"]
            print(f"  journal: closed {coin} {df.at[i, 'side']} "
                  f"{WHY_TEXT.get(t.why, t.why)} {t.r:+.2f}R")
        elif len(m) or entry_ts == live.ltf.index[-1]:
            df.at[i, "note"] = ""
        else:
            df.at[i, "note"] = f"not in the simulation at {_ts(now)}"
        if df.at[i, "status"] == "open":
            df.loc[i, ["last_utc", "last_px", "last_r"]] = [
                _ts(now), _f(live.last), f"{d * (live.last - entry) / risk:.3f}"]
            o = ev["open"]
            if o and pd.Timestamp(o["entry_time"]) == entry_ts and np.isfinite(o["choch_level"]):
                df.at[i, "exit_level"] = _f(o["choch_level"])
    save(df)
    if bot is not None:
        bot.handle_closed(df)
        bot.handle_new(df, now)
        save(df)
    if telegram is not None:
        tell(df, telegram, bot)
        save(df)
    write_md(df, scan_text, now)
    write_trade_journal(df, now, watching)


# ------------------------------------------------------------------ CoinDCX
class Bot:
    """The CoinDCX side of a fresh on-time call (smc_trade.py): a dry-run check
    and, with `offer`, a Place-button setup in the live bot. Only calls whose
    entry candle is still forming are touched; an old call is never offered."""

    def __init__(self, check: bool = True, offer: bool = False, risk_pct: float = 1.0,
                 risk_cap_inr: float = 500.0, leverage: int = 5, auto: bool = False):
        import smc_trade
        self.t = smc_trade
        # auto (the owner's switch): place fresh calls with no tap, and close
        # the bot's SMC positions on the CHoCH / 28-day exits
        self.check, self.offer, self.auto = check, offer and not auto, auto
        self.risk_pct, self.risk_cap_inr, self.leverage = risk_pct, risk_cap_inr, leverage
        self.dry, self.live, self.settings = smc_trade.managers(dry_only=not (offer or auto))

    @property
    def risk_inr(self) -> float:
        """risk_pct of the free futures balance, capped (the backtest risks
        0.5-1% of equity a trade; a fixed rupee amount does not scale)."""
        free = self.dry.free_inr() or 0.0
        return round(min(self.risk_cap_inr, free * self.risk_pct / 100.0), 2)

    def handle_new(self, df: pd.DataFrame, now: pd.Timestamp) -> None:
        for i in df.index:
            r = df.loc[i]
            fresh = (r.status == "open" and r.late == "no"
                     and pd.Timestamp(r.entry_utc, tz="UTC") + BAR > now)
            if not fresh:
                continue
            if self.check and not r.dcx_check:
                try:
                    df.at[i, "dcx_check"] = self.t.check(self.dry, r, self.risk_inr,
                                                         self.leverage)
                except Exception as exc:          # a read failure must not stop the scan
                    df.at[i, "dcx_check"] = f"check failed: {exc}"[:200]
                print(f"  coindcx: {r.coin} {r.side}: {df.at[i, 'dcx_check']}")
            if self.auto and not r.idea and self.live is not None:
                try:
                    with self.live.lock:
                        idea_id, _tid, msg = self.t.auto_open(
                            self.live, self.settings, r, self.risk_inr, self.leverage)
                except Exception as exc:          # retried next run if still fresh
                    print(f"  coindcx: {r.coin} {r.side}: auto trade failed: {exc}")
                    continue
                df.at[i, "idea"] = str(idea_id) if idea_id else "-"
                df.at[i, "note"] = msg
                print(f"  coindcx: {r.coin} {r.side}: {msg}")
            elif self.offer and not r.idea and self.live is not None:
                try:
                    idea_id, msg = self.t.offer(self.live, self.settings, r,
                                                self.risk_inr, self.leverage)
                except Exception as exc:          # retried next run if still fresh
                    idea_id, msg = None, f"offer failed: {exc}"[:200]
                    print(f"  coindcx: {r.coin} {r.side}: {msg}")
                    continue
                df.at[i, "idea"] = str(idea_id) if idea_id else "-"
                df.at[i, "note"] = msg
                print(f"  coindcx: {r.coin} {r.side}: {msg}")

    def handle_closed(self, df: pd.DataFrame) -> None:
        """Auto mode: close the bot's position from a call whose paper trade
        ended on the 4h CHoCH or the 28-day limit (the exchange stop and target
        handle the rest). Retried every run while the position is still held."""
        if not self.auto or self.live is None:
            return
        for i in df.index[(df.status == "closed") & df.why.isin(self.t.AUTO_EXITS)]:
            r = df.loc[i]
            try:
                with self.live.lock:
                    msg = self.t.auto_close(self.live, r)
            except Exception as exc:              # retried next run
                print(f"  coindcx: {r.coin} {r.side}: auto close failed: {exc}")
                df.at[i, "note"] = f"auto close failed: {exc}"[:200]
                continue
            if msg:
                df.at[i, "note"] = msg
                print(f"  coindcx: {r.coin} {r.side}: {msg}")

    def held(self, r) -> dict | None:
        """The bot's open position placed from this call, if any."""
        if self.live is None or not r.idea or r.idea == "-":
            return None
        try:
            return self.t.held_from_idea(self.live, r.idea)
        except Exception:
            return None


# ------------------------------------------------------------------ telegram
class Telegram:
    """Plain-text messages through the trade bot (.env TELEGRAM_BOT_TOKEN and
    TELEGRAM_CHAT_ID). No buttons and no order path: sendMessage only.
    `dry` prints the message instead of sending it."""

    def __init__(self, dry: bool = False):
        self.dry = dry
        self.bot = None
        if not dry:
            import harness  # noqa: F401  (puts the repo root on sys.path)
            from backend.alerts.telegram import telegram_from_env
            self.bot = telegram_from_env()
            if self.bot is None:
                print("  telegram: no TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env")
        self.sent: list[str] = []

    def send(self, text: str) -> bool:
        if self.dry:
            print("  telegram (dry run):\n    " + text.replace("\n", "\n    "))
            self.sent.append(text)
            return True
        if self.bot is None:
            return False
        # plain text on purpose: coin names with _ or * would break Markdown
        ok = self.bot._call("sendMessage", chat_id=self.bot.chat_id, text=text,
                            disable_web_page_preview=True) is not None
        print(f"  telegram: {'sent' if ok else 'FAILED'}: {text.splitlines()[0]}")
        if ok:
            self.sent.append(text)
        return ok


def _num(x: str) -> str:
    return _d(x) if x else "?"


def new_message(r) -> str:
    d = 1 if r.side == "long" else -1
    lines = [f"SMC NEW: {r.side.upper()} {r.coin} ({r.symbol})",
             f"Entry {_num(r.entry)} (4h open {_ist(r.entry_utc)} IST)",
             f"Stop {_num(r.stop)} ({float(r.stop_pct):.1f}% away)",
             f"Target 6R {_num(r.target)}"]
    if r.exit_level:
        lines.append(f"Exit early if a 4h candle closes {'below' if d > 0 else 'above'} "
                     f"{_num(r.exit_level)}")
    if r.seen_px:
        moved = d * (float(r.seen_px) - float(r.entry)) / abs(float(r.entry) - float(r.stop))
        lines.append(f"Price at the scan: {_num(r.seen_px)} ({moved:+.2f}R)")
    lines.append(f"On CoinDCX futures: {r.dcx}")
    note = str(r.get("note", "") or "")
    if note.startswith(("traded", "not traded", "dry run")):
        lines.append(f"AUTO: {note}")          # the owner's auto mode
    else:
        lines.append("Paper trade. No order was placed.")
    return "\n".join(lines)


def close_message(r, df: pd.DataFrame) -> str:
    closed = df[(df.status == "closed") & (df.late == "no")]
    rs = closed.r.astype(float)
    tally = (f"On-time closed so far: {len(rs)}, win {100 * (rs > 0).mean():.0f}%, "
             f"avg {rs.mean():+.2f}R" if len(rs) else "")
    lines = [f"SMC CLOSED: {r.side.upper()} {r.coin} {float(r.r):+.2f}R",
             f"Exit: {WHY_TEXT.get(r.why, r.why)} at {_num(r.exit_px)} ({_ist(r.exit_utc)} IST)",
             f"Entry {_num(r.entry)} ({_ist(r.entry_utc)} IST), stop {_num(r.stop)}"]
    if r.late == "yes":
        lines.append("This trade was logged late, so it is not in the on-time numbers.")
    if tally:
        lines.append(tally)
    note = str(r.get("note", "") or "")
    if note.startswith(("auto-closed", "auto close failed")):
        lines.append(f"AUTO: {note}")          # the owner's auto mode
    else:
        lines.append("Paper trade (R from the backtest rules).")
    return "\n".join(lines)


def tell(df: pd.DataFrame, tg: Telegram, bot: "Bot | None" = None) -> None:
    """Send what has not been sent yet: a NEW alert for each on-time call that
    is still open, and a CLOSED alert for every logged trade that ended."""
    for i in df.index:
        r = df.loc[i]
        if r.status == "closed" and r.told != "closed":
            text = close_message(r, df)
            held = bot.held(r) if bot is not None else None
            if held:
                text = (f"ACTION: you hold {held['pair']} from this call (bot trade "
                        f"#{held['id']}). The strategy exits here: close it in the "
                        f"CoinDCX app or with `trade close {held['pair']}`.\n" + text)
            if tg.send(text):
                df.at[i, "told"] = "closed"
        elif r.status == "open" and r.told == "" and r.late == "no":
            if tg.send(new_message(r)):
                df.at[i, "told"] = "new"


# ------------------------------------------------------------------ report
def _ist(s: str) -> str:
    if not s:
        return ""
    return (pd.Timestamp(s) + IST).strftime("%d %b %H:%M")


def _stats(c: pd.DataFrame) -> str:
    if len(c) == 0:
        return "none yet"
    r = c.r.astype(float)
    return (f"{len(c)} trades, win {100 * (r > 0).mean():.0f}%, "
            f"avg {r.mean():+.2f}R, total {r.sum():+.1f}R "
            f"(= {0.5 * r.sum():+.1f}% of an account at 0.5% risk)")


def _d(x: str) -> str:
    """A csv price, shortened for reading."""
    return f"{float(x):.6g}" if x else ""


def _table(rows: list[dict]) -> str:
    if not rows:
        return "_none_"
    head = list(rows[0])
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(r[h]) for h in head) + " |" for r in rows]
    return "\n".join(out)


TEMPLATE = """# SMC Sweep-Break — paper trades

Every call the live scan makes, logged automatically every 4 hours by
`freqtrade-lab/research/scan_smc.py --log`. Rules and backtest:
[STRATEGY_SMC_SweepBreak.md](../freqtrade-lab/research/STRATEGY_SMC_SweepBreak.md).
Times are IST. Entry = the backtest's fill (the 4h open after the signal);
"seen" = the price when the scan ran. "Late" = logged after its entry candle
had closed (a missed run, or open before logging began); late trades are
kept out of the on-time numbers.

Backtest expectation, for comparison: about 38% wins, +0.25R a trade, and
losing streaks of 10+ are normal. Judge it after 30+ closed on-time trades.

## Notes

_Hand-written notes go here. The scan never changes this section._

<!-- AUTO:SUMMARY -->
<!-- /AUTO:SUMMARY -->

## Open trades

<!-- AUTO:OPEN -->
<!-- /AUTO:OPEN -->

## Closed trades

<!-- AUTO:CLOSED -->
<!-- /AUTO:CLOSED -->

## Last scan

<!-- AUTO:SCAN -->
<!-- /AUTO:SCAN -->
"""


def _put(doc: str, name: str, body: str) -> str:
    a, b = f"<!-- AUTO:{name} -->", f"<!-- /AUTO:{name} -->"
    i, j = doc.index(a) + len(a), doc.index(b)
    return doc[:i] + "\n" + body.strip() + "\n" + doc[j:]


def write_md(df: pd.DataFrame, scan_text: str | None, now: pd.Timestamp) -> None:
    doc = MD.read_text(encoding="utf-8") if MD.exists() else TEMPLATE
    closed = df[df.status == "closed"]
    on_time = closed[closed.late == "no"]
    opened = df[df.status == "open"]
    summary = [
        f"_Updated {(now + IST):%d %b %Y %H:%M} IST._",
        "",
        f"- Calls logged: {len(df)} ({int((df.late == 'no').sum())} on time, "
        f"{int((df.late == 'yes').sum())} late). Open now: {len(opened)}.",
        f"- **Closed, on time:** {_stats(on_time)}",
        f"- Closed, all: {_stats(closed)}",
    ]
    for side in ("long", "short"):
        s = on_time[on_time.side == side]
        if len(s):
            summary.append(f"- On time, {side}s: {_stats(s)}")
    if len(on_time):
        seen = on_time[on_time.seen_px != ""]
        d = np.where(seen.side == "long", 1, -1)
        slip = d * (seen.seen_px.astype(float) - seen.entry.astype(float)) / (
            seen.entry.astype(float) - seen.stop.astype(float)).abs()
        summary.append(f"- Price had moved {slip.mean():+.2f}R on average by the "
                       f"time the scan ran (+ = in the trade's favour).")
    doc = _put(doc, "SUMMARY", "\n".join(summary))

    doc = _put(doc, "OPEN", _table([{
        "#": r.id, "coin": r.coin, "side": r.side, "entered": _ist(r.entry_utc),
        "entry": _d(r.entry), "stop": _d(r.stop), "6R target": _d(r.target),
        "exit if a 4h candle closes": (("below " if r.side == "long" else "above ")
                                       + _d(r.exit_level)) if r.exit_level else "next run",
        "now": _d(r.last_px), "now R": f"{float(r.last_r):+.2f}" if r.last_r else "",
        "late": r.late, "CoinDCX": r.dcx, "CoinDCX dry run": r.dcx_check, "note": r.note}
        for r in opened.itertuples()]))

    doc = _put(doc, "CLOSED", _table([{
        "#": r.id, "coin": r.coin, "side": r.side, "entered": _ist(r.entry_utc),
        "exited": _ist(r.exit_utc), "entry": _d(r.entry), "exit": _d(r.exit_px),
        "why": WHY_TEXT.get(r.why, r.why), "R": f"{float(r.r):+.2f}",
        "late": r.late} for r in closed.iloc[::-1].itertuples()]))

    if scan_text is not None:
        doc = _put(doc, "SCAN", "```\n" + scan_text + "\n```")
    MD.write_text(doc, encoding="utf-8")


SECTION = """## SMC Sweep-Break calls (4h, long and short)

Logged automatically every 4 hours by the SMC scan. These are kept out of
trades.csv: that replay is long-only with a fixed stop and target, and these
trades are mostly shorts that exit on the 4h structure. Full detail and the
last scan: [SMC_PAPER.md](SMC_PAPER.md).

<!-- AUTO:SMC -->
<!-- /AUTO:SMC -->

"""


def write_trade_journal(df: pd.DataFrame, now: pd.Timestamp,
                        watching: list[dict] | None) -> None:
    """Rewrite the AUTO:SMC block in TRADE_JOURNAL.md (add the section once)."""
    if not TRADE_MD.exists():
        return
    doc = TRADE_MD.read_text(encoding="utf-8")
    if "<!-- AUTO:SMC -->" not in doc:
        anchor = "## What works and what doesn't"
        if anchor in doc:
            doc = doc.replace(anchor, SECTION + anchor, 1)
        else:
            doc = doc.rstrip() + "\n\n" + SECTION
    closed = df[df.status == "closed"]
    on_time = closed[closed.late == "no"]
    opened = df[df.status == "open"]
    lines = [f"_Updated {(now + IST):%d %b %Y %H:%M} IST._", "",
             f"- Calls: {len(df)} ({int((df.late == 'no').sum())} on time). "
             f"Open: {len(opened)}. Closed on time: {_stats(on_time)}", ""]
    rows = [{"#": r.id, "coin": r.coin, "side": r.side,
             "entered": _ist(r.entry_utc), "entry": _d(r.entry),
             "stop": _d(r.stop), "6R target": _d(r.target),
             "status": (f"open, now {float(r.last_r):+.2f}R" if r.status == "open" and r.last_r
                        else "open" if r.status == "open"
                        else f"{WHY_TEXT.get(r.why, r.why)} {float(r.r):+.2f}R "
                             f"({_ist(r.exit_utc)})"),
             "late": r.late}
            for r in df.iloc[::-1].head(25).itertuples()]
    lines.append(_table(rows))
    if len(df) > 25:
        lines.append(f"\n_Last 25 of {len(df)}; all in SMC_PAPER.md._")
    if watching:
        lines += ["", "**Watching** (would trigger at the next 4h close):", ""]
        lines += [f"- {w['coin']} {w['side'].lower()}: {w['trigger']} "
                  f"(now {w['now']}, stop {w['stop']}, {w['stop %']}%)" for w in watching]
    doc = _put(doc, "SMC", "\n".join(lines))
    TRADE_MD.write_text(doc, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    # rebuild both pages from the csv, e.g. after pulling it from the VM
    _now = pd.Timestamp.now(tz="UTC")
    write_md(load(), None, _now)
    write_trade_journal(load(), _now, None)
    print(f"rebuilt {MD} and the SMC block of {TRADE_MD}")
