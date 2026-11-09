"""BACKTEST: test each rule on years of daily candles, with fees, then keep
what works and kill what doesn't.

A rule is judged per market (crypto / india / us), on all trades of the
watchlist together. It is kept only when:

  1. it has at least ``min_trades`` trades,
  2. the average trade is at least ``min_exp_r`` R after fees and slippage,
  3. the profit factor is at least ``min_pf``, and
  4. it clears the same ``min_exp_r`` bar on the *control* symbols, which
     are not on the watchlist.

Point 4 matters most. Testing many rules on a hand-picked list always finds
one that looks good by luck; the control list catches that. The rules have
fixed settings: nothing is tuned to the data.
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .data import DAY, DeskData, complete
from .rules import WARMUP, arrays, setup_at, with_indicators
from .settings import MARKETS, Settings
from .sim import find_fill, manage, r_multiple

log = logging.getLogger(__name__)


@dataclass
class BtTrade:
    symbol: str
    rule: str
    signal_time: int
    fill_time: int
    exit_time: int
    entry: float
    stop: float
    target: float
    fill: float
    exit: float
    why: str
    r: float


def backtest_frame(df: pd.DataFrame, symbol: str, rule: str, *, fee: float, slip: float,
                   target_r: float, order_bars: int, max_hold: int, years: float,
                   now: float | None = None) -> list[BtTrade]:
    """Every trade ``rule`` would have made on one symbol, one at a time."""
    d = complete(df, now)
    if len(d) <= WARMUP + 2:
        return []
    d = with_indicators(d)
    a = arrays(d)
    o, h, lo, c, t = a["open"], a["high"], a["low"], a["close"], a["time"]
    n = len(d)
    window_start = t[-1] - years * 365 * DAY
    i = max(WARMUP, int(np.searchsorted(t, window_start)))
    out: list[BtTrade] = []
    while i < n - 1:
        s = setup_at(rule, a, i, target_r)
        if s is None:
            i += 1
            continue
        state, fill = find_fill(o, h, i + 1, s.entry, s.target, order_bars, slip)
        if state == "expired":
            i += order_bars
            continue
        if state == "missed":
            i = fill.idx
            continue
        if state == "pending":
            break
        ex = manage(o, h, lo, c, fill.idx, s.stop, s.target, max_hold, slip)
        if ex is None:          # still open at the end of the data
            break
        out.append(BtTrade(symbol, rule, int(t[i]), int(t[fill.idx]), int(t[ex.idx]),
                           s.entry, s.stop, s.target, fill.price, ex.price, ex.why,
                           r_multiple(fill.price, s.stop, ex.price, fee)))
        i = ex.idx
    return out


def stats(trades: list[BtTrade]) -> dict:
    """Trades, win rate %, average R, profit factor, total R, max drawdown R."""
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "exp_r": 0.0, "pf": 0.0,
                "total_r": 0.0, "max_dd_r": 0.0}
    rs = np.array([tr.r for tr in sorted(trades, key=lambda x: x.exit_time)])
    gains, losses = rs[rs > 0].sum(), -rs[rs <= 0].sum()
    pf = gains / losses if losses > 0 else (99.0 if gains > 0 else 0.0)
    eq = np.concatenate([[0.0], np.cumsum(rs)])
    dd = float((np.maximum.accumulate(eq) - eq).max())
    return {"trades": int(len(rs)), "win_rate": float((rs > 0).mean() * 100),
            "exp_r": float(rs.mean()), "pf": float(min(pf, 99.0)),
            "total_r": float(rs.sum()), "max_dd_r": dd}


def verdict(w: dict, ctl: dict, cfg: dict) -> tuple[bool, str]:
    if w["trades"] < cfg["min_trades"]:
        return False, f"only {w['trades']} trades (needs {cfg['min_trades']})"
    if w["exp_r"] <= 0:
        return False, f"loses money after fees ({w['exp_r']:+.2f}R a trade)"
    if w["exp_r"] < cfg["min_exp_r"]:
        return False, f"edge too small ({w['exp_r']:+.2f}R a trade)"
    if w["pf"] < cfg["min_pf"]:
        return False, f"profit factor {w['pf']:.2f} (needs {cfg['min_pf']})"
    if ctl["trades"] < cfg["min_trades"] // 2:
        return False, f"too few control trades to check ({ctl['trades']})"
    if ctl["exp_r"] < cfg["min_exp_r"]:
        return False, f"fails on the control symbols ({ctl['exp_r']:+.2f}R a trade)"
    return True, "works on the watchlist and on the control symbols"


def run_backtests(settings: Settings, data: DeskData, now: float | None = None,
                  markets: tuple[str, ...] = MARKETS) -> tuple[list[dict], list[dict]]:
    """(verdict rows, per-symbol rows)."""
    cfg = settings.backtest
    years = float(cfg["years"])
    recent_from = (now or pd.Timestamp.now(tz="UTC").timestamp()) - cfg["recent_years"] * 365 * DAY
    verdicts, per_symbol = [], []
    for market in markets:
        pooled: dict[tuple[str, str], list[BtTrade]] = {}
        for scope, symbols in (("watch", settings.watch[market]),
                               ("control", settings.control[market])):
            for sym in symbols:
                try:
                    df = data.history(sym, years + 1)
                except Exception as exc:   # one bad symbol must not stop the night
                    log.warning("backtest: %s failed: %s", sym, exc)
                    continue
                for rule, rcfg in settings.rules.items():
                    trades = backtest_frame(
                        df, sym, rule, fee=settings.fee(market), slip=settings.slippage,
                        target_r=float(rcfg.get("target_r", 2)),
                        order_bars=int(cfg["order_bars"]), max_hold=int(cfg["max_hold"]),
                        years=years, now=now)
                    pooled.setdefault((rule, scope), []).extend(trades)
                    per_symbol.append({"symbol": sym, "market": market, "scope": scope,
                                       "rule": rule, **stats(trades)})
        for rule in settings.rules:
            w = stats(pooled.get((rule, "watch"), []))
            ctl = stats(pooled.get((rule, "control"), []))
            recent = stats([tr for tr in pooled.get((rule, "watch"), [])
                            if tr.fill_time >= recent_from])
            keep, why = verdict(w, ctl, cfg)
            verdicts.append({
                "market": market, "rule": rule, "keep": int(keep), "why": why,
                "w_trades": w["trades"], "w_win": w["win_rate"], "w_exp": w["exp_r"],
                "w_pf": w["pf"], "w_dd": w["max_dd_r"], "w_total": w["total_r"],
                "c_trades": ctl["trades"], "c_win": ctl["win_rate"], "c_exp": ctl["exp_r"],
                "c_pf": ctl["pf"], "recent_trades": recent["trades"],
                "recent_exp": recent["exp_r"] if recent["trades"] else math.nan})
    return verdicts, per_symbol


def trades_frame(trades: list[BtTrade]) -> pd.DataFrame:
    return pd.DataFrame([asdict(t) for t in trades])
