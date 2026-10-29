"""Smart Money Concepts (SMC) engine: structure, order blocks, fair value gaps,
liquidity sweeps, and a multi-timeframe simulator that trades them.

Why a new engine: harness.simulate() enters at the next bar's open. SMC entries
are mostly resting LIMIT orders at a zone (order block, FVG, OTE retracement)
that may fill several bars later or never, and the trade has to be managed bar
by bar from the fill. That needs a per-coin state machine, so it lives here in
numba rather than in the harness.

Everything is causal, and these are the places where it could leak:
  * a swing pivot at bar i is only KNOWN at bar i + k (k bars to its right)
  * a structure break is a CLOSE beyond the last confirmed, unbroken pivot
  * a higher-timeframe bar is only usable once it has CLOSED; HTF arrays are
    mapped onto LTF bars by close time, never by open time
  * the risk filter for a market entry uses the signal bar's close, not the
    next bar's open (which is the fill and is not known at the decision)

Fill rules, deliberately pessimistic:
  * market entries fill at the next LTF bar's open
  * a limit fills at the limit, or at the open if the bar gaps through it
  * on the bar a limit fills, only the stop is tested -- a target touched in
    the same bar is not credited, because the order of the high and the low
    inside that bar is unknown
  * on every later bar the stop is tested before the target
  * cost is charged per side on entry and exit, in price terms
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402

TF_DELTA = {"15m": pd.Timedelta("15min"), "1h": pd.Timedelta("1h"),
            "4h": pd.Timedelta("4h"), "1d": pd.Timedelta("1D")}
RULE = {"15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}

# Futures taker fee ~0.05% plus a little slippage, per side. The 15m/1h cost
# finding in HANDOVER.md was made at 0.15% per side (spot); this engine is for
# perpetual futures, so the base case is cheaper and is stress-tested at 0.1%.
COST = 0.0006

UNIVERSE = """BTC ETH BNB XRP ADA DOGE SOL DOT LTC LINK AVAX TRX ATOM ETC XLM BCH
FIL NEAR ALGO VET ICP HBAR AAVE UNI SAND MANA AXS THETA EGLD STX SEI TAO S INJ TIA
SUI APT ARB OP FET GRT IMX LDO PENDLE JUP PYTH ENA ONDO AR RUNE CFX GALA CHZ CRV
SUSHI COMP SNX ZIL ONE IOTA QNT KSM NEO WAVES ENJ ANKR CELO SKL OCEAN BAND KAVA
ROSE FLOW MASK DYDX MINA WLD BLUR""".split()


def split(coins: list[str]) -> tuple[list[str], list[str]]:
    """Same md5 split as campaign.py, so FIT/HOLDOUT match earlier phases."""
    fit, hold = [], []
    for c in coins:
        h = int(hashlib.md5(c.encode()).hexdigest(), 16)
        (fit if h % 2 == 0 else hold).append(c)
    return fit, hold


# --------------------------------------------------------------------- data
@lru_cache(maxsize=None)
def bars(coin: str, tf: str, base: str = "15m") -> pd.DataFrame:
    """One coin at one timeframe, resampled up from `base`.

    Building every timeframe from the same base frame means 15m, 1h, 4h and
    1d all cover exactly the same dates, so a pair of timeframes never trades
    a stretch where only one of them has data.
    """
    df = harness.load(f"{coin}/USDT", base)
    if tf == base:
        return df
    out = df.resample(RULE[tf], label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last",
         "volume": "sum"}).dropna()
    return out


def have(coin: str, base: str = "15m") -> bool:
    return (harness.DATA_DIR / f"{coin}_USDT-{base}.feather").exists()


# ------------------------------------------------------------- primitives
@njit(cache=True)
def _atr(h, l, c, n):
    out = np.full(len(c), np.nan)
    tr = np.empty(len(c))
    tr[0] = h[0] - l[0]
    for i in range(1, len(c)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    if len(c) <= n:
        return out
    a = tr[:n].mean()
    out[n - 1] = a
    for i in range(n, len(c)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


@njit(cache=True)
def _pivots(h, l, k):
    """Fractal pivots, stamped at the bar where they become KNOWN (i + k)."""
    n = len(h)
    ph = np.full(n, np.nan)
    phi = np.full(n, -1, np.int64)
    pl = np.full(n, np.nan)
    pli = np.full(n, -1, np.int64)
    for i in range(k, n - k):
        ok = True
        for j in range(i - k, i):
            if h[j] >= h[i]:
                ok = False
                break
        if ok:
            for j in range(i + 1, i + k + 1):
                if h[j] > h[i]:
                    ok = False
                    break
        if ok:
            ph[i + k] = h[i]
            phi[i + k] = i
        ok = True
        for j in range(i - k, i):
            if l[j] <= l[i]:
                ok = False
                break
        if ok:
            for j in range(i + 1, i + k + 1):
                if l[j] < l[i]:
                    ok = False
                    break
        if ok:
            pl[i + k] = l[i]
            pli[i + k] = i
    return ph, phi, pl, pli


@njit(cache=True)
def _structure(o, h, l, c, ph, phi, pl, pli):
    """Market structure state machine.

    ev[t]   +2 bullish CHoCH, +1 bullish BOS, -1 bearish BOS, -2 bearish CHoCH
            (a CHoCH is a break against the prevailing trend; a BOS is with it)
    org[t]  at a break: the extreme the breaking leg started from (the low of
            the move that broke a high). This is the protected level and the
            natural stop.
    ob*[t]  at a break: the order block -- the last opposite-colour candle at
            or just before the origin
    fv*[t]  at a break: the fair value gap nearest the origin inside the leg
    ext[t]  at a break: the far extreme of the breaking leg (for OTE)
    swept[t] at a break: the origin candle wicked through the previous swing
            point and closed back -- a liquidity grab before the reversal
    swb/sws[t] a bar that wicks through a live swing low/high and closes back
            inside (a sweep), stamped with the wick extreme
    rlo/rhi[t] the dealing range of the current trend (for premium/discount)
    """
    n = len(c)
    trend = np.zeros(n, np.int8)
    ev = np.zeros(n, np.int8)
    org = np.full(n, np.nan)
    orgi = np.full(n, -1, np.int64)
    obh = np.full(n, np.nan)
    obl = np.full(n, np.nan)
    fvh = np.full(n, np.nan)
    fvl = np.full(n, np.nan)
    ext = np.full(n, np.nan)
    swept = np.zeros(n, np.bool_)
    swb = np.full(n, np.nan)
    sws = np.full(n, np.nan)
    rlo = np.full(n, np.nan)
    rhi = np.full(n, np.nan)
    sl_any = np.full(n, np.nan)
    sh_any = np.full(n, np.nan)

    sh = np.nan
    shi = -1
    sl = np.nan
    sli = -1
    last_sl = np.nan
    last_sh = np.nan
    cur = 0
    r_lo = np.nan
    r_hi = np.nan
    for t in range(n):
        if not np.isnan(ph[t]):
            sh = ph[t]
            shi = phi[t]
            last_sh = sh
        if not np.isnan(pl[t]):
            sl = pl[t]
            sli = pli[t]
            last_sl = sl
        sl_any[t] = last_sl
        sh_any[t] = last_sh

        if not np.isnan(sl) and l[t] < sl and c[t] >= sl:
            swb[t] = l[t]
        if not np.isnan(sh) and h[t] > sh and c[t] <= sh:
            sws[t] = h[t]

        if not np.isnan(sh) and c[t] > sh:
            ev[t] = 1 if cur == 1 else 2
            k = shi
            for j in range(shi, t + 1):
                if l[j] < l[k]:
                    k = j
            org[t] = l[k]
            orgi[t] = k
            b = k
            for j in range(k, max(k - 6, -1), -1):
                if c[j] < o[j]:
                    b = j
                    break
            obh[t] = h[b]
            obl[t] = l[b]
            for j in range(k + 2, t + 1):
                if l[j] > h[j - 2]:
                    fvh[t] = l[j]
                    fvl[t] = h[j - 2]
                    break
            mx = h[k]
            for j in range(k, t + 1):
                if h[j] > mx:
                    mx = h[j]
            ext[t] = mx
            if k > 0:
                ref = sl_any[k - 1]
                swept[t] = (not np.isnan(ref)) and l[k] < ref and c[k] > ref
            cur = 1
            sh = np.nan
            r_lo = l[k]
            r_hi = mx
        elif not np.isnan(sl) and c[t] < sl:
            ev[t] = -1 if cur == -1 else -2
            k = sli
            for j in range(sli, t + 1):
                if h[j] > h[k]:
                    k = j
            org[t] = h[k]
            orgi[t] = k
            b = k
            for j in range(k, max(k - 6, -1), -1):
                if c[j] > o[j]:
                    b = j
                    break
            obh[t] = h[b]
            obl[t] = l[b]
            for j in range(k + 2, t + 1):
                if h[j] < l[j - 2]:
                    fvh[t] = l[j - 2]
                    fvl[t] = h[j]
                    break
            mn = l[k]
            for j in range(k, t + 1):
                if l[j] < mn:
                    mn = l[j]
            ext[t] = mn
            if k > 0:
                ref = sh_any[k - 1]
                swept[t] = (not np.isnan(ref)) and h[k] > ref and c[k] < ref
            cur = -1
            sl = np.nan
            r_hi = h[k]
            r_lo = mn
        else:
            if cur == 1 and h[t] > r_hi:
                r_hi = h[t]
            elif cur == -1 and l[t] < r_lo:
                r_lo = l[t]
        trend[t] = cur
        rlo[t] = r_lo
        rhi[t] = r_hi
    return (trend, ev, org, orgi, obh, obl, fvh, fvl, ext, swept, swb, sws,
            rlo, rhi)


@njit(cache=True)
def _active_sweeps(c, swb, sws, life):
    """Carry each HTF sweep forward for `life` bars until price closes beyond it.

    Returns the active bullish sweep low and its bar, and the bearish mirror.
    A newer sweep replaces an older one.
    """
    n = len(c)
    ab = np.full(n, np.nan)
    abi = np.full(n, -1, np.int64)
    asx = np.full(n, np.nan)
    asi = np.full(n, -1, np.int64)
    cb = np.nan
    cbi = -1
    cs = np.nan
    csi = -1
    for t in range(n):
        if not np.isnan(swb[t]):
            cb = swb[t]
            cbi = t
        if not np.isnan(sws[t]):
            cs = sws[t]
            csi = t
        if cbi >= 0 and (t - cbi > life or c[t] < cb):
            cb = np.nan
            cbi = -1
        if csi >= 0 and (t - csi > life or c[t] > cs):
            cs = np.nan
            csi = -1
        ab[t] = cb
        abi[t] = cbi
        asx[t] = cs
        asi[t] = csi
    return ab, abi, asx, asi


# -------------------------------------------------------------- frames
STRUCT_COLS = ("trend", "ev", "org", "orgi", "obh", "obl", "fvh", "fvl", "ext",
               "swept", "swb", "sws", "rlo", "rhi")


@lru_cache(maxsize=None)
def structure(coin: str, tf: str, k: int, base: str = "15m") -> dict:
    df = bars(coin, tf, base)
    o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
    ph, phi, pl, pli = _pivots(h, l, k)
    out = dict(zip(STRUCT_COLS, _structure(o, h, l, c, ph, phi, pl, pli)))
    out.update(o=o, h=h, l=l, c=c, atr=_atr(h, l, c, 14), index=df.index)
    return out


@lru_cache(maxsize=None)
def htf_on_ltf(coin: str, ltf: str, htf: str, k_htf: int, sweep_life: int,
               base: str = "15m") -> dict:
    """HTF context mapped onto every LTF bar, using only CLOSED HTF bars."""
    H = structure(coin, htf, k_htf, base)
    L = bars(coin, ltf, base)
    htf_close = (H["index"] + TF_DELTA[htf]).to_numpy()
    ltf_close = (L.index + TF_DELTA[ltf]).to_numpy()
    pos = np.searchsorted(htf_close, ltf_close, side="right") - 1
    valid = pos >= 0
    p = np.where(valid, pos, 0)
    ab, abi, asx, asi = _active_sweeps(H["c"], H["swb"], H["sws"], sweep_life)
    # the LTF bar index where the sweeping HTF bar OPENED, so an LTF leg can be
    # required to start inside or after the sweep
    ltf_open = L.index.to_numpy()
    htf_open = H["index"].to_numpy()

    def ltf_start(hidx):
        s = np.searchsorted(ltf_open, htf_open[np.maximum(hidx, 0)], side="left")
        return np.where(hidx >= 0, s, -1)

    def take(a, fill):
        out = a[p].astype(float) if a.dtype != np.int64 else a[p]
        out = np.where(valid, out, fill)
        return out

    return {
        "htrend": np.where(valid, H["trend"][p], 0).astype(np.int8),
        "hrlo": take(H["rlo"], np.nan),
        "hrhi": take(H["rhi"], np.nan),
        "hswb": take(ab, np.nan),
        "hswb_i": np.where(valid, ltf_start(abi[p]), -1).astype(np.int64),
        "hsws": take(asx, np.nan),
        "hsws_i": np.where(valid, ltf_start(asi[p]), -1).astype(np.int64),
    }


# -------------------------------------------------------------- config
@dataclass(frozen=True)
class Cfg:
    ltf: str = "15m"
    htf: str = "4h"
    k_ltf: int = 3            # pivot width on the entry timeframe
    k_htf: int = 3            # pivot width on the bias timeframe
    mode: str = "cont"        # cont | rev | both
    side: int = 0             # +1 longs only, -1 shorts only, 0 both
    choch_only: bool = True   # LTF trigger: CHoCH only, or any break
    need_swept: bool = False  # LTF origin must be a liquidity grab
    discount: bool = False    # cont: the LTF pullback reached HTF discount
    entry: str = "mkt"        # mkt | ob | fvg | ote
    ote: float = 0.705        # retracement level for the OTE entry
    expiry: int = 12          # bars a limit order rests
    sl_buf: float = 0.1       # stop buffer beyond the structure, in LTF ATR
    min_risk: float = 0.004   # skip if the stop is closer than this fraction
    max_risk: float = 0.05    # skip if further
    tp_r: float = 3.0
    be_r: float = 0.0         # move stop to entry once this R is reached (0 off)
    part_r: float = 0.0       # take part_frac off at part_r (0 off)
    part_frac: float = 0.5
    max_hold: int = 192       # LTF bars
    exit_choch: bool = False  # close at an opposite LTF CHoCH before target
    sweep_life: int = 6       # HTF bars a sweep stays tradable
    # filters added after round 3's feature study (smc_features.py)
    hour_from: int = 0        # signal bar must OPEN in [hour_from, hour_to) UTC
    hour_to: int = 24
    min_volx: float = 0.0     # signal bar volume / its 96-bar mean
    with_d50: bool = False    # trade the side of the coin's daily 50 SMA
    max_leg_atr: float = 99.0 # skip over-extended breaking legs
    # trailing stop in R behind the best price, armed once trail_start R is
    # reached (0 = off). Raised from a bar's extreme only AFTER that bar's
    # stop test, so one bar can never both extend and protect the trade.
    trail_r: float = 0.0
    trail_start: float = 1.0
    cost: float = COST

    @property
    def tag(self) -> str:
        return "|".join(f"{k}={v}" for k, v in asdict(self).items())


ENTRY = {"mkt": 0, "ob": 1, "fvg": 2, "ote": 3}
MODE = {"cont": 0, "rev": 1, "both": 2}


@njit(cache=True)
def _sim(o, h, l, c, atr, ev, org, orgi, obh, obl, fvh, fvl, ext, swept,
         htrend, hrlo, hrhi, hswb, hswb_i, hsws, hsws_i,
         side, mode, choch_only, need_swept, discount, entry, ote, expiry,
         sl_buf, min_risk, max_risk, tp_r, be_r, part_r, part_frac, max_hold,
         exit_choch, cost, hour, volx, d50, hour_from, hour_to, min_volx,
         with_d50, max_leg_atr, trail_r, trail_start):
    n = len(c)
    cap = n // 2 + 16
    T_sig = np.empty(cap, np.int64)
    T_in = np.empty(cap, np.int64)
    T_out = np.empty(cap, np.int64)
    T_dir = np.empty(cap, np.int8)
    T_kind = np.empty(cap, np.int8)     # 0 continuation, 1 reversal
    T_px = np.empty(cap, np.float64)
    T_stop = np.empty(cap, np.float64)
    T_r = np.empty(cap, np.float64)
    T_why = np.empty(cap, np.int8)      # 0 stop 1 target 2 BE 3 time 4 choch 5 end
    T_mfe = np.empty(cap, np.float64)
    nt = 0

    state = 0       # 0 idle, 1 pending limit, 2 in trade
    d = 0
    kind = 0
    sig = 0
    lim = 0.0
    stop = 0.0
    risk = 0.0
    cancel_px = 0.0
    exp_t = 0
    px = 0.0
    t_in = 0
    live = 0.0
    rem = 1.0
    booked = 0.0
    part_done = False
    mfe = 0.0

    for t in range(n):
        # ---------------------------------------------------- manage a trade
        if state == 2 and t > t_in:
            why = -1
            out_px = 0.0
            if (d > 0 and l[t] <= live) or (d < 0 and h[t] >= live):
                out_px = live
                why = 2 if live == px else 0
                if d > 0 and o[t] < live:
                    out_px = o[t]      # gapped through the stop
                if d < 0 and o[t] > live:
                    out_px = o[t]
            else:
                fav = (h[t] - px) / risk if d > 0 else (px - l[t]) / risk
                if fav > mfe:
                    mfe = fav
                if part_r > 0 and not part_done and fav >= part_r:
                    tp = px + d * part_r * risk
                    booked += part_frac * (d * (tp - px) - cost * (px + tp)) / risk
                    rem -= part_frac
                    part_done = True
                    live = px
                if fav >= tp_r:
                    out_px = px + d * tp_r * risk
                    why = 1
                elif exit_choch and ((d > 0 and ev[t] == -2) or (d < 0 and ev[t] == 2)):
                    out_px = c[t]
                    why = 4
                elif t - t_in >= max_hold:
                    out_px = c[t]
                    why = 3
                elif be_r > 0 and fav >= be_r and ((d > 0 and live < px) or (d < 0 and live > px)):
                    live = px
                if why < 0 and trail_r > 0 and mfe >= trail_start:
                    cand = px + d * (mfe - trail_r) * risk
                    if (d > 0 and cand > live) or (d < 0 and cand < live):
                        live = cand
            if why >= 0:
                r = booked + rem * (d * (out_px - px) - cost * (px + out_px)) / risk
                T_out[nt] = t
                T_r[nt] = r
                T_why[nt] = why
                T_mfe[nt] = mfe
                nt += 1
                state = 0
            continue

        # ---------------------------------------------------- pending limit
        if state == 1:
            if t > exp_t or (d > 0 and h[t] >= cancel_px) or (d < 0 and l[t] <= cancel_px) \
                    or (d > 0 and ev[t] < 0) or (d < 0 and ev[t] > 0):
                state = 0
            elif (d > 0 and l[t] <= lim) or (d < 0 and h[t] >= lim):
                # a gap through the limit fills at the open -- unless it also
                # gapped through the stop, where the open would hand back a
                # fictional profit; book it at the limit for a full loss
                px = lim
                if d > 0 and stop < o[t] < lim:
                    px = o[t]
                if d < 0 and lim < o[t] < stop:
                    px = o[t]
                risk = abs(px - stop)
                T_sig[nt] = sig
                T_in[nt] = t
                T_dir[nt] = d
                T_kind[nt] = kind
                T_px[nt] = px
                T_stop[nt] = stop
                t_in = t
                live = stop
                rem = 1.0
                booked = 0.0
                part_done = False
                mfe = 0.0
                if (d > 0 and l[t] <= stop) or (d < 0 and h[t] >= stop):
                    T_out[nt] = t
                    T_r[nt] = (d * (stop - px) - cost * (px + stop)) / risk
                    T_why[nt] = 0
                    T_mfe[nt] = 0.0
                    nt += 1
                    state = 0
                else:
                    state = 2
                continue

        # ---------------------------------------------------- new signal
        e = ev[t]
        if e == 0 or t + 1 >= n or np.isnan(atr[t]):
            continue
        dd = 1 if e > 0 else -1
        if side != 0 and dd != side:
            continue
        if choch_only and abs(e) != 2:
            continue
        if need_swept and not swept[t]:
            continue
        if hour[t] < hour_from or hour[t] >= hour_to:
            continue
        if min_volx > 0 and not volx[t] >= min_volx:
            continue
        if with_d50 and d50[t] != dd:
            continue
        if max_leg_atr < 99 and not abs(ext[t] - org[t]) <= max_leg_atr * atr[t]:
            continue

        cont_ok = False
        rev_ok = False
        if mode != 1 and htrend[t] == dd:
            cont_ok = True
            if discount:
                eq = 0.5 * (hrlo[t] + hrhi[t])
                if np.isnan(eq):
                    cont_ok = False
                elif dd > 0 and not org[t] < eq:
                    cont_ok = False
                elif dd < 0 and not org[t] > eq:
                    cont_ok = False
        sw = np.nan
        if mode != 0:
            if dd > 0 and not np.isnan(hswb[t]) and orgi[t] >= hswb_i[t]:
                rev_ok = True
                sw = hswb[t]
            if dd < 0 and not np.isnan(hsws[t]) and orgi[t] >= hsws_i[t]:
                rev_ok = True
                sw = hsws[t]
        if not (cont_ok or rev_ok):
            continue
        k_ = 0 if cont_ok else 1

        base = org[t]
        if entry == 1:
            base = min(base, obl[t]) if dd > 0 else max(base, obh[t])
        if k_ == 1:
            base = min(base, sw) if dd > 0 else max(base, sw)
        st = base - dd * sl_buf * atr[t]

        if entry == 0:
            ref = c[t]
        elif entry == 1:
            ref = obh[t] if dd > 0 else obl[t]
        elif entry == 2:
            ref = fvh[t] if dd > 0 else fvl[t]   # the edge price meets first
        else:
            ref = ext[t] - ote * (ext[t] - org[t])
        if np.isnan(ref):
            continue
        if entry != 0 and ((dd > 0 and ref >= c[t]) or (dd < 0 and ref <= c[t])):
            ref = c[t]          # already in the zone: take the next open
            ent = 0
        else:
            ent = entry
        rk = dd * (ref - st)
        if rk <= 0:
            continue
        rp = rk / ref
        if rp < min_risk or rp > max_risk:
            continue

        d = dd
        kind = k_
        sig = t
        stop = st
        if ent == 0:
            px = o[t + 1]
            risk = d * (px - stop)
            if risk <= 0:
                continue
            T_sig[nt] = t
            T_in[nt] = t + 1
            T_dir[nt] = d
            T_kind[nt] = kind
            T_px[nt] = px
            T_stop[nt] = stop
            t_in = t      # the bar t+1 is managed in full on the next loop
            live = stop
            rem = 1.0
            booked = 0.0
            part_done = False
            mfe = 0.0
            state = 2
        else:
            lim = ref
            cancel_px = lim + d * tp_r * rk
            exp_t = t + expiry
            state = 1

    if state == 2:
        r = booked + rem * (d * (c[n - 1] - px) - cost * (px + c[n - 1])) / risk
        T_out[nt] = n - 1
        T_r[nt] = r
        T_why[nt] = 5
        T_mfe[nt] = mfe
        nt += 1
    return (T_sig[:nt], T_in[:nt], T_out[:nt], T_dir[:nt], T_kind[:nt],
            T_px[:nt], T_stop[:nt], T_r[:nt], T_why[:nt], T_mfe[:nt])


WHY = np.array(["stop", "target", "breakeven", "time", "choch", "data_end"])


@lru_cache(maxsize=None)
def extras(coin: str, ltf: str, base: str = "15m") -> dict:
    """Signal-bar filters: hour, relative volume, daily 50 SMA side.

    The daily flag is stamped at the daily bar's CLOSE, so an LTF bar only
    sees yesterday's completed daily candle.
    """
    L = bars(coin, ltf, base)
    v = L["volume"]
    volx = (v / v.rolling(96, min_periods=20).mean()).to_numpy()
    D = bars(coin, "1d", base)
    ma = D["close"].rolling(50).mean()
    side = np.sign(D["close"] - ma).where(ma.notna(), 0.0)
    side.index = side.index + TF_DELTA["1d"]
    d50 = side.reindex(L.index + TF_DELTA[ltf], method="ffill").fillna(0.0)
    return {"hour": L.index.hour.to_numpy().astype(np.int64),
            "volx": np.nan_to_num(volx, nan=0.0),
            "d50": d50.to_numpy().astype(np.int64)}


def run(coin: str, cfg: Cfg, base: str = "15m") -> pd.DataFrame:
    """Every trade one coin takes under one config."""
    L = structure(coin, cfg.ltf, cfg.k_ltf, base)
    H = htf_on_ltf(coin, cfg.ltf, cfg.htf, cfg.k_htf, cfg.sweep_life, base)
    X = extras(coin, cfg.ltf, base)
    res = _sim(L["o"], L["h"], L["l"], L["c"], L["atr"], L["ev"], L["org"],
               L["orgi"], L["obh"], L["obl"], L["fvh"], L["fvl"], L["ext"],
               L["swept"],
               H["htrend"], H["hrlo"], H["hrhi"], H["hswb"], H["hswb_i"],
               H["hsws"], H["hsws_i"],
               cfg.side, MODE[cfg.mode], cfg.choch_only, cfg.need_swept,
               cfg.discount, ENTRY[cfg.entry], cfg.ote, cfg.expiry, cfg.sl_buf,
               cfg.min_risk, cfg.max_risk, cfg.tp_r, cfg.be_r, cfg.part_r,
               cfg.part_frac, cfg.max_hold, cfg.exit_choch, cfg.cost,
               X["hour"], X["volx"], X["d50"], cfg.hour_from, cfg.hour_to,
               cfg.min_volx, cfg.with_d50, cfg.max_leg_atr, cfg.trail_r,
               cfg.trail_start)
    sig, tin, tout, d, kind, px, stop, r, why, mfe = res
    idx = L["index"]
    return pd.DataFrame({
        "coin": coin, "sig": idx[sig], "entry_time": idx[tin],
        "exit_time": idx[tout], "dir": d, "kind": kind, "entry": px,
        "stop": stop, "r": r, "why": WHY[why], "mfe": mfe,
        "risk_pct": np.abs(px - stop) / px,
    })


# --------------------------------------------------------------- metrics
def metrics(tr: pd.DataFrame) -> dict:
    """Pooled metrics, path-dependent ones measured in EXIT-TIME order."""
    if len(tr) == 0:
        return {"n": 0}
    t = tr.sort_values("exit_time")
    rs = t["r"].to_numpy()
    eq = np.cumsum(rs)
    dd = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq
    span = (t["exit_time"].max() - t["entry_time"].min()).days / 365.25
    span = max(span, 0.25)
    gw, gl = rs[rs > 0].sum(), -rs[rs < 0].sum()
    by_coin = t.groupby("coin")["r"].sum()
    by_year = t.groupby(t["exit_time"].dt.year)["r"].sum()
    max_dd = float(dd.max()) if len(dd) else 0.0
    ann = rs.sum() / span
    return {
        "n": len(t),
        "win": round(100 * float((rs > 0).mean()), 1),
        "hit_tp": round(100 * float((t["why"] == "target").mean()), 1),
        "avg_r": round(float(rs.mean()), 3),
        "pf": round(gw / gl, 2) if gl > 0 else 99.0,
        "tot_r": round(float(rs.sum()), 1),
        "per_yr": round(len(t) / span, 1),
        "ann_r": round(ann, 1),
        "dd_r": round(max_dd, 1),
        "ratio": round(ann / max_dd, 2) if max_dd > 0 else 99.0,
        "coins_pos": f"{int((by_coin > 0).sum())}/{len(by_coin)}",
        "yrs_pos": f"{int((by_year > 0).sum())}/{len(by_year)}",
        "avg_risk": round(100 * float(t["risk_pct"].mean()), 2),
    }


def basket(coins: list[str], cfg: Cfg, base: str = "15m") -> pd.DataFrame:
    frames = [run(c, cfg, base) for c in coins]
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["coin", "sig", "entry_time", "exit_time", "dir", "kind",
                 "entry", "stop", "r", "why", "mfe", "risk_pct"])
