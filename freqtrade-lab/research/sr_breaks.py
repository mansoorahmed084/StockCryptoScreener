"""Support and Resistance Levels with Breaks [LuxAlgo], rebuilt in Python, and
a backtest of it.

    python research/sr_breaks.py              # the full grid, old + new coins
    python research/sr_breaks.py --quick      # 5 + 5 coins

The indicator (LuxAlgo's free open-source v4 script, default settings):
  * resistance = the latest pivot high with 15 bars each side, shown one bar
    after it is confirmed (fixnan(pivothigh(15, 15)[1])); support mirrors it.
    A level stays until a newer pivot replaces it, broken or not.
  * volume oscillator = 100 x (EMA5(vol) - EMA10(vol)) / EMA10(vol)
  * "B" up   = close crosses over resistance, osc > 20, and NOT a bull wick
               (bull wick: open - low > close - open)
  * "B" down = close crosses under support, osc > 20, and NOT a bear wick
               (bear wick: open - close < high - open)

Trade rules tested (one position per coin, entry next open):
  * long on an up break, short on a down break (or long only)
  * filters: the volume rule and the wick rule each on/off
  * stop "bar":     the break bar's low - 0.1 ATR (high + 0.1 ATR short)
    stop "support": the opposite level (support for a long) - 0.1 ATR
  * exit "3R":  fixed 3R target, 42-bar time stop, stop tested first
    exit "sr":  hold until a close beyond the indicator's own opposite level
                (support for a long), leave at the next open; the hard stop
                stays. Support rises as new pivot lows form, so it trails.
  * stops closer than 0.5% or wider than 15% are skipped; 0.06% per side

Out-of-sample means coins: the 203 coins outside the 76-coin universe.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smc           # noqa: E402
import smc_account   # noqa: E402
import smc_oos       # noqa: E402

BASE = "1h"
OUT = Path(__file__).resolve().parent / "results" / "sr_breaks.jsonl"


# ------------------------------------------------------------- indicator
@njit(cache=True)
def _ema(x, n):
    """Pine's ema: seeded with the SMA of the first n values."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    a = 2.0 / (n + 1.0)
    e = x[:n].mean()
    out[n - 1] = e
    for i in range(n, len(x)):
        e = a * x[i] + (1.0 - a) * e
        out[i] = e
    return out


@njit(cache=True)
def _levels(ph, pl):
    """fixnan(pivot[1]): the latest pivot, usable one bar after confirmation."""
    n = len(ph)
    res = np.full(n, np.nan)
    sup = np.full(n, np.nan)
    r = np.nan
    s = np.nan
    for t in range(1, n):
        if not np.isnan(ph[t - 1]):
            r = ph[t - 1]
        if not np.isnan(pl[t - 1]):
            s = pl[t - 1]
        res[t] = r
        sup[t] = s
    return res, sup


def indicator(df: pd.DataFrame, left: int = 15, right: int = 15,
              vol_thresh: float = 20.0) -> pd.DataFrame:
    """Levels, the volume oscillator and the break flags on one OHLCV frame.

    smc._pivots uses one width for both sides; LuxAlgo's default is 15/15.
    """
    assert left == right, "only equal left/right widths are supported"
    o, h, l, c, v = (df[x].to_numpy(float) for x in
                     ("open", "high", "low", "close", "volume"))
    ph, _, pl, _ = smc._pivots(h, l, left)
    res, sup = _levels(ph, pl)
    s, lg = _ema(v, 5), _ema(v, 10)
    with np.errstate(divide="ignore", invalid="ignore"):
        osc = 100 * (s - lg) / lg
    pc = np.concatenate([[np.nan], c[:-1]])
    pres = np.concatenate([[np.nan], res[:-1]])
    psup = np.concatenate([[np.nan], sup[:-1]])
    x_up = (c > res) & (pc <= pres)                 # ta.crossover
    x_dn = (c < sup) & (pc >= psup)                 # ta.crossunder
    bull_wick = (o - l) > (c - o)
    bear_wick = (o - c) < (h - o)
    vol_ok = osc > vol_thresh
    return pd.DataFrame({
        "res": res, "sup": sup, "osc": osc,
        "x_up": x_up, "x_dn": x_dn, "bull_wick": bull_wick,
        "bear_wick": bear_wick, "vol_ok": vol_ok,
        "b_up": x_up & ~bull_wick & vol_ok,     # LuxAlgo's "B" labels
        "b_dn": x_dn & ~bear_wick & vol_ok,
    }, index=df.index)


