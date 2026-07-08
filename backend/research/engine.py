"""Trade-level backtest engine.

Long-only, one open position per coin. Entries fill at the NEXT candle open
after a signal (plus slippage); stops/targets fill intrabar with conservative
assumptions (stop before target when both touch; gap-through fills at the open).
Fees and slippage are charged on both sides.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

FEE_PCT = 0.001      # 0.1% taker per side
SLIP_PCT = 0.0005    # 0.05% per side


@dataclass(frozen=True)
class Signal:
    ts: pd.Timestamp          # close time of the signal candle
    stop: float               # initial stop price (absolute)
    tag: str = ""             # for attribution in results
    limit: float | None = None  # buy-limit price; None = market at next open
    ttl: int = 6              # bars the limit order stays working


@dataclass
class Trade:
    coin: str
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    entry: float
    exit: float
    stop: float
    target: float | None
    r: float                  # net R multiple after costs
    pnl_pct: float            # net % move on position
    reason: str               # 'stop' | 'target' | 'signal_exit' | 'time' | 'eod'
    bars: int
    tag: str = ""


@dataclass
class Metrics:
    n: int = 0
    win_rate: float = float("nan")
    avg_r: float = float("nan")
    profit_factor: float = float("nan")
    expectancy_pct: float = float("nan")   # avg net pnl% per trade
    max_dd_pct: float = float("nan")       # at 1% equity risk per trade
    equity_final: float = float("nan")     # growth multiple at 1% risk
    avg_bars: float = float("nan")

    def row(self) -> dict:
        return {
            "n": self.n, "win%": round(self.win_rate * 100, 1),
            "avgR": round(self.avg_r, 3), "PF": round(self.profit_factor, 2),
            "exp%": round(self.expectancy_pct, 3),
            "maxDD%": round(self.max_dd_pct, 2),
            "equity": round(self.equity_final, 3),
            "bars": round(self.avg_bars, 1),
        }


def simulate(coin: str, df: pd.DataFrame, signals: list[Signal], *,
             rr_target: float | None = 1.5,
             exit_signal: pd.Series | None = None,
             trail_stop: pd.Series | None = None,
             max_hold: int | None = None,
             fee_pct: float = FEE_PCT, slip_pct: float = SLIP_PCT) -> list[Trade]:
    """Run the signal list through the candles; returns closed trades.

    exit_signal: boolean series (same index) — True at a candle close requests
    an exit at the NEXT open. trail_stop: price series — the stop is raised to
    this level (never lowered) at each candle close.
    """
    if df.empty or not signals:
        return []
    idx = df.index
    pos = {ts: i for i, ts in enumerate(idx)}
    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    exit_arr = (exit_signal.reindex(idx).fillna(False).to_numpy()
                if exit_signal is not None else None)
    trail_arr = (trail_stop.reindex(idx).to_numpy()
                 if trail_stop is not None else None)
    round_trip = 2 * (fee_pct + slip_pct)

    trades: list[Trade] = []
    busy_until = -1  # candle index until which we're in a position

    for sig in sorted(signals, key=lambda s: s.ts):
        i = pos.get(sig.ts)
        if i is None or i + 1 >= len(idx):
            continue
        if i + 1 <= busy_until:
            continue  # already in a trade for this coin

        if sig.limit is None:                       # market at next open
            entry_i = i + 1
            entry = opens[entry_i] * (1 + slip_pct)
        else:                                        # buy limit on a retest
            entry_i = None
            for k in range(i + 1, min(len(idx), i + 1 + sig.ttl)):
                if opens[k] <= sig.limit:            # gapped through: fill at open
                    entry_i, entry = k, opens[k]
                    break
                if lows[k] <= sig.limit:             # touched: fill at the limit
                    entry_i, entry = k, sig.limit
                    break
            if entry_i is None:
                continue                             # never filled
        stop = sig.stop
        if stop >= entry:
            continue  # signal invalidated by the gap up/down at entry
        risk = entry - stop
        target = entry + rr_target * risk if rr_target else None

        exit_price = None
        reason = "eod"
        j = entry_i
        limit_fill_bar = entry_i if sig.limit is not None else -1
        pending_exit = False
        while j < len(idx):
            if pending_exit:
                exit_price, reason = opens[j] * (1 - slip_pct), "signal_exit"
                break
            # conservative intrabar order: stop first, then target
            if j != entry_i and opens[j] <= stop:
                exit_price, reason = opens[j] * (1 - slip_pct), "stop"
                break
            if lows[j] <= stop:
                exit_price, reason = stop * (1 - slip_pct), "stop"
                break
            # On a limit-fill bar the intrabar sequence is unknowable — price
            # reached the limit by falling; assuming it also bounced to the
            # target within the same bar would be optimistic. Targets fill from
            # the next bar onward.
            if (target is not None and j != limit_fill_bar
                    and highs[j] >= target):
                exit_price, reason = target * (1 - slip_pct), "target"
                break
            if max_hold is not None and j - entry_i + 1 >= max_hold:
                exit_price, reason = opens[min(j + 1, len(idx) - 1)] * (1 - slip_pct), "time"
                j = min(j + 1, len(idx) - 1)
                break
            if trail_arr is not None and not np.isnan(trail_arr[j]):
                stop = max(stop, float(trail_arr[j]))
            if exit_arr is not None and exit_arr[j]:
                pending_exit = True
            j += 1
        if exit_price is None:  # ran out of data with position open
            exit_price, reason, j = opens[-1] * (1 - slip_pct), "eod", len(idx) - 1

        gross_pct = exit_price / entry - 1.0
        net_pct = gross_pct - round_trip
        net_r = net_pct * entry / risk
        trades.append(Trade(
            coin=coin, entry_ts=idx[entry_i], exit_ts=idx[min(j, len(idx) - 1)],
            entry=entry, exit=exit_price, stop=sig.stop, target=target,
            r=net_r, pnl_pct=net_pct * 100, reason=reason,
            bars=min(j, len(idx) - 1) - entry_i + 1, tag=sig.tag))
        busy_until = j
    return trades


def metrics(trades: list[Trade], *, risk_per_trade: float = 0.01) -> Metrics:
    if not trades:
        return Metrics(n=0)
    rs = np.array([t.r for t in trades])
    wins = rs[rs > 0]
    losses = rs[rs <= 0]
    ordered = sorted(trades, key=lambda t: t.exit_ts)
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for t in ordered:
        equity *= 1 + risk_per_trade * t.r
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    pf = (wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 \
        else float("inf")
    return Metrics(
        n=len(trades),
        win_rate=float((rs > 0).mean()),
        avg_r=float(rs.mean()),
        profit_factor=float(pf),
        expectancy_pct=float(np.mean([t.pnl_pct for t in trades])),
        max_dd_pct=float(max_dd * 100),
        equity_final=float(equity),
        avg_bars=float(np.mean([t.bars for t in trades])),
    )
