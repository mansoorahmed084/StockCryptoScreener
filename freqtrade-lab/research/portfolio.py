"""Portfolio simulation: pool trades across coins and sides, compound, per year.

Every earlier test pooled trades and averaged their R, which answers "is the
edge real" but not "what would the account have done". Those differ, because:

  * trades overlap, and a position limit means some signals are simply skipped
  * risk is 1% of CURRENT equity, so results compound
  * a year's outcome depends on the order trades arrive in, not just their mean

So this walks the trades in chronological order, enforces a concurrency cap,
sizes each at 1% of equity at the time, and reports by calendar year.

Shorts are priced by the inversion in breakout.py. R-multiples are
log-symmetric to true shorts up to a small convexity term, and **funding is not
modelled** -- the same caveat backend/research/strategy.py carries.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness      # noqa: E402
import breakout     # noqa: E402

BAR = pd.Timedelta("1D")


def collect(coins: list[str], side: str, tf: str = "1d",
            detail: str = "1h", time_stop: int = 60, **kw) -> list:
    """Every trade the config produces, across the given coins."""
    plan = harness.ExitPlan(legs=[(3.0, 1.0)], time_stop_bars=time_stop)
    out = []
    for c in coins:
        pair = f"{c}/USDT"
        try:
            base, det = harness.load(pair, tf), harness.load(pair, detail)
        except FileNotFoundError:
            continue
        sig = breakout.divergence_breakout(base, side=side, **kw)
        if sig.empty:
            continue
        for tr in harness.simulate(sig, base, det, plan, base_bar=BAR):
            out.append((tr, c))
    return out


def simulate_account(trades: list, capital: float = 100_000.0,
                     risk: float = 0.01, max_open: int = 10) -> pd.DataFrame:
    """Walk trades chronologically, cap concurrency, compound at 1% risk."""
    trades = sorted(trades, key=lambda x: x[0].entry_time)
    equity = capital
    open_until: list[pd.Timestamp] = []
    rows = []

    for tr, coin in trades:
        open_until = [t for t in open_until if t > tr.entry_time]
        if len(open_until) >= max_open:
            continue                       # no slot: the signal is skipped
        pnl = equity * risk * tr.r
        equity += pnl
        open_until.append(tr.exit_time)
        rows.append({"entry": tr.entry_time, "exit": tr.exit_time, "coin": coin,
                     "dir": "long" if tr.direction > 0 else "short",
                     "r": tr.r, "pnl": pnl, "equity": equity})
    return pd.DataFrame(rows)


def by_year(acct: pd.DataFrame, capital: float = 100_000.0) -> pd.DataFrame:
    """Calendar-year P&L, trade count and win rate."""
    if acct.empty:
        return pd.DataFrame()
    a = acct.copy()
    a["year"] = a["entry"].dt.year
    g = a.groupby("year")
    out = pd.DataFrame({
        "trades": g.size(),
        "win%": (g["r"].apply(lambda s: 100 * (s > 0).mean())).round(1),
        "total_R": g["r"].sum().round(1),
        "pnl": g["pnl"].sum().round(0),
    })
    out["equity_end"] = g["equity"].last().round(0)
    start = pd.Series([capital] + list(out["equity_end"])[:-1], index=out.index)
    out["return%"] = ((out["equity_end"] / start - 1) * 100).round(1)
    return out


def summary(acct: pd.DataFrame, years: float, capital: float = 100_000.0) -> dict:
    if acct.empty:
        return {"n": 0}
    end = float(acct["equity"].iloc[-1])
    eq = pd.concat([pd.Series([capital]), acct["equity"]], ignore_index=True)
    dd = (eq.cummax() - eq) / eq.cummax()
    rs = acct["r"].to_numpy()
    gw, gl = rs[rs > 0].sum(), -rs[rs < 0].sum()
    return {
        "n": len(acct),
        "win%": round(100 * (rs > 0).mean(), 1),
        "avg_r": round(rs.mean(), 3),
        "total%": round((end / capital - 1) * 100, 2),
        "cagr%": round(((end / capital) ** (1 / years) - 1) * 100, 2),
        "pf": round(gw / gl, 2) if gl > 0 else float("inf"),
        "max_dd%": round(100 * dd.max(), 2),
        "end": round(end),
    }
