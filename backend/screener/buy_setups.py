"""Rank the scanner's buy setups and pick the ones the trade journal tracks.

The same rules every day, so the journal tests the scanner rather than a mood:

* a bullish pattern that just broke up (a "fresh" break, bought ``now``) or
  sits within 1.5% under its line (bought on a ``close_above`` the line);
* on 1h, 4h or 1d (15m setups were the noisiest in the first journal days);
* the daily and the 4h trend both up (close > EMA 20 > EMA 50);
* no bearish setup on the same coin at the same or a higher timeframe;
* at least 5% of room to the nearest daily supply (or none above);
* reward to the target at least twice the risk to the stop;
* one setup per coin, best score first; at most ``n`` of each kind, skipping
  a coin / timeframe / pattern the journal already took in the last days.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from . import pattern_scan as ps
from . import patterns as pt

TF_WEIGHT = {"15m": 1, "1h": 2, "4h": 3, "1d": 4}
PICK_TFS = ("1h", "4h", "1d")
MIN_ROOM_PCT = 5.0
MIN_RR = 2.0


def trend(close: pd.Series) -> str:
    e20 = close.ewm(span=20).mean().iloc[-1]
    e50 = close.ewm(span=50).mean().iloc[-1]
    p = close.iloc[-1]
    return "up" if p > e20 > e50 else "down" if p < e20 < e50 else "mixed"


def rank(scan: pd.DataFrame, trends: dict[str, tuple[str, str]]) -> pd.DataFrame:
    """Every live bullish setup with its entry kind, reward / risk and score.
    ``trends`` maps a symbol to its (daily, 4h) trend."""
    df = scan.copy()
    df["t1d"] = df["symbol"].map(lambda s: trends.get(s, ("?", "?"))[0])
    df["t4h"] = df["symbol"].map(lambda s: trends.get(s, ("?", "?"))[1])
    fresh = df["setup"].str.contains("fresh")
    near = df["setup"].str.startswith("Near breakout")
    bull = df["pattern"].isin(ps.BULLISH) & (
        (df["status"].isin(["broke up", "confirmed"]) & fresh) |
        (df["status"].isin(["inside", "forming"]) & near))
    bear = df["pattern"].isin(ps.BEARISH) & (
        (df["status"].isin(["broke down", "confirmed"]) & fresh) |
        (df["status"].isin(["inside", "forming"]) & near))
    bear_tf = df[bear].groupby("coin")["timeframe"].agg(lambda s: max(TF_WEIGHT[t] for t in s))

    b = df[bull].copy()
    b["kind"] = np.where(b["status"].isin(["broke up", "confirmed"]), "now", "close_above")
    b["reward_pct"] = (b["target_up"] / b["price"] - 1) * 100
    b["risk_pct"] = (1 - b["down_level"] / b["price"]) * 100
    b["rr"] = b["reward_pct"] / b["risk_pct"].where(b["risk_pct"] > 0)
    b["conflict"] = [c in bear_tf.index and bear_tf[c] >= TF_WEIGHT[tf]
                     for c, tf in zip(b["coin"], b["timeframe"])]
    tfs = b.groupby("coin")["timeframe"].agg(lambda s: len(set(s)))

    def score(r) -> float:
        s = TF_WEIGHT[r.timeframe]
        s += {"up": 2, "down": -2}.get(r.t1d, 0) + {"up": 1, "down": -2}.get(r.t4h, 0)
        room = r.zone_above_pct
        s += 1 if not np.isfinite(room) or room >= MIN_ROOM_PCT else (-2 if room < 2 else 0)
        if np.isfinite(r.rr):
            s += 1 if r.rr >= MIN_RR else (-1 if r.rr < 1 else 0)
        s -= 3 if r.conflict else 0
        return s + tfs[r.coin] - 1

    b["score"] = b.apply(score, axis=1) if len(b) else []
    return b.sort_values(["score", "rr"], ascending=False).reset_index(drop=True)


def pick(ranked: pd.DataFrame, n: int = 5,
         taken: set[tuple[str, str, str]] = frozenset()) -> pd.DataFrame:
    """The setups that pass every rule in the module docstring."""
    r = ranked
    if r.empty:
        return r
    ok = (r["timeframe"].isin(PICK_TFS) & (r["t1d"] == "up") & (r["t4h"] == "up")
          & ~r["conflict"]
          & (~np.isfinite(r["zone_above_pct"]) | (r["zone_above_pct"] >= MIN_ROOM_PCT))
          & (r["rr"] >= MIN_RR)
          & np.isfinite(r["down_level"]) & np.isfinite(r["target_up"]))
    ok &= np.array([(c, tf, p) not in taken
                    for c, tf, p in zip(r["coin"], r["timeframe"], r["pattern"])], dtype=bool)
    good = r[ok].drop_duplicates("coin")
    return pd.concat([good[good["kind"] == k].head(n) for k in ("now", "close_above")])


def journal_rows(picks: pd.DataFrame, fetch: Callable[[str, str, int], pd.DataFrame],
                 *, first_id: int, day: str, when_utc: str, list_name: str) -> list[dict]:
    """Rows for journal/trades.csv. A ``close_above`` pick is re-read from
    fresh candles so the journal follows the pattern's real (sloping) line."""
    rows = []
    for i, r in enumerate(picks.itertuples()):
        row = {"id": first_id + i, "day": day, "list": f"{list_name} "
               + ("buy now" if r.kind == "now" else "about to break"),
               "coin": r.coin, "tf": r.timeframe, "setup": r.pattern, "entry_rule": r.kind,
               "trigger": "", "t1": "", "p1": "", "t2": "", "p2": "", "from_utc": when_utc,
               "entry_price": "", "stop": round(float(r.down_level), 10),
               "target": round(float(r.target_up), 10),
               "note": f"auto: score {r.score:.0f}, reward/risk {r.rr:.1f}"}
        if r.kind == "now":
            row["entry_price"] = float(r.price)
        else:
            line = None
            try:
                df = fetch(r.symbol, r.timeframe, 300)
                p = next((x for x in pt.analyse(df).patterns
                          if x.name == r.pattern and x.upper is not None), None)
                if p is not None:
                    u = p.upper
                    ms = lambda ts: int(pd.Timestamp(ts).value // 1_000_000)  # noqa: E731
                    line = (ms(df.index[u.i0]), u.p0, ms(df.index[u.i1]), u.p1)
            except Exception:
                line = None
            if line:
                row["t1"], row["p1"], row["t2"], row["p2"] = line
            else:
                row["trigger"] = float(r.up_level)
        rows.append(row)
    return rows
