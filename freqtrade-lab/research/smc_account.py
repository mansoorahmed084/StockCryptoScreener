"""Turn a pooled SMC trade list into an account: CAGR and real drawdown.

R sums assume every signal is taken at the same size. An account cannot do
that: positions overlap, slots fill up, and profit only compounds once a trade
CLOSES. This is the event-queue walk from tl_account.py, adapted for futures:

  * risk a fixed fraction of current equity per trade
  * equity is banked at EXIT, never at entry (portfolio.py's flaw)
  * at most `slots` positions open at once; later signals are skipped
  * total notional is capped at `max_lev` x equity (a 1% risk behind a 0.5%
    stop is a 2x position on its own, so tight-stop books hit this cap)
  * drawdown is measured on closed equity AND on equity with open trades
    marked at their worst case (all open stops hit), which is a bound on the
    mark-to-market drawdown that needs no candles
"""
from __future__ import annotations

import heapq

import numpy as np
import pandas as pd


def account(tr: pd.DataFrame, risk: float = 0.01, slots: int = 10,
            max_lev: float = 5.0) -> dict:
    if len(tr) == 0:
        return {"trades": 0}
    t = tr.sort_values("entry_time").reset_index(drop=True)
    eq = 1.0
    open_q: list = []          # (exit_time, seq, stake_risk, r, notional)
    notional = 0.0
    risk_open = 0.0
    curve = []                 # (time, closed equity, worst-case equity)
    taken = skipped = 0
    seq = 0
    for row in t.itertuples(index=False):
        while open_q and open_q[0][0] <= row.entry_time:
            xt, _, stake, r, notl = heapq.heappop(open_q)
            eq += stake * r
            notional -= notl
            risk_open -= stake
            curve.append((xt, eq, eq - risk_open))
        if len(open_q) >= slots:
            skipped += 1
            continue
        stake = eq * risk
        notl = stake / max(row.risk_pct, 1e-6)
        if notional + notl > max_lev * eq:
            skipped += 1
            continue
        heapq.heappush(open_q, (row.exit_time, seq, stake, row.r, notl))
        seq += 1
        notional += notl
        risk_open += stake
        taken += 1
        curve.append((row.entry_time, eq, eq - risk_open))
    while open_q:
        xt, _, stake, r, notl = heapq.heappop(open_q)
        eq += stake * r
        risk_open -= stake
        curve.append((xt, eq, eq - risk_open))
    c = pd.DataFrame(curve, columns=["time", "closed", "worst"])
    years = max((c.time.max() - c.time.min()).days / 365.25, 0.25)

    def maxdd(x):
        x = np.asarray(x)
        pk = np.maximum.accumulate(x)
        return float(((pk - x) / pk).max())

    yearly = c.groupby(c.time.dt.year)["closed"].last()
    prev = yearly.shift(1).fillna(1.0)
    return {
        "trades": taken, "skipped": skipped,
        "final": round(eq, 2),
        "cagr": round(100 * (eq ** (1 / years) - 1), 1) if eq > 0 else -100.0,
        "dd_closed": round(100 * maxdd(c.closed), 1),
        "dd_worst": round(100 * maxdd(c.worst.clip(lower=1e-9)), 1),
        "years": {int(y): round(100 * (v / p - 1), 1)
                  for y, v, p in zip(yearly.index, yearly, prev)},
    }
