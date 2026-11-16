"""Does SMC Sweep-Break (B_final) hold on SMALL coins? Results by the coin's
24h dollar volume at the moment of the signal.

    python research/smc_volume.py          # both tests
    python research/smc_volume.py A        # only the long history
    python research/smc_volume.py B        # only the live view

The live scan trades only coins with 24h futures volume >= $5M. This asks
whether lowering that floor would add trades with the same edge.

  A  long history: the 279 research coins (Binance spot 1h candles, 2020 to
     now). Each trade is tagged with the coin's 24h spot dollar volume over
     the 24 hours before its entry. Costs 0.06% (as tested), 0.10% and 0.20%
     per side: small coins slip more.
  B  live view: every Binance USDT perp the live scan sees (~500, including
     coins the research never used), last ~5.5 months of 4h futures candles,
     tagged with the 24h FUTURES dollar volume before entry -- the exact
     number the live floor uses -- and with whether CoinDCX lists the coin.

R per trade is the backtest's: entry at the next 4h open, stop and target as
the strategy sets them, the cost per side taken off.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smc           # noqa: E402
import smc_loop      # noqa: E402
import smc_oos       # noqa: E402

CFG = smc_oos.FINALISTS["B_final"]
BANDS = [0, 1e6, 2e6, 5e6, 10e6, 50e6, np.inf]
LABELS = ["< $1M", "$1-2M", "$2-5M", "$5-10M", "$10-50M", ">= $50M"]


def stats(t: pd.DataFrame, col: str = "r") -> dict:
    r = t[col].astype(float)
    if not len(r):
        return dict(trades=0)
    win, loss = r[r > 0].sum(), -r[r <= 0].sum()
    return dict(trades=len(r), win=f"{100 * (r > 0).mean():.0f}%",
                avgR=round(r.mean(), 3), PF=round(win / loss, 2) if loss else np.inf,
                totalR=round(r.sum(), 1))


def table(t: pd.DataFrame, cols: dict[str, str]) -> pd.DataFrame:
    """One row per volume band (and the two sides of the $5M floor)."""
    t = t.assign(band=pd.cut(t.v24, BANDS, labels=LABELS, right=False))
    rows = []
    groups = [(b, t[t.band == b]) for b in LABELS]
    groups += [("ALL under $5M", t[t.v24 < 5e6]), ("ALL $5M and up", t[t.v24 >= 5e6])]
    for name, g in groups:
        row = {"24h volume": name}
        for label, col in cols.items():
            s = stats(g, col)
            if label == list(cols)[0]:
                row.update({k: v for k, v in s.items() if k != "totalR"})
            else:
                row[f"avgR {label}"] = s.get("avgR")
        rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ A
def v24_spot(coin: str) -> pd.Series:
    """24h spot dollar volume known at each 1h bar's close: the value at
    time T sums the 24 bars that closed by T."""
    d = smc.bars(coin, "1h", "1h")
    qv = (d["close"] * d["volume"]).rolling(24, min_periods=20).sum()
    qv.index = qv.index + pd.Timedelta("1h")          # known at the bar's close
    return qv


def test_a() -> None:
    old = [c for c in smc.UNIVERSE if smc.have(c, "1h")]
    coins = old + smc_oos.new_coins()
    cfgs = [CFG, replace(CFG, cost=0.0010), replace(CFG, cost=0.0020)]
    tr = smc_loop.evaluate(cfgs, coins, "1h", "volume A")
    base = tr[0].copy()
    for i, name in ((1, "r10"), (2, "r20")):
        base[name] = tr[i]["r"].to_numpy() if len(tr[i]) == len(base) else np.nan
    v = []
    for coin, g in base.groupby(base.coin.astype(str)):
        s = v24_spot(coin)
        v.append(pd.Series(s.reindex(pd.DatetimeIndex(g.entry_time), method="ffill").to_numpy(),
                           index=g.index))
    base["v24"] = pd.concat(v).reindex(base.index)
    base = base.dropna(subset=["v24"])
    lo = base.entry_time.max() - pd.DateOffset(years=3)
    for title, t in (("A. 279 coins, 2020 to now", base),
                     ("A. 279 coins, last 3 years", base[base.entry_time >= lo])):
        print(f"\n{title}: {len(t)} trades, 24h SPOT volume before entry")
        print(table(t, {"0.06%": "r", "0.10%": "r10", "0.20%": "r20"}).to_string(index=False))


# ------------------------------------------------------------------ B
def test_b() -> None:
    import scan_smc

    results, now = scan_smc.scan(0.0, False, None, 4)
    rows = []
    for live, _vol, ev in results:
        tr = ev.get("trades")
        if tr is None or not len(tr):
            continue
        k = live.ltf
        qv = k["quote_volume"] if "quote_volume" in k else k["close"] * k["volume"]
        v24 = qv.rolling(6, min_periods=6).sum()
        v24.index = v24.index + scan_smc.BAR                # known at the 4h close
        for _, x in tr[tr.why != "data_end"].iterrows():
            e = pd.Timestamp(x.entry_time)
            e = e if e.tzinfo else e.tz_localize("UTC")
            rows.append(dict(coin=live.coin, dcx=live.dcx, r=float(x.r),
                             v24=float(v24.reindex([e], method="ffill").iloc[0])))
    t = pd.DataFrame(rows).dropna(subset=["v24"])
    print(f"\nB. live view: {t.coin.nunique()} perps, closed trades entered in the last "
          f"~5.5 months to {now:%Y-%m-%d}, 24h FUTURES volume before entry")
    print(table(t, {"0.06%": "r"}).to_string(index=False))
    small = t[t.v24 < 5e6]
    if len(small):
        on = small[small.dcx]
        print(f"\nUnder $5M: {len(small)} trades on {small.coin.nunique()} coins; "
              f"{len(on)} of them ({100 * len(on) / len(small):.0f}%) on coins CoinDCX lists")
        print("  on CoinDCX:     ", stats(on))
        print("  not on CoinDCX: ", stats(small[~small.dcx]))


if __name__ == "__main__":
    which = (sys.argv[1:] or ["A", "B"])
    if "A" in which:
        test_a()
    if "B" in which:
        test_b()