@lru_cache(maxsize=None)
def frame(coin: str, tf: str) -> pd.DataFrame:
    df = smc.bars(coin, tf, BASE)
    out = df.join(indicator(df))
    out["atr"] = smc._atr(df["high"].to_numpy(float), df["low"].to_numpy(float),
                          df["close"].to_numpy(float), 14)
    return out


# ------------------------------------------------------------- simulator
@njit(cache=True)
def _sim(o, h, l, c, atr, res, sup, up, dn, side, stop_mode, exit_mode,
         tp_r, max_hold, min_risk, max_risk, cost):
    n = len(c)
    ti = np.empty(n, np.int64)
    tx = np.empty(n, np.int64)
    dd = np.empty(n, np.int64)
    px = np.empty(n)
    st = np.empty(n)
    rr = np.empty(n)
    why = np.empty(n, np.int64)       # 0 stop, 1 target, 2 time, 3 level, 4 end
    mfe = np.empty(n)
    nt = 0
    t = 30
    while t < n - 1:
        d = 0
        if up[t]:
            d = 1
        elif dn[t] and side == 2:
            d = -1
        if d == 0 or np.isnan(atr[t]):
            t += 1
            continue
        ep = o[t + 1]
        if stop_mode == 0:
            stop = l[t] - 0.1 * atr[t] if d > 0 else h[t] + 0.1 * atr[t]
        else:
            ref = sup[t] if d > 0 else res[t]
            if np.isnan(ref):
                t += 1
                continue
            stop = ref - 0.1 * atr[t] if d > 0 else ref + 0.1 * atr[t]
        risk = (ep - stop) * d
        if risk <= 0 or risk / ep < min_risk or risk / ep > max_risk:
            t += 1
            continue
        tgt = ep + d * tp_r * risk
        x_px = c[n - 1]
        x_i = n - 1
        w = 4
        best = 0.0
        for j in range(t + 1, n):
            if d > 0 and l[j] <= stop:
                x_px = min(o[j], stop)
                x_i = j
                w = 0
                break
            if d < 0 and h[j] >= stop:
                x_px = max(o[j], stop)
                x_i = j
                w = 0
                break
            fav = (h[j] - ep) if d > 0 else (ep - l[j])
            best = max(best, fav / risk)
            if exit_mode == 0:
                if d > 0 and h[j] >= tgt:
                    x_px = max(o[j], tgt)
                    x_i = j
                    w = 1
                    break
                if d < 0 and l[j] <= tgt:
                    x_px = min(o[j], tgt)
                    x_i = j
                    w = 1
                    break
                if j - t >= max_hold:
                    x_px = c[j]
                    x_i = j
                    w = 2
                    break
            else:
                lvl = sup[j] if d > 0 else res[j]
                if j + 1 < n and not np.isnan(lvl) and (
                        (d > 0 and c[j] < lvl) or (d < 0 and c[j] > lvl)):
                    x_px = o[j + 1]
                    x_i = j + 1
                    w = 3
                    break
        g = (x_px - ep) * d / risk - cost * (ep + x_px) / risk
        ti[nt] = t + 1
        tx[nt] = x_i
        dd[nt] = d
        px[nt] = ep
        st[nt] = stop
        rr[nt] = g
        why[nt] = w
        mfe[nt] = best
        nt += 1
        t = max(x_i, t + 1)
    return (ti[:nt], tx[:nt], dd[:nt], px[:nt], st[:nt], rr[:nt], why[:nt],
            mfe[:nt])


WHY = np.array(["stop", "target", "time", "level", "data_end"])


@dataclass(frozen=True)
class Cfg:
    tf: str = "4h"
    side: str = "long"        # long | both
    vol: bool = True          # LuxAlgo's volume rule (osc > 20)
    wick: bool = True         # LuxAlgo's wick rule (skip wick breaks)
    stop: str = "bar"         # bar | support
    exit: str = "3R"          # 3R | sr
    tp_r: float = 3.0
    max_hold: int = 42
    min_risk: float = 0.005
    max_risk: float = 0.15
    cost: float = smc.COST

    @property
    def name(self) -> str:
        f = ("vol" if self.vol else "-") + "/" + ("wick" if self.wick else "-")
        return f"{self.tf} {self.side} {f} stop={self.stop} exit={self.exit}"


