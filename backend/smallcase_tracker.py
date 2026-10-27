"""Smallcase tracker: the long-term portfolio (smallcases and mutual funds),
checked once a month.

``journal/smallcase_buys.csv`` holds each buy (date, id, amount in Rs). The id
is a smallcase scid, or ``MF_<AMFI code>`` for a mutual fund.
``python -m backend.smallcase_tracker`` values every buy on the public
smallcase index or the fund's NAV (mfapi.in) and rewrites the AUTO blocks of
``journal/SMALLCASE_TRACKER.md``.

* units    a buy of Rs A on day D gets A / index(D) units; the index (or NAV) on
           D is the last published point on or before D (the first if D is older)
* value    units x today's index. For a smallcase the real account differs a
           little: whole shares, charges and the manager's rebalances are not
           modelled
* drift    a holding's share of the total value minus its target share
* alerts   drift over DRIFT_FIX: put new money into the light ones first
           (no sale, no tax); drift over DRIFT_SELL: also trim the heavy one.
           A manager rebalance due in REBALANCE_SOON_DAYS days, or done in
           the last REBALANCE_RECENT_DAYS days, is a reminder to accept it
* split    the next SIP goes to the holdings below target, in proportion
           to how far below they are; with no gap it follows the targets

Data only. No orders are placed; the user buys and sells in Zerodha.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

CSV = "journal/smallcase_buys.csv"
MD = "journal/SMALLCASE_TRACKER.md"
API = "https://api.smallcase.com/smallcases"
MF_API = "https://api.mfapi.in/mf"
MF = "MF_"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# id -> (name, target share of the portfolio); MF_<code> is a mutual fund
PORTFOLIO = {
    "SCMO_0015": ("Safe Haven Model", 1 / 3),
    "SCTR_0008": ("Metal Tracker", 1 / 3),
    "MF_118632": ("Nippon India Large Cap Fund (Direct, Growth)", 1 / 3),
}
SIP = 50_000
DRIFT_FIX = 0.05
DRIFT_SELL = 0.10
REBALANCE_SOON_DAYS = 7
REBALANCE_RECENT_DAYS = 30


@dataclass
class Buy:
    date: date
    scid: str
    amount: float


@dataclass
class Info:
    scid: str
    name: str
    index: float                    # today's index level ("price" in the history)
    returns: dict[str, float]       # 1M, 3M, 1Y absolute; 3Y, 5Y CAGR
    last_rebalance: date | None
    next_rebalance: date | None


@dataclass
class Line:
    scid: str
    name: str
    invested: float
    value: float
    target: float
    weight: float = 0.0

    @property
    def gain(self) -> float:
        return self.value / self.invested - 1 if self.invested else 0.0

    @property
    def drift(self) -> float:
        return self.weight - self.target


def load(path: str | Path | None = None) -> list[Buy]:
    p = Path(path or CSV)
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        return [Buy(date.fromisoformat(r["date"]), (r.get("id") or r.get("scid") or "").strip(),
                    float(r["amount"]))
                for r in csv.DictReader(fh) if r.get("date") and not r["date"].startswith("#")]


def _day(s: str | None) -> date | None:
    return datetime.fromisoformat(s[:10]).date() if s else None


def _back(history: dict[date, float], years: float, cagr: bool) -> float | None:
    """Return over the last `years` (CAGR when asked), None if the history is shorter."""
    end, last = next(reversed(history.items()))
    start = end - timedelta(days=round(365.25 * years))
    if start < next(iter(history)):
        return None
    r = last / index_on(history, start)
    return r ** (1 / years) - 1 if cagr else r - 1


def mf_info(fid: str, history: dict[date, float]) -> Info:
    """A fund has no manager rebalance; its returns come from the NAV history."""
    return Info(fid, PORTFOLIO[fid][0], next(reversed(history.values())),
                {"1M": _back(history, 1 / 12, False), "3M": _back(history, 0.25, False),
                 "1Y": _back(history, 1, False), "3Y": _back(history, 3, True),
                 "5Y": _back(history, 5, True)}, None, None)


def fetch_mf_history(fid: str, client: httpx.Client) -> dict[date, float]:
    data = client.get(f"{MF_API}/{fid.removeprefix(MF)}").json()["data"]
    return dict(sorted((datetime.strptime(x["date"], "%d-%m-%Y").date(), float(x["nav"]))
                       for x in data if float(x["nav"]) > 0))


def fetch_info(scid: str, client: httpx.Client) -> Info:
    d = client.get(f"{API}/smallcase", params={"scid": scid}).json()["data"]
    s, r = d["stats"], d["stats"]["returns"]
    ratios = s.get("ratios") or {}
    return Info(scid, d["info"]["name"], s["indexValue"],
                {"1M": r.get("monthly"), "3M": r.get("quarterly"), "1Y": r.get("yearly"),
                 "3Y": ratios.get("cagr3y"), "5Y": ratios.get("cagr5y")},
                _day(d["info"].get("lastRebalanced")), _day(d["info"].get("nextUpdate")))


def fetch_history(scid: str, client: httpx.Client) -> dict[date, float]:
    """Index level by day, finest points first (1m daily, 1y every few days, max monthly)."""
    out: dict[date, float] = {}
    for dur in ("max", "1y", "1m"):
        d = client.get(f"{API}/historical", params={"scid": scid, "benchmarkId": ".NIFTY100",
                                                   "base": 100, "duration": dur}).json()["data"]
        out.update({_day(p["date"]): p["price"] for p in d["points"]})
    return dict(sorted(out.items()))


def index_on(history: dict[date, float], day: date) -> float:
    before = [v for d, v in history.items() if d <= day]
    return before[-1] if before else next(iter(history.values()))


def value(buys: list[Buy], infos: dict[str, Info],
          histories: dict[str, dict[date, float]]) -> list[Line]:
    lines = {s: Line(s, n, 0.0, 0.0, t) for s, (n, t) in PORTFOLIO.items()}
    for b in buys:
        if b.scid not in lines:
            raise ValueError(f"{b.scid} in {CSV} is not in PORTFOLIO")
        units = b.amount / index_on(histories[b.scid], b.date)
        lines[b.scid].invested += b.amount
        lines[b.scid].value += units * infos[b.scid].index
    total = sum(l.value for l in lines.values())
    for l in lines.values():
        l.weight = l.value / total if total else 0.0
    return list(lines.values())


def split(lines: list[Line], amount: float) -> dict[str, float]:
    """Next SIP: fill the gaps to target after this money, else follow the targets."""
    total = sum(l.value for l in lines) + amount
    gaps = {l.scid: max(l.target * total - l.value, 0.0) for l in lines}
    need = sum(gaps.values())
    if need <= 0:
        return {l.scid: amount * l.target for l in lines}
    return {s: amount * g / need for s, g in gaps.items()}


def alerts(lines: list[Line], infos: dict[str, Info], today: date) -> list[str]:
    out = []
    if sum(l.value for l in lines) > 0:
        heavy = [l for l in lines if l.drift > DRIFT_SELL]
        for l in lines:
            if abs(l.drift) > DRIFT_FIX:
                side = "above" if l.drift > 0 else "below"
                out.append(f"⚖️ **{l.name}** is {abs(l.drift) * 100:.1f} points {side} its target "
                           f"({l.weight * 100:.1f}% vs {l.target * 100:.1f}%).")
        if any(abs(l.drift) > DRIFT_FIX for l in lines):
            out.append("➡️ Put the next SIP into the holdings below target (see *Next SIP*). "
                       "This fixes the mix with no sale and no tax.")
        for l in heavy:
            out.append(f"✂️ **{l.name}** is more than {DRIFT_SELL * 100:.0f} points heavy. New money "
                       f"alone is slow to fix this. Think about selling Rs {l.drift * sum(x.value for x in lines):,.0f} "
                       "of it. A sale has tax: 20% on gains held under 1 year, 12.5% after.")
    for s, i in infos.items():
        name = PORTFOLIO[s][0]
        if i.next_rebalance and 0 <= (i.next_rebalance - today).days <= REBALANCE_SOON_DAYS:
            out.append(f"🔁 **{name}**: the manager's rebalance is due on {i.next_rebalance:%d %b %Y}. "
                       "Accept it in Zerodha smallcase when it shows up.")
        elif i.last_rebalance and 0 <= (today - i.last_rebalance).days <= REBALANCE_RECENT_DAYS:
            out.append(f"🔁 **{name}**: the manager rebalanced on {i.last_rebalance:%d %b %Y}. "
                       "If Zerodha still shows it as pending, accept it.")
    return out or ["✅ Nothing to do. The mix is within the limits and no rebalance is due."]


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:+.1f}%"


def render(lines: list[Line], infos: dict[str, Info], today: date, sip: float) -> dict[str, str]:
    inv, val = sum(l.invested for l in lines), sum(l.value for l in lines)
    summary = [f"_Updated {today:%d %b %Y}. Smallcase values use the public smallcase index, "
               "so the real account can differ a little. Fund values use the NAV._", ""]
    if inv:
        summary.append(f"**Invested:** Rs {inv:,.0f} · **Value:** Rs {val:,.0f} · "
                       f"**Gain:** Rs {val - inv:,.0f} ({_pct(val / inv - 1)})")
    else:
        summary.append(f"**No buys yet.** Add each buy to [smallcase_buys.csv](smallcase_buys.csv).")
    mix = ["| Holding | Invested | Value | Gain | Share now | Target | Drift |",
           "|---|---|---|---|---|---|---|"]
    for l in lines:
        mix.append(f"| {l.name} | Rs {l.invested:,.0f} | Rs {l.value:,.0f} | {_pct(l.gain if l.invested else None)} "
                   f"| {l.weight * 100:.1f}% | {l.target * 100:.1f}% "
                   f"| {f'{l.drift * 100:+.1f} pts' if inv else '—'} |")
    ret = ["| Holding | 1M | 3M | 1Y | 3Y CAGR | 5Y CAGR | Last rebalance | Next rebalance |",
           "|---|---|---|---|---|---|---|---|"]
    for s, i in infos.items():
        r = i.returns
        ret.append(f"| {PORTFOLIO[s][0]} | {_pct(r['1M'])} | {_pct(r['3M'])} | {_pct(r['1Y'])} "
                   f"| {_pct(r['3Y'])} | {_pct(r['5Y'])} "
                   f"| {i.last_rebalance or '—'} | {i.next_rebalance or '—'} |")
    nxt = [f"How to split the next Rs {sip:,.0f}, to move the mix back to target:", "",
           "| Holding | Amount |", "|---|---|"]
    nxt += [f"| {PORTFOLIO[s][0]} | Rs {a:,.0f} |" for s, a in split(lines, sip).items()]
    return {"SUMMARY": "\n".join(summary), "ALERTS": "\n".join(f"- {a}" for a in alerts(lines, infos, today)),
            "MIX": "\n".join(mix), "RETURNS": "\n".join(ret), "NEXT": "\n".join(nxt)}


def write_markdown(path: str | Path, blocks: dict[str, str]) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    for name, body in blocks.items():
        pat = re.compile(rf"(<!-- AUTO:{name} -->\r?\n).*?(<!-- /AUTO:{name} -->)", re.S)
        if not pat.search(text):
            raise ValueError(f"{path} has no AUTO:{name} markers")
        text = pat.sub(lambda m: m.group(1) + body + "\n" + m.group(2), text)
    p.write_text(text, encoding="utf-8")


def run(today: date | None = None, sip: float = SIP,
        client_factory: Callable[[], httpx.Client] | None = None) -> dict[str, str]:
    today = today or date.today()
    buys = load()
    with (client_factory or (lambda: httpx.Client(headers=HEADERS, timeout=30)))() as c:
        funds = {s: fetch_mf_history(s, c) for s in PORTFOLIO if s.startswith(MF)}
        infos = {s: mf_info(s, funds[s]) if s in funds else fetch_info(s, c) for s in PORTFOLIO}
        histories = {s: funds.get(s) or fetch_history(s, c) for s in {b.scid for b in buys}}
    blocks = render(value(buys, infos, histories), infos, today, sip)
    write_markdown(MD, blocks)
    return blocks


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sip", type=float, default=SIP, help="next monthly amount to split (Rs)")
    blocks = run(sip=ap.parse_args(argv).sip)
    sys.stdout.reconfigure(encoding="utf-8")   # the alerts carry emoji; Windows consoles default to cp1252
    print(blocks["SUMMARY"], "", blocks["ALERTS"], sep="\n")


if __name__ == "__main__":
    main()
