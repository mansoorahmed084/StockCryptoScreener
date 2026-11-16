"""SuperTrend AI (Clustering) [LuxAlgo], rebuilt in Python, and a backtest of it.

    python research/supertrend_ai.py              # the full grid, old + new coins
    python research/supertrend_ai.py --quick      # 10 coins, to check it runs

The indicator (LuxAlgo's free open-source script, default settings):
  * run one SuperTrend for every factor 1.0, 1.5 ... 5.0 on ATR(10)
  * score each one with an EMA (memory 10) of close-to-close change, signed by
    which side of that SuperTrend the previous close was on
  * k-means (k = 3) on the nine scores, centroids seeded at the 25/50/75th
    percentiles; take the mean factor of the BEST cluster
  * one final SuperTrend with that factor is the trailing line; a flip of its
    direction is the signal
  * the score printed on each signal = int(10 x best-cluster score / EMA(10)
    of |close - close[1]|)

Everything is computed from closed bars only. A signal on bar i is entered at
the open of bar i+1.

Trade rules tested (one position per coin):
  * long on a bullish flip, short on a bearish flip (or long only)
  * exit "flip":  leave at the next open after the line flips against us
  * exit "touch": a stop order sits on the trailing line known at the last
    close, so the trade can leave inside a bar; a flip still exits too
  * R = distance from entry to the line at the signal bar; costs per side
  * optional filters: minimum signal score, daily SuperTrend AI bias
  * a stop closer than 0.5% of price is skipped (a gap onto the line)

Out-of-sample means coins: the 203 Binance coins outside the 76-coin
universe (smc_oos.new_coins), never used to choose anything.
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
WARMUP = 200          # bars ignored at the start of each coin
OUT = Path(__file__).resolve().parent / "results" / "supertrend_ai.jsonl"


# ------------------------------------------------------------- indicator
@njit(cache=True)
def _stai(h, l, c, atr, factors, alpha, maxiter):
    n = len(c)
    m = len(factors)
    hl2 = (h + l) / 2.0
    a = 2.0 / (alpha + 1.0)
    ea = 2.0 / (int(alpha) + 1.0)

    den = np.full(n, np.nan)
    for i in range(1, n):
        x = abs(c[i] - c[i - 1])
        den[i] = x if np.isnan(den[i - 1]) else ea * x + (1.0 - ea) * den[i - 1]

    up_f = np.full(m, np.nan)
    lo_f = np.full(m, np.nan)
    tr_f = np.zeros(m, np.int64)
    out_f = np.full(m, np.nan)
    perf = np.zeros(m)

    os_out = np.full(n, -1, np.int64)
    ts = np.full(n, np.nan)
    tfac = np.full(n, np.nan)
    pidx = np.full(n, np.nan)

    upper = np.nan
    lower = np.nan
    os = 0
    target = np.nan
    lab = np.zeros(m, np.int64)

    for i in range(1, n):
        if np.isnan(atr[i]):
            continue
        # one SuperTrend per factor, scored
        for k in range(m):
            up = hl2[i] + atr[i] * factors[k]
            dn = hl2[i] - atr[i] * factors[k]
            pu = up_f[k]
            pl = lo_f[k]
            if not np.isnan(pu):
                if c[i] > pu:
                    tr_f[k] = 1
                elif c[i] < pl:
                    tr_f[k] = 0
            up_f[k] = min(up, pu) if (not np.isnan(pu) and c[i - 1] < pu) else up
            lo_f[k] = max(dn, pl) if (not np.isnan(pl) and c[i - 1] > pl) else dn
            d = 0.0
            if not np.isnan(out_f[k]):
                d = np.sign(c[i - 1] - out_f[k])
            perf[k] += a * ((c[i] - c[i - 1]) * d - perf[k])
            out_f[k] = lo_f[k] if tr_f[k] == 1 else up_f[k]

        # k-means, k = 3, seeded at the quartiles
        cen = np.empty(3)
        cen[0] = np.percentile(perf, 25.0)
        cen[1] = np.percentile(perf, 50.0)
        cen[2] = np.percentile(perf, 75.0)
        for _ in range(maxiter + 1):
            for k in range(m):
                best = -1
                bd = np.inf
                for j in range(3):
                    if np.isnan(cen[j]):
                        continue
                    dd = abs(perf[k] - cen[j])
                    if dd < bd:
                        bd = dd
                        best = j
                lab[k] = best
            new = np.full(3, np.nan)
            for j in range(3):
                s = 0.0
                cnt = 0
                for k in range(m):
                    if lab[k] == j:
                        s += perf[k]
                        cnt += 1
                if cnt > 0:
                    new[j] = s / cnt
            same = True
            for j in range(3):
                if not (new[j] == cen[j]):
                    same = False
            cen = new
            if same:
                break

        fs = 0.0
        ps = 0.0
        cnt = 0
        for k in range(m):
            if lab[k] == 2:
                fs += factors[k]
                ps += perf[k]
                cnt += 1
        pi = 0.0
        if cnt > 0:
            target = fs / cnt
            pi = max(ps / cnt, 0.0)
        if np.isnan(target):
            continue
        pidx[i] = pi / den[i] if den[i] > 0 else 0.0

        # the final SuperTrend on the chosen factor
        up = hl2[i] + atr[i] * target
        dn = hl2[i] - atr[i] * target
        upper = min(up, upper) if (not np.isnan(upper) and c[i - 1] < upper) else up
        lower = max(dn, lower) if (not np.isnan(lower) and c[i - 1] > lower) else dn
        if c[i] > upper:
            os = 1
        elif c[i] < lower:
            os = 0
        ts[i] = lower if os == 1 else upper
        os_out[i] = os
        tfac[i] = target
    return os_out, ts, tfac, pidx


def indicator(df: pd.DataFrame, length: int = 10, fmin: float = 1.0,
              fmax: float = 5.0, step: float = 0.5, alpha: float = 10.0,
              maxiter: int = 1000) -> pd.DataFrame:
    """SuperTrend AI on one OHLC frame. os: 1 = bull, 0 = bear, -1 = warm-up."""
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    atr = smc._atr(h, l, c, length)
    k = int(round((fmax - fmin) / step))
    factors = np.array([fmin + i * step for i in range(k + 1)])
    os_, ts, tf, pi = _stai(h, l, c, atr, factors, alpha, maxiter)
    return pd.DataFrame({"os": os_, "ts": ts, "factor": tf, "perf": pi,
                         "score": np.floor(pi * 10)}, index=df.index)


@lru_cache(maxsize=None)
def frame(coin: str, tf: str) -> pd.DataFrame:
    df = smc.bars(coin, tf, BASE)
    return df.join(indicator(df))


@lru_cache(maxsize=None)
def daily_bias(coin: str, tf: str) -> np.ndarray:
    """Daily SuperTrend AI direction known at each `tf` bar's close (-1 = none)."""
    d = frame(coin, "1d")
    L = frame(coin, tf)
    d_close = (d.index + smc.TF_DELTA["1d"]).to_numpy()
    l_close = (L.index + smc.TF_DELTA[tf]).to_numpy()
    pos = np.searchsorted(d_close, l_close, side="right") - 1
    os_d = d["os"].to_numpy()
    out = np.where(pos >= 0, os_d[np.clip(pos, 0, None)], -1)
    return out.astype(np.int64)


