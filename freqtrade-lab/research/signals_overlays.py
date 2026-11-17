"""Signals & Overlays Toolkit (OWN BUILD), in Python, and a backtest of it.

    python research/signals_overlays.py            # the full grid, old + new coins
    python research/signals_overlays.py --quick    # 5 + 5 coins, to check it runs

This is NOT LuxAlgo's Signals & Overlays. That script is paid and closed. This
is the Python twin of tradestation-pine/signals_overlays_own.pine: the same
feature list as LuxAlgo's public docs describe, with our own formulas. A result
here says nothing about LuxAlgo's real signals.

The indicator (all from closed bars):
  * Confirmation signal = ATR band flip (SuperTrend). Band = hl2 +/-
    sensitivity x 0.25 x ATR(10). Strong (+) = the flip agrees with the 200 EMA.
  * Contrarian signal = RSI (length = sensitivity) leaves oversold (30) or
    overbought (70). Strong (+) = RSI went past 20 / 80 during that visit.
  * Exit cross: Confirmation = RSI(14) crosses back under 70 (over 30 for a
    short) while the trade is in profit against the signal close. Contrarian =
    RSI back at 50 while in profit, once per signal.
  * Autopilot = every sensitivity in a range runs side by side; the one with
    the best sum of position x close-to-close return over 250 bars drives the
    signals. Short 5..10, Medium 10..20, Long 20..30.
  * Classifier = class 1..4 from where (close - EMA200) / ATR(14) sits among
    its own last 200 values.
  * Overlays: Smart Trail (ATR trailing stop), Reversal Zones (mean +/- 2 to 3
    standard deviations), Trend Tracer (step line), Trend Catcher (Kaufman
    adaptive average), Neo Cloud (two Donchian mid-lines).
  * Trend Strength = min(100, 2 x ADX(14)).
  Not ported: the dashboard's Volatility, Squeeze and Volume Sentiment cells.

Trade rules tested (one position per coin, entry at the next open):
  * long on a bullish signal, short on a bearish one (or long only)
  * all signals, or only the strong (+) ones
  * stop = signal close -/+ 2 ATR(14) (the toolkit's "SL 1" at Distance 5)
  * exit "flip":  leave at the next open after an opposite signal
    exit "cross": the same, and also at the next open after an exit cross
    exit "3R":    fixed 3R target, 42-bar time stop, stop tested first
  * stops closer than 0.5% or wider than 15% are skipped; 0.06% per side
  * round 2 turns one dial at a time on 4h and 1d: each filter, each
    Autopilot range, classifier classes 1-2 or 3-4, sensitivity, a 4 ATR stop

Out-of-sample means coins: the 203 coins outside the 76-coin universe.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smc           # noqa: E402
import smc_account   # noqa: E402
import smc_oos       # noqa: E402

BASE = "1h"
WARMUP = 400          # EMA200, then 200 bars for the classifier window
OUT = Path(__file__).resolve().parent / "results" / "signals_overlays.jsonl"

AUTO_RANGE = {"off": (10, 20), "short": (5, 10), "medium": (10, 20),
              "long": (20, 30)}
OS, OB, OS_STRONG, OB_STRONG = 30.0, 70.0, 20.0, 80.0


# ------------------------------------------------------------- primitives
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
def _rma(x, n):
    """Pine's rma: starts at the SMA of the first n values that are not NaN."""
    out = np.full(len(x), np.nan)
    i0 = 0
    while i0 < len(x) and np.isnan(x[i0]):
        i0 += 1
    if len(x) - i0 < n:
        return out
    a = x[i0:i0 + n].mean()
    out[i0 + n - 1] = a
    for i in range(i0 + n, len(x)):
        a = (a * (n - 1) + x[i]) / n
        out[i] = a
    return out


def _prev(x):
    return np.concatenate([[np.nan], x[:-1]])


def _roll(x, n, how):
    return getattr(pd.Series(x).rolling(n), how)().to_numpy()


