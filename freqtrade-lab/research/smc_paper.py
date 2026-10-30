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

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smc_oos  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CSV = REPO / "journal" / "smc_paper.csv"
MD = REPO / "journal" / "SMC_PAPER.md"
LOG = REPO / "freqtrade-lab" / "user_data" / "logs" / "smc_scan.log"

CFG = smc_oos.FINALISTS["B_final"]
BAR = pd.Timedelta("4h")
IST = pd.Timedelta(hours=5, minutes=30)
COLS = ["id", "coin", "symbol", "side", "signal_utc", "entry_utc", "entry",
        "stop", "target", "stop_pct", "seen_utc", "seen_px", "late", "dcx",
        "status", "exit_utc", "exit_px", "why", "r", "last_utc", "last_px",
        "last_r", "exit_level", "note"]
WHY_TEXT = {"choch": "4h CHoCH", "stop": "stop", "target": "6R target",
            "time": "28 days"}


# ------------------------------------------------------------------ log
class _Tee:
    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, x):
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
    print(f"  journal: logged {'LATE ' if late else ''}{live.coin} {side} "
          f"entry {row['entry']} stop {row['stop']}")
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)


# ------------------------------------------------------------------ update
def update(results: list, now: pd.Timestamp, scan_text: str) -> None:
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
    write_md(df, scan_text, now)


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
        "late": r.late, "CoinDCX": r.dcx, "note": r.note}
        for r in opened.itertuples()]))

    doc = _put(doc, "CLOSED", _table([{
        "#": r.id, "coin": r.coin, "side": r.side, "entered": _ist(r.entry_utc),
        "exited": _ist(r.exit_utc), "entry": _d(r.entry), "exit": _d(r.exit_px),
        "why": WHY_TEXT.get(r.why, r.why), "R": f"{float(r.r):+.2f}",
        "late": r.late} for r in closed.iloc[::-1].itertuples()]))

    if scan_text is not None:
        doc = _put(doc, "SCAN", "```\n" + scan_text + "\n```")
    MD.write_text(doc, encoding="utf-8")


if __name__ == "__main__":
    write_md(load(), None, pd.Timestamp.now(tz="UTC"))
    print(f"rebuilt {MD}")