def run(coin: str, cfg: Cfg) -> pd.DataFrame:
    F = frame(coin, cfg.tf)
    up = F["x_up"].to_numpy()
    dn = F["x_dn"].to_numpy()
    if cfg.vol:
        up = up & F["vol_ok"].to_numpy()
        dn = dn & F["vol_ok"].to_numpy()
    if cfg.wick:
        up = up & ~F["bull_wick"].to_numpy()
        dn = dn & ~F["bear_wick"].to_numpy()
    ti, tx, d, px, st, r, w, mfe = _sim(
        F["open"].to_numpy(float), F["high"].to_numpy(float),
        F["low"].to_numpy(float), F["close"].to_numpy(float),
        F["atr"].to_numpy(float), F["res"].to_numpy(float),
        F["sup"].to_numpy(float), up, dn, 2 if cfg.side == "both" else 1,
        0 if cfg.stop == "bar" else 1, 0 if cfg.exit == "3R" else 1,
        cfg.tp_r, cfg.max_hold, cfg.min_risk, cfg.max_risk, cfg.cost)
    idx = F.index
    return pd.DataFrame({"coin": coin, "entry_time": idx[ti],
                         "exit_time": idx[tx], "dir": d, "entry": px,
                         "stop": st, "r": r, "why": WHY[w], "mfe": mfe,
                         "risk_pct": np.abs(px - st) / px})


def basket(coins: list[str], cfg: Cfg) -> pd.DataFrame:
    fr = [run(c, cfg) for c in coins]
    fr = [f for f in fr if len(f)]
    return pd.concat(fr, ignore_index=True) if fr else pd.DataFrame()


# ------------------------------------------------------------------ grid
def grid() -> list[Cfg]:
    return [Cfg(tf, side, vol, wick, stop, ex)
            for tf, side, vol, wick, stop, ex in itertools.product(
                ("1h", "4h", "1d"), ("long", "both"), (True, False),
                (True, False), ("bar", "support"), ("3R", "sr"))]


def evaluate(cfg: Cfg, old: list[str], new: list[str]) -> dict:
    fit, hold = smc.split(old)
    t_old = basket(old, cfg)
    t_new = basket(new, cfg)
    row = {"cfg": asdict(cfg), "name": cfg.name}
    if len(t_old):
        row["fit"] = smc.metrics(t_old[t_old.coin.isin(fit)])
        row["hold"] = smc.metrics(t_old[t_old.coin.isin(hold)])
        row["old"] = smc.metrics(t_old)
    if len(t_new):
        row["new"] = smc.metrics(t_new)
        row["new_cost10"] = smc.metrics(basket(new, replace(cfg, cost=0.0010)))
        row["new_acct"] = smc_account.account(t_new, risk=0.005)
        rs = t_new.r.sort_values(ascending=False)
        row["new_trim1"] = round(float(rs.iloc[len(rs) // 100:].mean()), 3)
        row["new_by_year"] = {int(k): v for k, v in t_new.groupby(
            t_new.exit_time.dt.year)["r"].mean().round(3).items()}
    return row


def show(row: dict) -> None:
    o, n = row.get("old", {}), row.get("new", {})
    a = row.get("new_acct", {})
    print(f"{row['name']:44s} old n={o.get('n', 0):6d} avgR={o.get('avg_r', 0):+.3f} | "
          f"new n={n.get('n', 0):6d} avgR={n.get('avg_r', 0):+.3f} "
          f"pf={n.get('pf', 0):.2f} win={n.get('win', 0)} "
          f"c10={row.get('new_cost10', {}).get('avg_r', 0):+.3f} "
          f"trim1={row.get('new_trim1', 0):+.3f} "
          f"cagr={a.get('cagr')} dd={a.get('dd_worst')}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    old = [c for c in smc.UNIVERSE if smc.have(c, BASE)]
    new = smc_oos.new_coins()
    if a.quick:
        old, new = old[:5], new[:5]
    print(f"old coins {len(old)}, new coins {len(new)}", flush=True)
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w") as fh:
        for cfg in grid():
            row = evaluate(cfg, old, new)
            fh.write(json.dumps(row, default=str) + "\n")
            show(row)


if __name__ == "__main__":
    main()