# ------------------------------------------------------------- simulator
@njit(cache=True)
def _sim(o, h, l, c, os_, ts, score, bias, start, side, exit_mode, min_score,
         use_bias, cost, min_risk=0.0):
    n = len(c)
    sig = np.empty(n, np.int64)
    tin = np.empty(n, np.int64)
    tout = np.empty(n, np.int64)
    dirs = np.empty(n, np.int64)
    px = np.empty(n)
    stp0 = np.empty(n)
    rr = np.empty(n)
    why = np.empty(n, np.int64)       # 0 stop, 1 flip, 2 data_end
    mfe = np.empty(n)
    sc = np.empty(n)
    nt = 0

    pos = 0
    e_i = 0
    e_px = 0.0
    risk = 0.0
    s_i = 0
    best = 0.0
    s_sc = 0.0
    s0 = 0.0
    for i in range(max(start, 1), n - 1):
        # 1. manage the open trade on bar i
        if pos != 0 and i >= e_i:
            done = False
            x_px = 0.0
            x_i = i
            x_why = 0
            if exit_mode == 1:
                stop = ts[i - 1]
                if pos > 0 and l[i] <= stop:
                    x_px = min(o[i], stop)
                    done = True
                elif pos < 0 and h[i] >= stop:
                    x_px = max(o[i], stop)
                    done = True
            if not done:
                fav = (h[i] - e_px) if pos > 0 else (e_px - l[i])
                best = max(best, fav / risk)
                flipped = (pos > 0 and os_[i] == 0) or (pos < 0 and os_[i] == 1)
                if flipped:
                    x_px = o[i + 1]
                    x_i = i + 1
                    x_why = 1
                    done = True
            if done:
                g = (x_px - e_px) * pos / risk
                g -= cost * (e_px + x_px) / risk
                sig[nt] = s_i
                tin[nt] = e_i
                tout[nt] = x_i
                dirs[nt] = pos
                px[nt] = e_px
                stp0[nt] = s0
                rr[nt] = g
                why[nt] = x_why
                mfe[nt] = best
                sc[nt] = s_sc
                nt += 1
                pos = 0

        # 2. a new signal on bar i, entered at the next open
        if pos == 0 and os_[i] >= 0 and os_[i - 1] >= 0 and os_[i] != os_[i - 1]:
            d = 1 if os_[i] == 1 else -1
            ok = True
            if side == 1 and d < 0:
                ok = False
            if score[i] < min_score:
                ok = False
            if use_bias:
                if bias[i] < 0 or (d > 0 and bias[i] != 1) or (d < 0 and bias[i] != 0):
                    ok = False
            if ok:
                ep = o[i + 1]
                rk = (ep - ts[i]) * d
                if rk > 0 and rk / ep >= min_risk:
                    pos = d
                    e_i = i + 1
                    e_px = ep
                    risk = rk
                    s_i = i
                    best = 0.0
                    s_sc = score[i]
                    s0 = ts[i]

    if pos != 0:
        x_px = c[n - 1]
        g = (x_px - e_px) * pos / risk - cost * (e_px + x_px) / risk
        sig[nt] = s_i
        tin[nt] = e_i
        tout[nt] = n - 1
        dirs[nt] = pos
        px[nt] = e_px
        stp0[nt] = s0
        rr[nt] = g
        why[nt] = 2
        mfe[nt] = best
        sc[nt] = s_sc
        nt += 1
    return (sig[:nt], tin[:nt], tout[:nt], dirs[:nt], px[:nt], stp0[:nt],
            rr[:nt], why[:nt], mfe[:nt], sc[:nt])


