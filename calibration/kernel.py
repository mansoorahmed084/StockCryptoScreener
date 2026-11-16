"""Compiled (numba) copy of the Technical Sentiment Composite, built for fitting.

``backend/indicators/sentiment.py`` is the readable original. This module repeats the same
arithmetic bar by bar in float64 so that a candidate parameter set costs about a millisecond and
many candidates run in parallel across the CPU cores. ``tests/test_calibration.py`` checks it
against the pandas original, so the two cannot drift apart.

Inputs must be clean OHLCV arrays (no NaN). Output columns follow ``COMPONENTS``.
"""
from __future__ import annotations

import numpy as np
from numba import njit, prange

COMPONENTS = ("rsi", "stoch", "stoch_rsi", "cci", "bbp", "ma", "bb", "supertrend", "vwap",
              "linreg", "structure")
VWAP_COL = COMPONENTS.index("vwap")

# name, default, low, high, is_integer — the search space the optimizer works in.
PARAMS = (
    ("rsi_len", 14, 2, 60, True),
    ("stoch_len", 14, 2, 60, True),
    ("stoch_smooth", 3, 1, 10, True),
    ("stoch_rsi_len", 14, 2, 60, True),
    ("cci_len", 20, 2, 80, True),
    ("bbp_len", 13, 2, 60, True),
    ("ma_len", 20, 2, 200, True),
    ("bb_len", 20, 2, 100, True),
    ("bb_mult", 2.0, 0.5, 4.0, False),
    ("st_len", 10, 2, 60, True),
    ("st_mult", 3.0, 0.5, 8.0, False),
    ("vwap_mult", 2.0, 0.5, 4.0, False),
    ("linreg_len", 25, 3, 200, True),
    ("structure_len", 5, 1, 30, True),
    ("norm_smooth", 3, 1, 10, True),
)
PARAM_NAMES = tuple(p[0] for p in PARAMS)
DEFAULTS = np.array([p[1] for p in PARAMS], dtype=np.float64)
LOWER = np.array([p[2] for p in PARAMS], dtype=np.float64)
UPPER = np.array([p[3] for p in PARAMS], dtype=np.float64)
IS_INT = np.array([p[4] for p in PARAMS], dtype=np.bool_)


def snap(theta: np.ndarray) -> np.ndarray:
    """Clip to the search box and round the integer parameters, as the kernel will read them."""
    out = np.clip(np.asarray(theta, dtype=np.float64), LOWER, UPPER).copy()
    out[IS_INT] = np.rint(out[IS_INT])
    return out


def as_dict(theta: np.ndarray) -> dict:
    t = snap(theta)
    return {n: (int(v) if i else float(v)) for n, v, i in zip(PARAM_NAMES, t, IS_INT)}


# ---- rolling helpers (pandas semantics: NaN unless `minp` valid values sit in the window) ----
@njit(cache=True)
def _roll_mean(x, w, minp):
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(n):
        s = 0.0
        k = 0
        for j in range(max(0, i - w + 1), i + 1):
            if not np.isnan(x[j]):
                s += x[j]
                k += 1
        if k >= minp and k > 0:
            out[i] = s / k
    return out


@njit(cache=True)
def _roll_std0(x, w, minp):
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(n):
        s = 0.0
        k = 0
        lo = max(0, i - w + 1)
        for j in range(lo, i + 1):
            if not np.isnan(x[j]):
                s += x[j]
                k += 1
        if k >= minp and k > 0:
            m = s / k
            ss = 0.0
            for j in range(lo, i + 1):
                if not np.isnan(x[j]):
                    ss += (x[j] - m) ** 2
            out[i] = np.sqrt(ss / k)
    return out


@njit(cache=True)
def _roll_ext(x, w, want_max):
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(w - 1, n):
        best = x[i]
        bad = np.isnan(best)
        for j in range(i - w + 1, i):
            v = x[j]
            if np.isnan(v):
                bad = True
                break
            if (want_max and v > best) or ((not want_max) and v < best):
                best = v
        if not bad:
            out[i] = best
    return out