def rsi(c, n=14):
    """Pine's ta.rsi."""
    ch = c - _prev(c)
    up = _rma(np.where(np.isnan(ch), np.nan, np.maximum(ch, 0.0)), n)
    dn = _rma(np.where(np.isnan(ch), np.nan, np.maximum(-ch, 0.0)), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100.0 - 100.0 / (1.0 + up / dn)
    r = np.where(dn == 0, 100.0, np.where(up == 0, 0.0, r))
    return np.where(np.isnan(up), np.nan, r)


def adx(h, l, c, n=14):
    """Pine's ta.dmi(n, n), the ADX part."""
    up = h - _prev(h)
    dn = _prev(l) - l
    pdm = np.where(np.isnan(up), np.nan, np.where((up > dn) & (up > 0), up, 0.0))
    mdm = np.where(np.isnan(dn), np.nan, np.where((dn > up) & (dn > 0), dn, 0.0))
    pc = _prev(c)
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))   # NaN on bar 0
    trur = _rma(tr, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus = 100.0 * _rma(pdm, n) / trur
        minus = 100.0 * _rma(mdm, n) / trur
        s = plus + minus
        dx = np.abs(plus - minus) / np.where(s == 0, 1.0, s)
    return 100.0 * _rma(dx, n)


# ---------------------------------------------------------- signal engines
@njit(cache=True)
def _conf(centre, c, atr, sens, fac):
    """Direction (+1 / -1) of one band flip per sensitivity. The band is `centre`
    +/- sensitivity x fac x atr. Starts at +1."""
    k, n = len(sens), len(c)
    out = np.ones((k, n), np.int8)
    for j in range(k):
        pu = np.nan
        pl = np.nan
        d = 1
        for t in range(n):
            if t >= 1 and not np.isnan(atr[t]):
                mid = centre[t]
                w = sens[j] * fac * atr[t]
                u = mid + w
                lo = mid - w
                pc = c[t - 1]
                nu = u if (np.isnan(pu) or u < pu or pc > pu) else pu
                nl = lo if (np.isnan(pl) or lo > pl or pc < pl) else pl
                if d == 1:
                    d = -1 if c[t] < nl else 1
                else:
                    d = 1 if c[t] > nu else -1
                pu = nu
                pl = nl
            out[j, t] = d
    return out


@njit(cache=True)
def _cont(c, lens, os_, ob, os_strong, ob_strong):
    """RSI reversal signals per length: +1/+2 leaving oversold, -1/-2 leaving
    overbought (2 = RSI went past the strong level during that visit)."""
    k, n = len(lens), len(c)
    sig = np.zeros((k, n), np.int8)
    rs = np.full((k, n), np.nan)
    for j in range(k):
        ln = lens[j]
        au = np.nan
        ad = np.nan
        pr = np.nan
        e = np.nan
        for t in range(1, n):
            ch = c[t] - c[t - 1]
            gain = max(ch, 0.0)
            loss = max(-ch, 0.0)
            au = gain if np.isnan(au) else au + (gain - au) / ln
            ad = loss if np.isnan(ad) else ad + (loss - ad) / ln
            if ad == 0:
                r = 50.0 if au == 0 else 100.0
            else:
                r = 100 - 100 / (1 + au / ad)
            s = 0
            if t > 3 * ln and not np.isnan(pr):
                ref = pr if np.isnan(e) else e
                if pr < os_ and r >= os_:
                    s = 2 if ref <= os_strong else 1
                elif pr > ob and r <= ob:
                    s = -2 if ref >= ob_strong else -1
            if r < os_:
                e = r if (np.isnan(e) or pr >= os_) else min(e, r)
            elif r > ob:
                e = r if (np.isnan(e) or pr <= ob) else max(e, r)
            else:
                e = np.nan
            sig[j, t] = s
            rs[j, t] = r
            pr = r
    return sig, rs


@njit(cache=True)
def _held(sig):
    """Position each contrarian engine holds after each bar: its last signal's side."""
    k, n = sig.shape
    out = np.zeros((k, n), np.int8)
    for j in range(k):
        p = 0
        for t in range(n):
            if sig[j, t] > 0:
                p = 1
            elif sig[j, t] < 0:
                p = -1
            out[j, t] = p
    return out


@njit(cache=True)
def _best(pos, c, gb):
    """Index of the engine with the best sum of (position held into the bar x
    close-to-close return) over the last `gb` bars. Ties go to the lower index."""
    k, n = pos.shape
    ring = np.zeros((k, gb))
    s = np.zeros(k)
    best = np.zeros(n, np.int64)
    for t in range(n):
        # whole millionths: the sums stay exact, so equal engines tie exactly
        ret = 0.0 if t == 0 else np.floor(1e6 * (c[t] - c[t - 1]) / c[t - 1] + 0.5)
        slot = t % gb
        for j in range(k):
            p = pos[j, t - 1] if t > 0 else 0
            cc = p * ret
            s[j] = s[j] + cc - ring[j, slot]
            ring[j, slot] = cc
        b = 0
        for j in range(1, k):
            if s[j] > s[b]:
                b = j
        best[t] = b
    return best


@njit(cache=True)
def _pick(rows, best, user, gb):
    """Row `best[t]` of `rows` from bar `gb` on, the user's row before that."""
    n = len(best)
    out = user.copy()
    for t in range(gb, n):
        out[t] = rows[best[t], t]
    return out


@njit(cache=True)
def _conf_sig(d, trend_up, trend_dn):
    """+-1 on a flip of `d`, +-2 when the flip agrees with the trend state."""
    n = len(d)
    out = np.zeros(n, np.int8)
    for t in range(1, n):
        if d[t] == 1 and d[t - 1] == -1:
            out[t] = 2 if trend_up[t] else 1
        elif d[t] == -1 and d[t - 1] == 1:
            out[t] = -2 if trend_dn[t] else -1
    return out


@njit(cache=True)
def _cls_hi(gz, n_look):
    """1 + how many of the window's 25/50/75th nearest-rank percentiles the
    current value is above. 1 while the window is not full."""
    n = len(gz)
    out = np.ones(n, np.int8)
    k1 = int(np.ceil(0.25 * n_look))
    k2 = int(np.ceil(0.50 * n_look))
    k3 = int(np.ceil(0.75 * n_look))
    for t in range(n_look - 1, n):
        g = gz[t]
        cnt = 0
        ok = True
        for i in range(t - n_look + 1, t + 1):
            x = gz[i]
            if np.isnan(x):
                ok = False
                break
            if x < g:
                cnt += 1
        if ok:
            out[t] = 1 + (cnt >= k1) + (cnt >= k2) + (cnt >= k3)
    return out


@njit(cache=True)
def _final(raw, pass_bull, pass_bear, ml_ok, c, is_conf, x_dn, x_up, crsi):
    """Filtered signals and the exit crosses that belong to them."""
    n = len(raw)
    sig = np.zeros(n, np.int8)
    ex = np.zeros(n, np.int8)
    pos = 0
    entry = np.nan
    done = False
    for t in range(n):
        s = raw[t]
        if s > 0 and pass_bull[t] and ml_ok[t]:
            pos, entry, done = 1, c[t], False
            sig[t] = s
        elif s < 0 and pass_bear[t] and ml_ok[t]:
            pos, entry, done = -1, c[t], False
            sig[t] = s
        elif pos == 1 and c[t] > entry:
            if is_conf:
                if x_dn[t]:
                    ex[t] = 1
            elif not done and crsi[t] >= 50:
                ex[t] = 1
                done = True
        elif pos == -1 and c[t] < entry:
            if is_conf:
                if x_up[t]:
                    ex[t] = -1
            elif not done and crsi[t] <= 50:
                ex[t] = -1
                done = True
    return sig, ex


# ----------------------------------------------------------------- overlays
@njit(cache=True)
def _trail(c, w):
    n = len(c)
    out = np.full(n, np.nan)
    dr = np.ones(n, np.int8)
    tr = np.nan
    d = 1
    for t in range(n):
        if not np.isnan(w[t]):
            if np.isnan(tr):
                tr = c[t] - w[t]
            elif d == 1:
                if c[t] < tr:
                    d = -1
                    tr = c[t] + w[t]
                else:
                    tr = max(tr, c[t] - w[t])
            else:
                if c[t] > tr:
                    d = 1
                    tr = c[t] - w[t]
                else:
                    tr = min(tr, c[t] + w[t])
        out[t] = tr
        dr[t] = d
    return out, dr


@njit(cache=True)
def _tracer(c, rng):
    n = len(c)
    out = np.full(n, np.nan)
    dr = np.zeros(n, np.int8)
    tr = np.nan
    d = 0
    for t in range(n):
        if not np.isnan(rng[t]):
            p = tr
            if np.isnan(tr):
                tr = c[t]
            elif c[t] > tr:
                tr = max(tr, c[t] - rng[t])
            else:
                tr = min(tr, c[t] + rng[t])
            if np.isnan(p):
                d = 0
            elif tr > p:
                d = 1
            elif tr < p:
                d = -1
        out[t] = tr
        dr[t] = d
    return out, dr


@njit(cache=True)
def _catcher(c, sc, atr):
    n = len(c)
    out = np.empty(n)
    dr = np.zeros(n, np.int8)
    k = c[0]
    d = 0
    out[0] = k
    for t in range(1, n):
        p = k
        k = k + sc[t] * (c[t] - k)
        mv = k - p
        lim = 0.0 if np.isnan(atr[t]) else 0.02 * atr[t]
        if mv > lim:
            d = 1
        elif mv < -lim:
            d = -1
        out[t] = k
        dr[t] = d
    return out, dr


@njit(cache=True)
def _neo(lead, lag):
    n = len(lead)
    dr = np.zeros(n, np.int8)
    d = 0
    for t in range(n):
        if lead[t] > lag[t]:
            d = 1
        elif lead[t] < lag[t]:
            d = -1
        dr[t] = d
    return dr


@njit(cache=True)
def _tpsl(h, l, c, atr, t_bull, t_bear, dist):
    """The four TP/SL levels as drawn (NaN on the bar they move), and the
    one-shot TP 1 / SL 1 hits."""
    n = len(c)
    lv = np.full((4, n), np.nan)
    hit = np.zeros((2, n), np.bool_)
    d = 0
    tp1 = tp2 = sl1 = sl2 = np.nan
    tp_done = sl_done = False
    for t in range(n):
        unit = dist * atr[t]
        if d != 0 and not tp_done and ((d == 1 and h[t] >= tp1) or (d == -1 and l[t] <= tp1)):
            hit[0, t] = True
            tp_done = True
        if d != 0 and not sl_done and ((d == 1 and l[t] <= sl1) or (d == -1 and h[t] >= sl1)):
            hit[1, t] = True
            sl_done = True
        past = d != 0 and (d * (c[t] - tp2) > 0 or d * (c[t] - sl2) < 0)
        moved = (not np.isnan(unit)) and (t_bull[t] or t_bear[t] or past)
        if moved:
            if t_bull[t]:
                d = 1
            elif t_bear[t]:
                d = -1
            tp1 = c[t] + d * 0.4 * unit
            tp2 = c[t] + d * 0.8 * unit
            sl1 = c[t] - d * 0.4 * unit
            sl2 = c[t] - d * 0.8 * unit
            tp_done = sl_done = False
        if d != 0 and not moved:
            lv[0, t], lv[1, t], lv[2, t], lv[3, t] = tp1, tp2, sl1, sl2
    return lv, hit


# ---------------------------------------------------------------- one coin
class Book:
    """Everything the toolkit computes on one OHLCV frame. The heavy parts are
    built once and reused by every setting."""

    def __init__(self, df: pd.DataFrame, trail_p: int = 3, rz_p: int = 3,
                 catcher_p: int = 3, tracer_p: int = 3, neo_p: int = 2,
                 fac: float = 0.25, base_len: int = 200, grid_bars: int = 250,
                 ml_len: int = 200, style: str = "own"):
        """style "own" = the tested build: band on hl2 +/- sensitivity x 0.25 x
        ATR(10), strong = with the 200 EMA. style "lux" = the settings that came
        closest to LuxAlgo's chart (our picture comparison, see
        reports/LUXALGO_SUMMARY.md step 4): band on
        ohlc4 +/- sensitivity x 0.165 x the 30-bar mean true range, strong and
        candle colour = EMA20 against EMA26."""
        self.index = df.index
        self.o, self.h, self.l, self.c = (df[x].to_numpy(float) for x in
                                          ("open", "high", "low", "close"))
        o, h, l, c = self.o, self.h, self.l, self.c
        self.n = len(c)
        self.fac, self.gb, self.style = fac, grid_bars, style
        self.atr10 = smc._atr(h, l, c, 10)
        self.atr14 = smc._atr(h, l, c, 14)
        self.base = _ema(c, base_len)
        with np.errstate(invalid="ignore"):
            if style == "lux":
                pc = _prev(c)
                tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
                tr[0] = h[0] - l[0]                     # ta.tr(true)
                self.centre, self.rng, self.fac = (o + h + l + c) / 4, _roll(tr, 30, "mean"), 0.165
                fast, slow = _ema(c, 20), _ema(c, 26)
                self.trend_up, self.trend_dn = fast > slow, fast < slow
            else:
                self.centre, self.rng = (h + l) / 2, self.atr10
                self.trend_up, self.trend_dn = c > self.base, c < self.base
        with np.errstate(divide="ignore", invalid="ignore"):
            self.cls_hi = _cls_hi((c - self.base) / self.atr14, ml_len)
        r14 = rsi(c, 14)
        p14 = _prev(r14)
        self.x_dn = (r14 < 70) & (p14 >= 70)        # ta.crossunder(rsi, 70)
        self.x_up = (r14 > 30) & (p14 <= 30)        # ta.crossover(rsi, 30)
        self.trend_str = np.minimum(100.0, 2.0 * np.nan_to_num(adx(h, l, c, 14)))

        # overlays
        self.trail, self.trail_dir = _trail(c, (trail_p + 1) * self.atr14)
        ln = 20 + 30 * (rz_p - 1)
        mean, dev = _roll(c, ln, "mean"), pd.Series(c).rolling(ln).std(ddof=0).to_numpy()
        self.rz = {f"r{i + 1}": mean + (2.0 + 0.5 * i) * dev for i in range(3)}
        self.rz.update({f"s{i + 1}": mean - (2.0 + 0.5 * i) * dev for i in range(3)})
        ach = np.nan_to_num(np.abs(c - _prev(c)))
        self.tracer, self.tracer_dir = _tracer(c, _ema(ach, 20 * tracer_p) * 3.0)
        tl = 10 * catcher_p
        noise = _roll(ach, tl, "sum")
        back = np.concatenate([np.full(tl, np.nan), c[:-tl]]) if self.n > tl else np.full(self.n, np.nan)
        with np.errstate(divide="ignore", invalid="ignore"):
            er = np.where(noise > 0, np.abs(c - back) / noise, 0.0)
        er = np.nan_to_num(er)
        sc = (er * (2.0 / 3 - 2.0 / 31) + 2.0 / 31) ** 2
        self.catcher, self.catcher_dir = _catcher(c, sc, self.atr14)
        nf = 13 * neo_p
        self.lead = (_roll(h, nf, "max") + _roll(l, nf, "min")) / 2
        self.lag = (_roll(h, 2 * nf, "max") + _roll(l, 2 * nf, "min")) / 2
        self.neo_dir = _neo(self.lead, self.lag)
        self._conf_rows: dict = {}
        self._cont_rows: dict = {}
        self._best_idx: dict = {}

    # -- engines, cached
    def conf_dir(self, sens: float) -> np.ndarray:
        if sens not in self._conf_rows:
            self._conf_rows[sens] = _conf(self.centre, self.c, self.rng,
                                          np.array([float(sens)]), self.fac)[0]
        return self._conf_rows[sens]

    def cont(self, sens: float):
        if sens not in self._cont_rows:
            s, r = _cont(self.c, np.array([float(sens)]), OS, OB, OS_STRONG, OB_STRONG)
            self._cont_rows[sens] = (s[0], r[0])
        return self._cont_rows[sens]

    def _grid(self, mode: str, auto: str):
        """(sensitivities, best index per bar, engine rows) for one mode and range."""
        key = (mode, auto)
        if key not in self._best_idx:
            lo, hi = AUTO_RANGE[auto]
            sens = list(range(lo, hi + 1))
            if mode == "conf":
                rows = np.stack([self.conf_dir(s) for s in sens])
                best = _best(rows, self.c, self.gb)
                self._best_idx[key] = (sens, best, rows, None)
            else:
                sig = np.stack([self.cont(s)[0] for s in sens])
                rs = np.stack([self.cont(s)[1] for s in sens])
                best = _best(_held(sig), self.c, self.gb)
                self._best_idx[key] = (sens, best, sig, rs)
        return self._best_idx[key]

    def optimal(self, mode: str, auto: str = "off") -> np.ndarray:
        """The Optimal Sensitivity plot: NaN until `grid_bars` bars exist."""
        sens, best, _, _ = self._grid(mode, auto)
        out = np.array(sens, float)[best]
        out[:self.gb] = np.nan
        return out

    # -- signals
    def conf_side(self, sens: float = 12, auto: str = "off") -> np.ndarray:
        """The confirmation engine's side (+1 / -1) on every bar."""
        d = self.conf_dir(sens)
        if auto != "off":
            _, best, rows, _ = self._grid("conf", auto)
            d = _pick(rows, best, d, self.gb)
        return d

    def conf_sig(self, sens: float = 12, auto: str = "off") -> np.ndarray:
        return _conf_sig(self.conf_side(sens, auto), self.trend_up, self.trend_dn)

    def signals(self, mode: str = "conf", sens: float = 12, auto: str = "off",
                filt: str = "none", ml: str = "") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(signal, exit cross, classifier class) per bar.

        signal: +-1 normal, +-2 strong. exit: +1 = exit the bullish signal,
        -1 = exit the bearish one. `ml` = the classes to keep, "" = classifier off.
        """
        c = self.c
        if mode == "conf":
            raw = self.conf_sig(sens, auto)
            crsi = np.full(self.n, np.nan)
        else:
            raw, crsi = self.cont(sens)
            if auto != "off":
                _, best, sig, rs = self._grid("cont", auto)
                raw = _pick(sig, best, raw, self.gb)
                crsi = _pick(rs, best, crsi, self.gb)
        up = raw > 0
        hi = up if mode == "conf" else ~up
        cls = np.where(raw == 0, 0, np.where(hi, self.cls_hi, 5 - self.cls_hi)).astype(np.int8)
        ml_ok = np.isin(cls, [int(x) for x in ml]) if ml else np.ones(self.n, bool)
        top, btm = np.maximum(self.lead, self.lag), np.minimum(self.lead, self.lag)
        with np.errstate(invalid="ignore"):
            pb, ps = {
                "none": (np.ones(self.n, bool), np.ones(self.n, bool)),
                "trail": (c > self.trail, c < self.trail),
                "tracer": (self.tracer_dir == 1, self.tracer_dir == -1),
                "catcher": (self.catcher_dir == 1, self.catcher_dir == -1),
                "neo": (c > top, c < btm),
                "strength": (self.trend_str > 50, self.trend_str > 50),
            }[filt]
        sig, ex = _final(raw, pb, ps, ml_ok, c, mode == "conf", self.x_dn, self.x_up, crsi)
        return sig, ex, cls

    def bar_value(self, sens: float = 12, auto: str = "off") -> np.ndarray:
        """Confirmation Simple candle colour: 1 green, 0 purple, -1 red.

        style "own": set by the last signal (NaN before the first one). style
        "lux": bar by bar, green / red while the side and the trend state agree."""
        if self.style == "lux":
            d = self.conf_side(sens, auto)
            return np.where((d == 1) & self.trend_up, 1.0, np.where((d == -1) & self.trend_dn, -1.0, 0.0))
        s = self.conf_sig(sens, auto)
        v = np.where(s == 2, 1.0, np.where(s == -2, -1.0, np.where(s != 0, 0.0, np.nan)))
        return pd.Series(v).ffill().to_numpy()

    def tpsl(self, t_bull: np.ndarray, t_bear: np.ndarray, dist: float = 5.0):
        return _tpsl(self.h, self.l, self.c, self.atr14, t_bull, t_bear, dist)


# ------------------------------------------------------------- simulator
@njit(cache=True)
def _sim(o, h, l, c, atr, sig, ex, start, side, strong_only, exit_mode,
         stop_atr, tp_r, max_hold, min_risk, max_risk):
    """exit_mode 0 flip, 1 cross, 2 fixed target. Returns gross R and the cost
    multiplier k, so net R = gross - cost x k for any cost."""
    n = len(c)
    ti = np.empty(n, np.int64)
    tx = np.empty(n, np.int64)
    dd = np.empty(n, np.int8)
    gross = np.empty(n)
    kc = np.empty(n)
    rp = np.empty(n)
    why = np.empty(n, np.int8)   # 0 stop, 1 target, 2 time, 3 flip, 4 cross, 5 end
    nt = 0
    t = start
    while t < n - 1:
        s = sig[t]
        d = 1 if s > 0 else (-1 if s < 0 else 0)
        if (d == 0 or (strong_only and abs(s) != 2) or (d < 0 and side == 1)
                or np.isnan(atr[t])):
            t += 1
            continue
        ep = o[t + 1]
        stop = c[t] - d * stop_atr * atr[t]
        risk = (ep - stop) * d
        if risk <= 0 or risk / ep < min_risk or risk / ep > max_risk:
            t += 1
            continue
        tgt = ep + d * tp_r * risk
        x_px = c[n - 1]
        x_i = n - 1
        w = 5
        nxt = n
        for j in range(t + 1, n):
            if d > 0 and l[j] <= stop:
                x_px, x_i, w, nxt = min(o[j], stop), j, 0, j
                break
            if d < 0 and h[j] >= stop:
                x_px, x_i, w, nxt = max(o[j], stop), j, 0, j
                break
            if exit_mode == 2:
                if d > 0 and h[j] >= tgt:
                    x_px, x_i, w, nxt = max(o[j], tgt), j, 1, j
                    break
                if d < 0 and l[j] <= tgt:
                    x_px, x_i, w, nxt = min(o[j], tgt), j, 1, j
                    break
                if j - t >= max_hold:
                    x_px, x_i, w, nxt = c[j], j, 2, j
                    break
            elif j + 1 < n:
                if sig[j] * d < 0:
                    x_px, x_i, w, nxt = o[j + 1], j + 1, 3, j
                    break
                if exit_mode == 1 and ex[j] == d:
                    x_px, x_i, w, nxt = o[j + 1], j + 1, 4, j
                    break
        ti[nt] = t + 1
        tx[nt] = x_i
        dd[nt] = d
        gross[nt] = (x_px - ep) * d / risk
        kc[nt] = (ep + x_px) / risk
        rp[nt] = risk / ep
        why[nt] = w
        nt += 1
        t = max(nxt, t + 1)
    return ti[:nt], tx[:nt], dd[:nt], gross[:nt], kc[:nt], rp[:nt], why[:nt]


WHY = np.array(["stop", "target", "time", "flip", "cross", "data_end"])
EXIT = {"flip": 0, "cross": 1, "3R": 2}


@dataclass(frozen=True)
class Cfg:
    tf: str = "4h"
    mode: str = "conf"        # conf | cont
    side: str = "both"        # long | both
    strong: bool = False      # trade only the strong (+) signals
    exit: str = "flip"        # flip | cross | 3R
    filt: str = "none"        # none | trail | tracer | catcher | neo | strength
    auto: str = "off"         # off | short | medium | long
    ml: str = ""              # classifier classes to keep, "" = off
    sens: int = 12
    stop_atr: float = 2.0
    tp_r: float = 3.0
    max_hold: int = 42
    min_risk: float = 0.005
    max_risk: float = 0.15

    @property
    def name(self) -> str:
        extra = [x for x in (
            self.filt if self.filt != "none" else "",
            f"auto={self.auto}" if self.auto != "off" else "",
            f"ml={self.ml}" if self.ml else "",
            f"sens={self.sens}" if self.sens != 12 else "",
            f"stop={self.stop_atr:g}atr" if self.stop_atr != 2.0 else "") if x]
        return (f"{self.tf} {self.mode} {self.side} {'strong' if self.strong else 'all'} "
                f"exit={self.exit}" + (" " + " ".join(extra) if extra else ""))


def trades(book: Book, cfg: Cfg) -> tuple:
    sig, ex, _ = book.signals(cfg.mode, cfg.sens, cfg.auto, cfg.filt, cfg.ml)
    return _sim(book.o, book.h, book.l, book.c, book.atr14, sig, ex, WARMUP,
                2 if cfg.side == "both" else 1, cfg.strong, EXIT[cfg.exit],
                cfg.stop_atr, cfg.tp_r, cfg.max_hold, cfg.min_risk, cfg.max_risk)


def run(coin: str, cfg: Cfg, book: Book | None = None, cost: float = smc.COST) -> pd.DataFrame:
    book = book or Book(smc.bars(coin, cfg.tf, BASE))
    ti, tx, d, gross, kc, rp, w = trades(book, cfg)
    idx = book.index
    return pd.DataFrame({"coin": coin, "entry_time": idx[ti], "exit_time": idx[tx],
                         "dir": d, "r": gross - cost * kc, "gross": gross, "k": kc,
                         "why": WHY[w], "risk_pct": rp})


# ------------------------------------------------------------------ grid
def grid() -> list[Cfg]:
    out = [Cfg(tf, mode, side, strong, ex)
           for tf, mode, side, strong, ex in itertools.product(
               ("1h", "4h", "1d"), ("conf", "cont"), ("long", "both"),
               (False, True), ("flip", "cross", "3R"))]
    # round 2: one dial at a time, both sides, all signals
    for tf, ex in itertools.product(("4h", "1d"), ("flip", "cross", "3R")):
        for f in ("trail", "tracer", "catcher", "neo", "strength"):
            out.append(Cfg(tf, "conf", exit=ex, filt=f))
        for mode in ("conf", "cont"):
            for a in ("short", "medium", "long"):
                out.append(Cfg(tf, mode, exit=ex, auto=a))
            for m in ("12", "34"):
                out.append(Cfg(tf, mode, exit=ex, ml=m))
            for s in (8, 16, 20):
                out.append(Cfg(tf, mode, exit=ex, sens=s))
            out.append(Cfg(tf, mode, exit=ex, stop_atr=4.0))
    return out


def collect(coins: list[str], cfgs: list[Cfg]) -> dict[Cfg, pd.DataFrame]:
    """Trades of every config on every coin. One coin and timeframe at a time,
    so the indicator arrays of only one coin are in memory."""
    parts: dict[Cfg, list] = {c: [] for c in cfgs}
    by_tf: dict[str, list[Cfg]] = {}
    for c in cfgs:
        by_tf.setdefault(c.tf, []).append(c)
    for i, coin in enumerate(coins):
        for tf, group in by_tf.items():
            df = smc.bars(coin, tf, BASE)
            if len(df) <= WARMUP + 50:
                continue
            book = Book(df)
            for cfg in group:
                tr = run(coin, cfg, book)
                if len(tr):
                    parts[cfg].append(tr)
        smc.bars.cache_clear()
        smc.harness._FRAMES.pop((f"{coin}/USDT", BASE), None)
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(coins)} coins", flush=True)
    cols = ["coin", "entry_time", "exit_time", "dir", "r", "gross", "k", "why", "risk_pct"]
    return {c: (pd.concat(p, ignore_index=True) if p else pd.DataFrame(columns=cols))
            for c, p in parts.items()}


def evaluate(cfg: Cfg, t_old: pd.DataFrame, t_new: pd.DataFrame, fit: set, hold: set) -> dict:
    row = {"cfg": asdict(cfg), "name": cfg.name}
    if len(t_old):
        row["fit"] = smc.metrics(t_old[t_old.coin.isin(fit)])
        row["hold"] = smc.metrics(t_old[t_old.coin.isin(hold)])
        row["old"] = smc.metrics(t_old)
    if len(t_new):
        row["new"] = smc.metrics(t_new)
        row["new_cost10"] = round(float((t_new.gross - 0.0010 * t_new.k).mean()), 3)
        row["new_acct"] = smc_account.account(t_new, risk=0.005)
        rs = t_new.r.sort_values(ascending=False)
        row["new_trim1"] = round(float(rs.iloc[len(rs) // 100:].mean()), 3)
        row["new_by_year"] = {int(k): v for k, v in t_new.groupby(
            t_new.exit_time.dt.year)["r"].mean().round(3).items()}
        row["new_why"] = {k: round(100 * v, 1) for k, v in
                          t_new.why.value_counts(normalize=True).items()}
    return row


def show(row: dict) -> None:
    f, hd, n = row.get("fit", {}), row.get("hold", {}), row.get("new", {})
    a = row.get("new_acct", {})
    print(f"{row['name']:52s} fit {f.get('avg_r', 0):+.3f} hold {hd.get('avg_r', 0):+.3f} | "
          f"new n={n.get('n', 0):6d} avgR={n.get('avg_r', 0):+.3f} "
          f"pf={n.get('pf', 0):.2f} win={n.get('win', 0)} "
          f"c10={row.get('new_cost10', 0):+.3f} trim1={row.get('new_trim1', 0):+.3f} "
          f"cagr={a.get('cagr')} dd={a.get('dd_worst')}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    old = [c for c in smc.UNIVERSE if smc.have(c, BASE)]
    new = smc_oos.new_coins()
    if a.quick:
        old, new = old[:5], new[:5]
    fit, hold = (set(x) for x in smc.split(old))
    cfgs = grid()
    print(f"old coins {len(old)}, new coins {len(new)}, configs {len(cfgs)}", flush=True)
    OUT.parent.mkdir(exist_ok=True)
    # one timeframe at a time keeps the trade lists in memory small
    with OUT.open("w") as fh:
        for tf in ("1d", "4h", "1h"):
            group = [c for c in cfgs if c.tf == tf]
            print(f"--- {tf}: {len(group)} configs", flush=True)
            t_old = collect(old, group)
            t_new = collect(new, group)
            for cfg in group:
                row = evaluate(cfg, t_old[cfg], t_new[cfg], fit, hold)
                fh.write(json.dumps(row, default=str) + "\n")
                show(row)


if __name__ == "__main__":
    main()