WHY = np.array(["stop", "flip", "data_end"])
SIDE = {"long": 1, "both": 2}
EXIT = {"flip": 0, "touch": 1}


@dataclass(frozen=True)
class Cfg:
    tf: str = "4h"
    side: str = "both"
    exit: str = "flip"
    min_score: int = 0
    bias: bool = False
    cost: float = smc.COST
    # a stop closer than this is skipped: one OG trade 0.02% wide booked +11,095R
    min_risk: float = 0.005

    @property
    def name(self) -> str:
        b = "+1dBias" if self.bias else ""
        return f"{self.tf} {self.side} {self.exit} s>={self.min_score}{b}"


def run(coin: str, cfg: Cfg) -> pd.DataFrame:
    F = frame(coin, cfg.tf)
    bias = daily_bias(coin, cfg.tf) if cfg.bias else np.zeros(len(F), np.int64)
    res = _sim(F["open"].to_numpy(float), F["high"].to_numpy(float),
               F["low"].to_numpy(float), F["close"].to_numpy(float),
               F["os"].to_numpy(np.int64), F["ts"].to_numpy(float),
               F["score"].fillna(-1).to_numpy(float), bias, WARMUP,
               SIDE[cfg.side], EXIT[cfg.exit], float(cfg.min_score),
               cfg.bias, cfg.cost, cfg.min_risk)
    s, ti, to, d, px, st, r, why, mfe, sc = res
    idx = F.index
    return pd.DataFrame({
        "coin": coin, "sig": idx[s], "entry_time": idx[ti],
        "exit_time": idx[to], "dir": d, "kind": "st", "entry": px,
        "stop": st, "r": r, "why": WHY[why], "mfe": mfe, "score": sc,
        "risk_pct": np.abs(px - st) / px,
    })