@njit(cache=True)
def _ewm(x, alpha):
    """pandas ``ewm(alpha=…, adjust=False).mean()``: starts at the first valid value."""
    n = len(x)
    out = np.full(n, np.nan)
    started = False
    prev = 0.0
    for i in range(n):
        if np.isnan(x[i]):
            if started:
                out[i] = prev
            continue
        if not started:
            prev = x[i]
            started = True
        else:
            prev = alpha * x[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


@njit(cache=True)
def _zone(x, b0, b1, b2, b3, b4):
    """Piecewise-linear map onto 0-100 with flat ends (np.interp with levels 0/25/50/75/100)."""
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(n):
        v = x[i]
        if np.isnan(v):
            continue
        if v <= b0:
            out[i] = 0.0
        elif v <= b1:
            out[i] = 25.0 * (v - b0) / (b1 - b0)
        elif v <= b2:
            out[i] = 25.0 + 25.0 * (v - b1) / (b2 - b1)
        elif v <= b3:
            out[i] = 50.0 + 25.0 * (v - b2) / (b3 - b2)
        elif v <= b4:
            out[i] = 75.0 + 25.0 * (v - b3) / (b4 - b3)
        else:
            out[i] = 100.0
    return out


@njit(cache=True)
def _rsi(c, length):
    n = len(c)
    alpha = 1.0 / length
    up = np.full(n, np.nan)
    dn = np.full(n, np.nan)
    for i in range(1, n):
        d = c[i] - c[i - 1]
        up[i] = d if d > 0.0 else 0.0
        dn[i] = -d if d < 0.0 else 0.0
    ru = _ewm(up, alpha)
    rd = _ewm(dn, alpha)
    out = np.full(n, np.nan)
    for i in range(n):
        if np.isnan(ru[i]):
            continue
        if rd[i] != 0.0:
            out[i] = 100.0 - 100.0 / (1.0 + ru[i] / rd[i])
        else:
            out[i] = 100.0 if ru[i] > 0.0 else 50.0
    return out


@njit(cache=True)
def _stoch(src, hi, lo, length):
    n = len(src)
    top = _roll_ext(hi, length, True)
    bot = _roll_ext(lo, length, False)
    out = np.full(n, np.nan)
    for i in range(n):
        if np.isnan(top[i]) or np.isnan(bot[i]):
            continue
        span = top[i] - bot[i]
        out[i] = 50.0 if span == 0.0 else 100.0 * (src[i] - bot[i]) / span
    return out


@njit(cache=True)
def _cci(x, length):
    n = len(x)
    mean = _roll_mean(x, length, length)
    out = np.full(n, np.nan)
    for i in range(length - 1, n):
        if np.isnan(mean[i]):
            continue
        dev = 0.0
        for j in range(i - length + 1, i + 1):
            dev += abs(x[j] - mean[i])
        dev /= length
        if dev != 0.0:
            out[i] = (x[i] - mean[i]) / (0.015 * dev)
    return out


@njit(cache=True)
def _anchored(close, buy, sell, smooth):
    n = len(close)
    raw = np.full(n, np.nan)
    state = 0
    hi = np.nan
    lo = np.nan
    for i in range(n):
        p = close[i]
        prev = state
        if buy[i]:
            state = 1
        elif sell[i]:
            state = -1
        if np.isnan(hi):
            hi = p
            lo = p
        elif state > prev:
            hi = p                      # a buy flip restarts the high; the low carries over
        elif state < prev:
            lo = p                      # a sell flip restarts the low; the high carries over
        else:
            hi = max(hi, p)
            lo = min(lo, p)
        if hi > lo:
            raw[i] = (p - lo) / (hi - lo)
        elif state != 0:
            raw[i] = 1.0 if state > 0 else 0.0
    sm = _roll_mean(raw, smooth, 1)
    for i in range(n):
        sm[i] = sm[i] * 100.0
    return sm


@njit(cache=True)
def _supertrend(h, l, c, length, mult):
    n = len(c)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], max(abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    atr = _ewm(tr, 1.0 / length)
    line = np.full(n, np.nan)
    upper = np.nan
    lower = np.nan
    bull = True
    for i in range(n):
        mid = (h[i] + l[i]) / 2.0
        up = mid + atr[i] * mult
        lo = mid - atr[i] * mult
        if np.isnan(up):
            continue
        if np.isnan(upper):
            upper = up
            lower = lo
        else:
            upper = up if (up < upper or c[i - 1] > upper) else upper
            lower = lo if (lo > lower or c[i - 1] < lower) else lower
            if bull and c[i] < lower:
                bull = False
            elif (not bull) and c[i] > upper:
                bull = True
        line[i] = lower if bull else upper
    return line


@njit(cache=True)
def _flags_above_below(close, up_line, dn_line):
    n = len(close)
    buy = np.zeros(n, dtype=np.bool_)
    sell = np.zeros(n, dtype=np.bool_)
    for i in range(n):
        buy[i] = close[i] > up_line[i]      # NaN compares False, as in pandas
        sell[i] = close[i] < dn_line[i]
    return buy, sell


@njit(cache=True)
def _structure(h, l, c, length):
    n = len(c)
    is_top = np.zeros(n, dtype=np.bool_)
    is_bot = np.zeros(n, dtype=np.bool_)
    for i in range(length, n - length):
        # Pine's ta.pivothigh/ta.pivotlow: at least as extreme as every bar to the left,
        # strictly more extreme than every bar to the right
        lmax = h[i - length]
        rmax = h[i + 1]
        lmin = l[i - length]
        rmin = l[i + 1]
        for j in range(i - length, i):
            lmax = max(lmax, h[j])
            lmin = min(lmin, l[j])
        for j in range(i + 1, i + length + 1):
            rmax = max(rmax, h[j])
            rmin = min(rmin, l[j])
        is_top[i] = h[i] >= lmax and h[i] > rmax
        is_bot[i] = l[i] <= lmin and l[i] < rmin
    buy = np.zeros(n, dtype=np.bool_)
    sell = np.zeros(n, dtype=np.bool_)
    top = np.nan
    bot = np.nan
    for i in range(n):
        j = i - length
        if j >= 0:
            if is_top[j]:
                top = h[j]
            if is_bot[j]:
                bot = l[j]
        if c[i] > top:
            buy[i] = True
            top = np.nan
        if c[i] < bot:
            sell[i] = True
            bot = np.nan
    return buy, sell


@njit(cache=True)
def _time_corr(c, length):
    n = len(c)
    out = np.full(n, np.nan)
    if length < 2:
        return out
    for i in range(length - 1, n):
        sx = 0.0
        sy = 0.0
        for j in range(i - length + 1, i + 1):
            sx += j
            sy += c[j]
        mx = sx / length
        my = sy / length
        sxy = 0.0
        sxx = 0.0
        syy = 0.0
        for j in range(i - length + 1, i + 1):
            dx = j - mx
            dy = c[j] - my
            sxy += dx * dy
            sxx += dx * dx
            syy += dy * dy
        if sxx > 0.0 and syy > 0.0:
            out[i] = sxy / np.sqrt(sxx * syy)
    return out


@njit(cache=True)
def _vwap_bands(h, l, c, v, day, mult):
    n = len(c)
    up = np.full(n, np.nan)
    dn = np.full(n, np.nan)
    cv = 0.0
    cpv = 0.0
    cp2v = 0.0
    for i in range(n):
        first = i == 0 or day[i] != day[i - 1]
        if first:
            cv = 0.0
            cpv = 0.0
            cp2v = 0.0
        tp = c[i]       # LuxAlgo computes the VWAP of the close, not of the typical price
        cv += v[i]
        cpv += tp * v[i]
        cp2v += tp * tp * v[i]
        if cv == 0.0:
            continue
        if first:
            # one sample: the VWAP is the price itself with no spread. Dividing back out leaves
            # rounding noise that can put the close a hair outside the bands and flip the trend.
            up[i] = tp
            dn[i] = tp
            continue
        vw = cpv / cv
        var = max(cp2v / cv - vw * vw, 0.0)
        band = np.sqrt(var) * mult
        up[i] = vw + band
        dn[i] = vw - band
    return up, dn


@njit(cache=True)
def _band_scale(x, upper, lower):
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(n):
        v = x[i]
        if np.isnan(v) or np.isnan(upper[i]) or np.isnan(lower[i]):
            continue
        up = max(upper[i], 1e-12)
        lo = min(lower[i], -1e-12)
        if v >= 0.0:
            out[i] = 50.0 + 25.0 * min(max(v / up, 0.0), 1.0) \
                + 25.0 * min(max((v - up) / (0.5 * up), 0.0), 1.0)
        else:
            out[i] = 50.0 - 25.0 * min(max(v / lo, 0.0), 1.0) \
                - 25.0 * min(max((v - lo) / (0.5 * lo), 0.0), 1.0)
    return out


@njit(cache=True)
def components_kernel(h, l, c, v, day, use_vwap, p):
    """The 11 component series (columns follow ``COMPONENTS``) for parameter vector ``p``."""
    n = len(c)
    rsi_len = int(np.rint(p[0]))
    stoch_len = int(np.rint(p[1]))
    stoch_smooth = int(np.rint(p[2]))
    stoch_rsi_len = int(np.rint(p[3]))
    cci_len = int(np.rint(p[4]))
    bbp_len = int(np.rint(p[5]))
    ma_len = int(np.rint(p[6]))
    bb_len = int(np.rint(p[7]))
    bb_mult = p[8]
    st_len = int(np.rint(p[9]))
    st_mult = p[10]
    vwap_mult = p[11]
    linreg_len = int(np.rint(p[12]))
    structure_len = int(np.rint(p[13]))
    smooth = max(1, int(np.rint(p[14])))

    out = np.full((n, 11), np.nan)

    rsi = _rsi(c, rsi_len)
    out[:, 0] = _zone(rsi, 0.0, 30.0, 50.0, 70.0, 100.0)

    k = _roll_mean(_stoch(c, h, l, stoch_len), stoch_smooth, stoch_smooth)
    out[:, 1] = _zone(k, 0.0, 20.0, 50.0, 80.0, 100.0)

    sr = _roll_mean(_stoch(rsi, rsi, rsi, stoch_rsi_len), stoch_smooth, stoch_smooth)
    out[:, 2] = _zone(sr, 0.0, 20.0, 50.0, 80.0, 100.0)

    hlc3 = (h + l + c) / 3.0
    out[:, 3] = _zone(_cci(hlc3, cci_len), -300.0, -100.0, 0.0, 100.0, 300.0)

    ema = _ewm(c, 2.0 / (bbp_len + 1.0))
    bbp = h + l - 2.0 * ema
    basis = _roll_mean(bbp, 100, 20)
    dev = _roll_std0(bbp, 100, 20) * 2.0
    out[:, 4] = _band_scale(bbp, basis + dev, basis - dev)

    ma = _roll_mean(c, ma_len, ma_len)
    buy, sell = _flags_above_below(c, ma, ma)
    out[:, 5] = _anchored(c, buy, sell, smooth)

    mid = _roll_mean(c, bb_len, bb_len)
    band = _roll_std0(c, bb_len, bb_len) * bb_mult
    buy, sell = _flags_above_below(c, mid + band, mid - band)
    out[:, 6] = _anchored(c, buy, sell, smooth)

    st = _supertrend(h, l, c, st_len, st_mult)
    buy, sell = _flags_above_below(c, st, st)
    out[:, 7] = _anchored(c, buy, sell, smooth)

    if use_vwap:
        up, dn = _vwap_bands(h, l, c, v, day, vwap_mult)
        buy, sell = _flags_above_below(c, up, dn)
        out[:, 8] = _anchored(c, buy, sell, smooth)

    out[:, 9] = 50.0 * _time_corr(c, linreg_len) + 50.0

    buy, sell = _structure(h, l, c, structure_len)
    out[:, 10] = _anchored(c, buy, sell, smooth)
    return out


@njit(cache=True)
def score_from_components(comps, use_vwap):
    """Mean of the components; NaN until every one in use has warmed up."""
    n, m = comps.shape
    out = np.full(n, np.nan)
    for i in range(n):
        s = 0.0
        k = 0
        ok = True
        for j in range(m):
            if j == 8 and not use_vwap:
                continue
            x = comps[i, j]
            if np.isnan(x):
                ok = False
                break
            s += x
            k += 1
        if ok and k > 0:
            out[i] = s / k
    return out


@njit(cache=True)
def sentiment_kernel(h, l, c, v, day, use_vwap, p):
    return score_from_components(components_kernel(h, l, c, v, day, use_vwap, p), use_vwap)


# ---- loss -------------------------------------------------------------------------------
@njit(cache=True)
def _huber(x, delta):
    a = abs(x)
    return 0.5 * x * x if a <= delta else delta * (a - 0.5 * delta)


@njit(cache=True)
def loss_value(score, ref, warm, delta, w_corr, w_diff):
    """Huber error in index points + (1 - correlation) + Huber error of bar-to-bar changes.

    Bars where the reference has a value but ours is missing are penalised, so shifting the
    warm-up cannot be used to dodge hard bars.
    """
    n = len(score)
    need = 0
    cnt = 0
    sh = 0.0
    sx = sy = sxx = syy = sxy = 0.0
    sd = 0.0
    nd = 0
    for i in range(warm, n):
        if np.isnan(ref[i]):
            continue
        need += 1
        if np.isnan(score[i]):
            continue
        cnt += 1
        e = score[i] - ref[i]
        sh += _huber(e, delta)
        sx += score[i]
        sy += ref[i]
        sxx += score[i] * score[i]
        syy += ref[i] * ref[i]
        sxy += score[i] * ref[i]
        if i > warm and not np.isnan(score[i - 1]) and not np.isnan(ref[i - 1]):
            sd += _huber((score[i] - score[i - 1]) - (ref[i] - ref[i - 1]), delta)
            nd += 1
    if need < 10 or cnt < 0.5 * need:
        return 1e3
    mean_h = sh / cnt
    cov = sxy / cnt - (sx / cnt) * (sy / cnt)
    vx = sxx / cnt - (sx / cnt) ** 2
    vy = syy / cnt - (sy / cnt) ** 2
    corr = cov / np.sqrt(vx * vy) if vx > 1e-12 and vy > 1e-12 else 0.0
    diff = sd / nd if nd > 0 else 0.0
    missing = 50.0 * (need - cnt) / need
    return mean_h + w_corr * (1.0 - corr) + w_diff * diff + missing


@njit(parallel=True, cache=True)
def batch_loss(P, h, l, c, v, day, use_vwap, ref, warm, delta, w_corr, w_diff):
    """Loss of every row of ``P`` (candidates x parameters), evaluated in parallel."""
    out = np.empty(P.shape[0])
    for k in prange(P.shape[0]):
        s = sentiment_kernel(h, l, c, v, day, use_vwap, P[k])
        out[k] = loss_value(s, ref, warm, delta, w_corr, w_diff)
    return out
