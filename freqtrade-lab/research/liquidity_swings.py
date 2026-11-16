"""Liquidity Swings [LuxAlgo], rebuilt in Python, and two tests of it.

    python research/liquidity_swings.py           # both tests, old + new coins
    python research/liquidity_swings.py --quick   # 5 + 5 coins

LuxAlgo's page shows no code, so this follows its published description and
defaults:
  * a swing high is a pivot high with 14 bars on each side (known 14 bars
    later). Its zone is the wick: from max(open, close) up to the high.
    A swing low mirrors it: from the low up to min(open, close).
  * a zone stays live until a candle CLOSES beyond it (above a high zone,
    below a low zone)
  * count = candles that touched the live zone since it was confirmed
    (LuxAlgo's "Filter Areas By: Count")
  * a SWEEP of a zone = a candle wicks beyond the zone's extreme and closes
    back on the inside

Test A, standalone: trade the reversal after a sweep. Long after a swing-low
sweep, short after a swing-high sweep. Entry next open; stop beyond the sweep
wick by 0.1 ATR; fixed R target; stop tested first; 42-bar time stop. One
trade per zone.

Test B, inside SMC sweep-break (B_final, the only survivor): the origin candle
of the 4h break must sweep a Liquidity Swings zone instead of the last k=5
fractal swing. Everything else unchanged.

Out-of-sample = the 203 coins outside the 76-coin universe.
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
MAXZ = 64             # live zones kept per side
OUT = Path(__file__).resolve().parent / "results" / "liquidity_swings.jsonl"


# ------------------------------------------------------------- indicator
@njit(cache=True)
def _zones(o, h, l, c, ph, phi, pl, pli, wick):
    """Per bar t, the sweeps of zones that were live BEFORE bar t.

    lo_any[t]    highest count among live swing-low zones that bar t swept
                 (-1 = none); hi_any[t] the swing-high mirror
    lo_last[t]   count of the LATEST swing-low zone if bar t swept it, else -1
    lo_id/hi_id  id of the zone swept (latest-zone sweep, else best-count one)
    lz_btm[t] .. the latest zone's edges after bar t (for plotting / tests)
    """
    n = len(c)
    lo_any = np.full(n, -1, np.int64)
    hi_any = np.full(n, -1, np.int64)
    lo_last = np.full(n, -1, np.int64)
    hi_last = np.full(n, -1, np.int64)
    lo_id = np.full(n, -1, np.int64)
    hi_id = np.full(n, -1, np.int64)
    lo_id_last = np.full(n, -1, np.int64)
    hi_id_last = np.full(n, -1, np.int64)
    lz_btm = np.full(n, np.nan)
    lz_top = np.full(n, np.nan)
    hz_btm = np.full(n, np.nan)
    hz_top = np.full(n, np.nan)

    # live zones: edge (the extreme), inner edge, count, id
    le = np.full(MAXZ, np.nan)
    li = np.full(MAXZ, np.nan)
    lc = np.zeros(MAXZ, np.int64)
    lid = np.full(MAXZ, -1, np.int64)
    he = np.full(MAXZ, np.nan)
    hi_ = np.full(MAXZ, np.nan)
    hc = np.zeros(MAXZ, np.int64)
    hid = np.full(MAXZ, -1, np.int64)
    last_l = -1      # slot of the latest low zone
    last_h = -1
    nid = 0

    for t in range(n):
        # 1. sweeps of zones live before this bar
        for s in range(MAXZ):
            if lid[s] >= 0 and l[t] < le[s] and c[t] >= le[s]:
                if lc[s] > lo_any[t]:
                    lo_any[t] = lc[s]
                    lo_id[t] = lid[s]
                if s == last_l:
                    lo_last[t] = lc[s]
                    lo_id_last[t] = lid[s]
            if hid[s] >= 0 and h[t] > he[s] and c[t] <= he[s]:
                if hc[s] > hi_any[t]:
                    hi_any[t] = hc[s]
                    hi_id[t] = hid[s]
                if s == last_h:
                    hi_last[t] = hc[s]
                    hi_id_last[t] = hid[s]
        # 2. this bar touches / kills zones
        for s in range(MAXZ):
            if lid[s] >= 0:
                if l[t] < li[s] and h[t] > le[s]:
                    lc[s] += 1
                if c[t] < le[s]:
                    lid[s] = -1
                    if s == last_l:
                        last_l = -1
            if hid[s] >= 0:
                if h[t] > hi_[s] and l[t] < he[s]:
                    hc[s] += 1
                if c[t] > he[s]:
                    hid[s] = -1
                    if s == last_h:
                        last_h = -1
        # 3. new zones confirmed at this bar
        if not np.isnan(pl[t]):
            i = pli[t]
            s = nid % MAXZ
            le[s] = l[i]
            li[s] = min(o[i], c[i]) if wick else h[i]
            lc[s] = 0
            lid[s] = nid
            last_l = s
            nid += 1
            # the zone may already be dead: a close below it since the pivot
            for j in range(i + 1, t + 1):
                if c[j] < le[s]:
                    lid[s] = -1
                    last_l = -1
                    break
        if not np.isnan(ph[t]):
            i = phi[t]
            s = nid % MAXZ
            he[s] = h[i]
            hi_[s] = max(o[i], c[i]) if wick else l[i]
            hc[s] = 0
            hid[s] = nid
            last_h = s
            nid += 1
            for j in range(i + 1, t + 1):
                if c[j] > he[s]:
                    hid[s] = -1
                    last_h = -1
                    break
        if last_l >= 0:
            lz_btm[t] = le[last_l]
            lz_top[t] = li[last_l]
        if last_h >= 0:
            hz_btm[t] = hi_[last_h]
            hz_top[t] = he[last_h]
    return (lo_any, hi_any, lo_last, hi_last, lo_id, hi_id, lo_id_last,
            hi_id_last, lz_btm, lz_top, hz_btm, hz_top)


ZCOLS = ("lo_any", "hi_any", "lo_last", "hi_last", "lo_id", "hi_id",
         "lo_id_last", "hi_id_last", "lz_btm", "lz_top", "hz_btm", "hz_top")


def zones(df: pd.DataFrame, length: int = 14, wick: bool = True) -> pd.DataFrame:
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    ph, phi, pl, pli = smc._pivots(h, l, length)
    return pd.DataFrame(dict(zip(ZCOLS, _zones(o, h, l, c, ph, phi, pl, pli, wick))),
                        index=df.index)


@lru_cache(maxsize=None)
def frame(coin: str, tf: str, length: int = 14) -> pd.DataFrame:
    df = smc.bars(coin, tf, BASE)
    z = zones(df, length)
    z["atr"] = smc._atr(df["high"].to_numpy(float), df["low"].to_numpy(float),
                        df["close"].to_numpy(float), 14)
    return df.join(z)


# ------------------------------------------------------ test A: reversal
@njit(cache=True)
def _sim_rev(o, h, l, c, atr, lo_cnt, hi_cnt, lo_id, hi_id, bias, use_bias,
             min_cnt, tp_r, max_hold, sl_buf, min_risk, max_risk, cost):
    n = len(c)
    out_i = np.empty(n, np.int64)
    out_x = np.empty(n, np.int64)
    out_d = np.empty(n, np.int64)
    out_px = np.empty(n)
    out_st = np.empty(n)
    out_r = np.empty(n)
    out_w = np.empty(n, np.int64)     # 0 stop, 1 target, 2 time, 3 data_end
    nt = 0
    used = np.zeros(2 * n + 2, np.bool_)  # at most two zone ids per bar
    busy_until = -1
    for t in range(20, n - 1):
        if t <= busy_until or np.isnan(atr[t]):
            continue
        d = 0
        if lo_cnt[t] >= min_cnt and lo_id[t] >= 0 and not used[lo_id[t]]:
            d = 1
        elif hi_cnt[t] >= min_cnt and hi_id[t] >= 0 and not used[hi_id[t]]:
            d = -1
        if d == 0:
            continue
        if use_bias and bias[t] != d:
            continue
        ep = o[t + 1]
        stop = l[t] - sl_buf * atr[t] if d > 0 else h[t] + sl_buf * atr[t]
        risk = (ep - stop) * d
        if risk <= 0 or risk / ep < min_risk or risk / ep > max_risk:
            continue
        used[lo_id[t] if d > 0 else hi_id[t]] = True
        tgt = ep + d * tp_r * risk
        x_px = c[n - 1]
        x_i = n - 1
        why = 3
        for j in range(t + 1, n):
            if d > 0 and l[j] <= stop:
                x_px = min(o[j], stop)
                x_i = j
                why = 0
                break
            if d < 0 and h[j] >= stop:
                x_px = max(o[j], stop)
                x_i = j
                why = 0
                break
            if d > 0 and h[j] >= tgt:
                x_px = max(o[j], tgt)
                x_i = j
                why = 1
                break
            if d < 0 and l[j] <= tgt:
                x_px = min(o[j], tgt)
                x_i = j
                why = 1
                break
            if j - t >= max_hold:
                x_px = c[j]
                x_i = j
                why = 2
                break
        r = (x_px - ep) * d / risk - cost * (ep + x_px) / risk
        out_i[nt] = t + 1
        out_x[nt] = x_i
        out_d[nt] = d
        out_px[nt] = ep
        out_st[nt] = stop
        out_r[nt] = r
        out_w[nt] = why
        nt += 1
        busy_until = x_i
    return (out_i[:nt], out_x[:nt], out_d[:nt], out_px[:nt], out_st[:nt],
            out_r[:nt], out_w[:nt])


WHY_A = np.array(["stop", "target", "time", "data_end"])


@dataclass(frozen=True)
class RevCfg:
    tf: str = "4h"
    zone: str = "last"        # last | any
    min_cnt: int = 0
    tp_r: float = 2.0
    bias: bool = False        # trade only with the daily structure trend
    max_hold: int = 42
    sl_buf: float = 0.1
    min_risk: float = 0.005
    max_risk: float = 0.08
    cost: float = smc.COST

    @property
    def name(self) -> str:
        return (f"A {self.tf} {self.zone} cnt>={self.min_cnt} {self.tp_r:g}R"
                + (" +1dBias" if self.bias else ""))


@lru_cache(maxsize=None)
def _bias(coin: str, tf: str) -> np.ndarray:
    return smc.htf_on_ltf(coin, tf, "1d", 2, 6, BASE)["htrend"].astype(np.int64)


def run_rev(coin: str, cfg: RevCfg) -> pd.DataFrame:
    F = frame(coin, cfg.tf)
    k = "any" if cfg.zone == "any" else "last"
    lo_c = F["lo_any" if k == "any" else "lo_last"].to_numpy(np.int64)
    hi_c = F["hi_any" if k == "any" else "hi_last"].to_numpy(np.int64)
    lo_i = F["lo_id" if k == "any" else "lo_id_last"].to_numpy(np.int64)
    hi_i = F["hi_id" if k == "any" else "hi_id_last"].to_numpy(np.int64)
    bias = _bias(coin, cfg.tf) if cfg.bias else np.zeros(len(F), np.int64)
    ti, tx, d, px, st, r, w = _sim_rev(
        F["open"].to_numpy(float), F["high"].to_numpy(float),
        F["low"].to_numpy(float), F["close"].to_numpy(float),
        F["atr"].to_numpy(float), lo_c, hi_c, lo_i, hi_i, bias, cfg.bias,
        cfg.min_cnt, cfg.tp_r, cfg.max_hold, cfg.sl_buf, cfg.min_risk,
        cfg.max_risk, cfg.cost)
    idx = F.index
    return pd.DataFrame({"coin": coin, "entry_time": idx[ti],
                         "exit_time": idx[tx], "dir": d, "entry": px,
                         "stop": st, "r": r, "why": WHY_A[w],
                         "risk_pct": np.abs(px - st) / px})


# ------------------------------------------- test B: inside sweep-break
B_FINAL = smc_oos.FINALISTS["B_final"]


@dataclass(frozen=True)
class SBCfg:
    sweep: str = "fractal"    # fractal (B_final as is) | last | any | union
    length: int = 14
    min_cnt: int = 0
    cost: float = smc.COST

    @property
    def name(self) -> str:
        if self.sweep == "fractal":
            return "B B_final (fractal k=5 sweep)"
        return f"B sweep={self.sweep} len={self.length} cnt>={self.min_cnt}"


def run_sb(coin: str, cfg: SBCfg) -> pd.DataFrame:
    sc = replace(B_FINAL, cost=cfg.cost)
    L = dict(smc.structure(coin, sc.ltf, sc.k_ltf, BASE))
    H = smc.htf_on_ltf(coin, sc.ltf, sc.htf, sc.k_htf, sc.sweep_life, BASE)
    X = smc.extras(coin, sc.ltf, BASE)
    if cfg.sweep != "fractal":
        F = frame(coin, sc.ltf, cfg.length)
        ev, orgi = L["ev"], L["orgi"]
        if cfg.sweep in ("any", "union"):
            lo, hi = F["lo_any"].to_numpy(), F["hi_any"].to_numpy()
        else:
            lo, hi = F["lo_last"].to_numpy(), F["hi_last"].to_numpy()
        k = np.clip(orgi, 0, None)
        ls = np.where(ev > 0, lo[k] >= cfg.min_cnt,
                      np.where(ev < 0, hi[k] >= cfg.min_cnt, False))
        ls &= (ev != 0) & (orgi >= 0)
        L["swept"] = (ls | L["swept"]) if cfg.sweep == "union" else ls
    return smc.trades_of(coin, sc, L, H, X)


# ------------------------------------------------------------------ grid
def grid_a() -> list[RevCfg]:
    out = []
    for tf, zone, mc, tp, b in itertools.product(
            ("1h", "4h", "1d"), ("last", "any"), (0, 3, 6), (2.0, 3.0),
            (False, True)):
        if tf == "1d" and b:
            continue
        out.append(RevCfg(tf, zone, mc, tp, b))
    return out


def grid_b() -> list[SBCfg]:
    out = [SBCfg()]
    for sw, ln, mc in itertools.product(("last", "any", "union"), (5, 14),
                                        (0, 3, 6)):
        out.append(SBCfg(sw, ln, mc))
    return out


def basket(run, coins, cfg) -> pd.DataFrame:
    fr = [run(c, cfg) for c in coins]
    fr = [f for f in fr if len(f)]
    return pd.concat(fr, ignore_index=True) if fr else pd.DataFrame()


def evaluate(run, cfg, old, new) -> dict:
    fit, hold = smc.split(old)
    t_old = basket(run, old, cfg)
    t_new = basket(run, new, cfg)
    row = {"cfg": asdict(cfg), "name": cfg.name}
    if len(t_old):
        row["fit"] = smc.metrics(t_old[t_old.coin.isin(fit)])
        row["hold"] = smc.metrics(t_old[t_old.coin.isin(hold)])
        row["old"] = smc.metrics(t_old)
    if len(t_new):
        row["new"] = smc.metrics(t_new)
        row["new_cost10"] = smc.metrics(basket(run, new, replace(cfg, cost=0.0010)))
        row["new_acct"] = smc_account.account(t_new, risk=0.005)
        rs = t_new.r.sort_values(ascending=False)
        row["new_trim1"] = round(float(rs.iloc[len(rs) // 100:].mean()), 3)
        row["new_by_year"] = {int(k): v for k, v in t_new.groupby(
            t_new.exit_time.dt.year)["r"].mean().round(3).items()}
    return row


def show(row: dict) -> None:
    o, n = row.get("old", {}), row.get("new", {})
    a = row.get("new_acct", {})
    print(f"{row['name']:40s} old n={o.get('n', 0):5d} avgR={o.get('avg_r', 0):+.3f} | "
          f"new n={n.get('n', 0):5d} avgR={n.get('avg_r', 0):+.3f} "
          f"pf={n.get('pf', 0):.2f} win={n.get('win', 0)} "
          f"c10={row.get('new_cost10', {}).get('avg_r', 0):+.3f} "
          f"trim1={row.get('new_trim1', 0):+.3f} "
          f"cagr={a.get('cagr')} dd={a.get('dd_worst')}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only", choices=("a", "b"))
    a = ap.parse_args()
    old = [c for c in smc.UNIVERSE if smc.have(c, BASE)]
    new = smc_oos.new_coins()
    if a.quick:
        old, new = old[:5], new[:5]
    print(f"old coins {len(old)}, new coins {len(new)}", flush=True)
    OUT.parent.mkdir(exist_ok=True)
    jobs = []
    if a.only != "a":
        jobs += [(run_sb, c) for c in grid_b()]
    if a.only != "b":
        jobs += [(run_rev, c) for c in grid_a()]
    with OUT.open("w") as fh:
        for run, cfg in jobs:
            row = evaluate(run, cfg, old, new)
            fh.write(json.dumps(row, default=str) + "\n")
            show(row)


if __name__ == "__main__":
    main()