def basket(coins: list[str], cfg: Cfg) -> pd.DataFrame:
    frames = [run(c, cfg) for c in coins]
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ------------------------------------------------------------------ grid
def grid() -> list[Cfg]:
    out = []
    for tf, side, ex, ms, b in itertools.product(
            ("1h", "4h", "1d"), ("long", "both"), ("flip", "touch"),
            (0, 3), (False, True)):
        if tf == "1d" and b:
            continue
        out.append(Cfg(tf, side, ex, ms, b))
    return out


def evaluate(cfg: Cfg, old: list[str], new: list[str]) -> dict:
    fit, hold = smc.split(old)
    t_old = basket(old, cfg)
    t_new = basket(new, cfg)
    stress = basket(new, replace(cfg, cost=0.0010))
    row = {"cfg": asdict(cfg), "name": cfg.name}
    if len(t_old):
        row["fit"] = smc.metrics(t_old[t_old.coin.isin(fit)])
        row["hold"] = smc.metrics(t_old[t_old.coin.isin(hold)])
        row["old"] = smc.metrics(t_old)
    if len(t_new):
        row["new"] = smc.metrics(t_new)
        rs = t_new.r.sort_values(ascending=False)
        row["new_trim1"] = round(float(rs.iloc[len(rs) // 100:].mean()), 3)
        row["new_median"] = round(float(rs.median()), 3)
        bc = t_new.groupby("coin").r.sum()
        row["new_top_coin_share"] = round(float(bc.max() / rs.sum()), 2) if rs.sum() > 0 else None
        row["new_cost10"] = smc.metrics(stress)
        row["new_acct"] = smc_account.account(t_new, risk=0.005)
        row["new_by_year"] = {int(k): v for k, v in t_new.groupby(
            t_new.exit_time.dt.year)["r"].mean().round(3).items()}
        row["new_by_score"] = {int(k): [int(n), round(float(m), 3)] for k, (n, m) in
                               t_new.groupby(t_new.score.clip(upper=10))["r"]
                               .agg(["size", "mean"]).iterrows()}
    return row


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
            o, n = row.get("old", {}), row.get("new", {})
            print(f"{cfg.name:28s} old n={o.get('n',0):5d} avgR={o.get('avg_r',0):+.3f} "
                  f"pf={o.get('pf',0):.2f} | new n={n.get('n',0):5d} "
                  f"avgR={n.get('avg_r',0):+.3f} pf={n.get('pf',0):.2f} "
                  f"win={n.get('win',0)} c10={row.get('new_cost10',{}).get('avg_r',0):+.3f} "
                  f"trim1={row.get('new_trim1', 0):+.3f} top={row.get('new_top_coin_share')}",
                  flush=True)


if __name__ == "__main__":
    main()
