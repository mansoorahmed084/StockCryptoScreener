"""Fast R-multiple backtest harness for ETH short-term strategy research.

Why this exists: freqtrade's CLI is the credibility check, but it is far too
slow to sweep a hundred parameter sets. This harness runs the same conservative
fill rules over the same feather candles freqtrade downloaded, in seconds, so
iteration is cheap. Anything that survives here gets re-run in freqtrade proper
before it is believed.

Fill rules, deliberately pessimistic and matching backend/research/engine.py:
  * a signal on a closed bar at T enters at the OPEN of bar T+1
  * exits are walked on DETAIL candles (5m inside 1h, 1h inside 4h)
  * if a detail bar's range contains both the stop and a target, the STOP fills
  * costs are charged in price terms on entry and on every partial exit
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DATA_DIR = Path(__file__).resolve().parents[1] / "user_data" / "data" / "binance"

# 0.1% exchange fee + 0.05% slippage per side, matching STRATEGY_RESEARCH.md.
DEFAULT_COST = 0.0015


# --------------------------------------------------------------------- data
def load(pair: str, timeframe: str) -> pd.DataFrame:
    """Load one OHLCV feather as a DatetimeIndex frame."""
    fname = f"{pair.replace('/', '_')}-{timeframe}.feather"
    path = DATA_DIR / fname
    if not path.exists():
        raise FileNotFoundError(f"No data at {path}. Run freqtrade download-data.")
    df = pd.read_feather(path)
    df = df.set_index("date").sort_index()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


# ------------------------------------------------------------------ exits
@dataclass
class ExitPlan:
    """How a trade is taken off.

    legs: (r_multiple, fraction_of_position). Fractions must sum to 1.0.
    be_after_leg: after this leg fills (0-indexed), move the stop to entry.
                  None disables the breakeven move.
    time_stop_bars: force-close the remainder after this many BASE bars.
    """
    legs: list[tuple[float, float]] = field(default_factory=lambda: [(3.0, 1.0)])
    be_after_leg: int | None = None
    time_stop_bars: int = 120

    @property
    def label(self) -> str:
        legs = "+".join(f"{f:.0%}@{r:g}R" for r, f in self.legs)
        be = f" BE@leg{self.be_after_leg}" if self.be_after_leg is not None else ""
        return legs + be


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: int          # +1 long, -1 short
    entry: float
    stop: float
    r: float                # realised R, net of costs
    hit_full_target: bool   # reached the LAST leg's R multiple
    bars_held: int
    reason: str


# --------------------------------------------------------------- simulation
def _walk(detail: pd.DataFrame, start: int, direction: int, entry: float,
          stop: float, plan: ExitPlan, bar_limit_ts: pd.Timestamp,
          cost: float) -> tuple[float, pd.Timestamp, bool, str]:
    """Walk detail bars from `start`, returning (net R, exit ts, full target, reason).

    Stop-first inside any bar that straddles both levels.
    """
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0, detail.index[start], False, "bad_risk"

    remaining = 1.0
    realised = 0.0
    live_stop = stop
    leg_i = 0
    legs = plan.legs
    last_r = legs[-1][0]
    full_target = False

    highs = detail["high"].to_numpy()
    lows = detail["low"].to_numpy()
    closes = detail["close"].to_numpy()
    index = detail.index

    def book(price: float, frac: float) -> float:
        fill = price * (1 - cost) if direction > 0 else price * (1 + cost)
        return frac * direction * (fill - entry) / risk

    for i in range(start, len(detail)):
        if index[i] >= bar_limit_ts:
            realised += book(closes[i], remaining)
            return realised, index[i], full_target, "time_stop"

        hi, lo = highs[i], lows[i]

        # --- stop first, always ---
        stop_hit = lo <= live_stop if direction > 0 else hi >= live_stop
        if stop_hit:
            realised += book(live_stop, remaining)
            reason = "breakeven" if live_stop == entry else "stop"
            return realised, index[i], full_target, reason

        # --- then any target legs this bar reaches, in order ---
        while leg_i < len(legs):
            r_mult, frac = legs[leg_i]
            tgt = entry + direction * r_mult * risk
            reached = hi >= tgt if direction > 0 else lo <= tgt
            if not reached:
                break
            realised += book(tgt, frac)
            remaining -= frac
            leg_i += 1
            if r_mult >= last_r:
                full_target = True
            if plan.be_after_leg is not None and leg_i == plan.be_after_leg + 1:
                live_stop = entry
            if remaining <= 1e-9:
                return realised, index[i], full_target, "target"

    realised += book(closes[-1], remaining)
    return realised, index[-1], full_target, "data_end"


def simulate(signals: pd.DataFrame, base: pd.DataFrame, detail: pd.DataFrame,
             plan: ExitPlan, cost: float = DEFAULT_COST,
             base_bar: pd.Timedelta | None = None) -> list[Trade]:
    """Run every signal to completion.

    signals: index = SIGNAL bar timestamps (already confirmed, no lookahead),
             columns = direction (+1/-1) and stop (absolute price).
    base:    the signal timeframe OHLCV.
    detail:  a finer timeframe used to resolve intrabar fills.
    """
    if base_bar is None:
        base_bar = base.index[1] - base.index[0]
    trades: list[Trade] = []

    for ts, row in signals.iterrows():
        entry_ts = ts + base_bar               # enter at the next base bar's open
        if entry_ts not in base.index:
            continue
        entry = float(base.loc[entry_ts, "open"])
        direction = int(row["direction"])
        stop = float(row["stop"])
        if direction > 0 and stop >= entry:
            continue
        if direction < 0 and stop <= entry:
            continue

        start = detail.index.searchsorted(entry_ts, side="left")
        if start >= len(detail):
            continue
        entry_fill = entry * (1 + cost) if direction > 0 else entry * (1 - cost)
        limit_ts = entry_ts + plan.time_stop_bars * base_bar

        r, exit_ts, full, reason = _walk(detail, start, direction, entry_fill,
                                         stop, plan, limit_ts, cost)
        trades.append(Trade(entry_ts, exit_ts, direction, entry_fill, stop, r,
                            full, int((exit_ts - entry_ts) / base_bar), reason))
    return trades


# ----------------------------------------------------------------- metrics
def metrics(trades: list[Trade]) -> dict:
    """Both win definitions, because they answer different questions."""
    if not trades:
        return {"n": 0}
    rs = np.array([t.r for t in trades])
    wins = rs > 0
    gross_win = rs[rs > 0].sum()
    gross_loss = -rs[rs < 0].sum()
    equity = np.cumsum(rs)
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))[1:]
    dd = peak - equity

    return {
        "n": len(trades),
        # net-positive trades: the "accuracy" the scale-out structures optimise
        "win_net_pct": round(100 * wins.mean(), 1),
        # reached the final R multiple: the strict "hit 1:3" reading
        "win_target_pct": round(100 * np.mean([t.hit_full_target for t in trades]), 1),
        "avg_r": round(rs.mean(), 3),
        "total_r": round(rs.sum(), 1),
        "pf": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "max_dd_r": round(dd.max(), 1),
        "avg_bars": round(np.mean([t.bars_held for t in trades]), 1),
        "trades_per_year": None,   # filled by the runner, which knows the span
    }


def split_metrics(trades: list[Trade], oos_start: str) -> dict:
    """In-sample / out-of-sample split on a date boundary."""
    cut = pd.Timestamp(oos_start, tz="UTC")
    is_t = [t for t in trades if t.entry_time < cut]
    oos_t = [t for t in trades if t.entry_time >= cut]
    return {"is": metrics(is_t), "oos": metrics(oos_t)}
