"""Read LuxAlgo's Price Action Concepts off a Vela screenshot.

The toolkit is closed code and draws labels, boxes and lines rather than numbers, so its output can
only be measured from the picture. This module turns one lossless screenshot (the browser's
``zoom`` capture of the chart area) into events: each dashed structure line gives a pivot bar (left
end), a break bar (right end) and a side.

Pixels become bars by matching the picture's candles to real candles: the silhouette of the candle
highs (top of each candle, left to right) correlates with the price series at exactly one place, which
fixes the bar of every pixel column without reading any axis label. A fit is only used when that
match is clear (``Fit.corr``) and the candles line up (``Fit.hit``).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from PIL import Image

# colours of the toolkit's thin lines, measured on a lossless capture (text and dashes share them)
TOP_Y = 40          # below the legend row; the plot starts here in a capture of the chart area


def load(path: str) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB")).astype(int)


def masks(a: np.ndarray) -> dict[str, np.ndarray]:
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return {
        "bull": (g - r > 60) & (g > 100) & (b > 80),
        "bear": (r - g > 120) & (r > 180),
    }


def _vertical_runs(mask: np.ndarray, min_len: int) -> np.ndarray:
    """Mask of pixels that sit in a vertical run of at least ``min_len`` (candle bodies and wicks)."""
    h, w = mask.shape
    out = np.zeros_like(mask)
    for x in range(w):
        col = mask[:, x]
        d = np.diff(np.concatenate(([0], col.view(np.int8), [0])))
        for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
            if e - s >= min_len:
                out[s:e, x] = True
    return out


@dataclass
class Fit:
    """Maps picture columns to bars of the candle table, and rows to prices."""
    i0: int               # index in the candle table of the bar at x0
    x0: float             # pixel column of that bar's centre
    dx: float             # pixels per bar
    y0: float             # row of price p0
    p0: float
    px_per_price: float
    corr: float           # correlation of the candle silhouette with the price series
    hit: float            # share of candle highs and lows that sit where the fit says
    n_bars: int

    def x_of(self, i: float) -> float:
        return self.x0 + (i - self.i0) * self.dx

    def bar_of(self, x: float) -> int:
        return int(round(self.i0 + (x - self.x0) / self.dx))

    def y_of(self, p: float) -> float:
        return self.y0 + (self.p0 - p) * self.px_per_price

    def price_of(self, y: float) -> float:
        return self.p0 - (y - self.y0) / self.px_per_price


def fit(a: np.ndarray, candles: pd.DataFrame, dx_guess: float, plot_x: tuple[int, int],
        plot_y: tuple[int, int], i_range: tuple[int, int] | None = None,
        cand: np.ndarray | None = None, dx_span: float = 0.01) -> Fit:
    """Fit the picture to the candle table. ``cand`` is a mask of candle pixels when the chart colours its
    candles differently (the default is green and red); ``dx_span`` is how far the bar spacing may be from
    ``dx_guess``, as a share of it."""
    if cand is None:
        m = masks(a)
        cand = _vertical_runs(m["bull"] | m["bear"], 4)
    cand = cand.copy()
    cand[: plot_y[0]] = False
    cand[plot_y[1]:] = False
    x_lo, x_hi = plot_x
    colsum = cand.sum(0).astype(float)
    # 1. dx and the column of one bar: the comb that catches the most candle pixels
    best = (-1.0, dx_guess, 0.0)
    for dx in np.arange(dx_guess * (1 - dx_span), dx_guess * (1 + dx_span), dx_guess * max(0.0005, dx_span / 40)):
        for ph in np.arange(0, dx, 0.25):
            xs = np.round(np.arange(x_lo + ph, x_hi, dx)).astype(int)
            s = colsum[xs[(xs >= 0) & (xs < a.shape[1])]].sum()
            if s > best[0]:
                best = (s, dx, ph)
    _, dx, ph = best
    xs = np.arange(x_lo + ph, x_hi - dx / 2, dx)
    n = len(xs)
    # 2. each bar's candle: the tallest connected vertical stroke in its column (text strokes are shorter)
    top = np.full(n, np.nan)
    bot = np.full(n, np.nan)
    for k, x in enumerate(xs):
        xi = int(round(x))
        strip = cand[:, max(xi - 1, 0):xi + 2].any(1)
        d = np.diff(np.concatenate(([0], strip.view(np.int8), [0])))
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        # join strokes split by a one-pixel gap, then keep the tallest
        segs = []
        for s_, e_ in zip(starts, ends):
            if segs and s_ - segs[-1][1] <= 2:
                segs[-1][1] = e_
            else:
                segs.append([s_, e_])
        if segs:
            s_, e_ = max(segs, key=lambda t: t[1] - t[0])
            if e_ - s_ >= 6:
                top[k], bot[k] = s_, e_ - 1
    ok = ~np.isnan(top)
    highs = candles["high"].to_numpy()
    lows = candles["low"].to_numpy()
    # the chart can run past the last candle (empty columns), so each trial uses only bars that exist
    lo_i, hi_i = (0, len(candles) - 40) if i_range is None else i_range
    best_c, best_i = -2.0, 0
    for i0 in range(max(lo_i, 0), min(hi_i, len(candles) - 40) + 1):
        kmax = min(n, len(candles) - i0)
        m = ok[:kmax]
        if m.sum() < 40:
            continue
        h = highs[i0:i0 + kmax][m]
        l = lows[i0:i0 + kmax][m]
        c = (np.corrcoef(top[:kmax][m], -h)[0, 1] + np.corrcoef(bot[:kmax][m], -l)[0, 1]) / 2
        if c > best_c:
            best_c, best_i = c, i0
    # 3. rows to prices: regress the candle tops on the highs of the matched bars
    kmax = min(n, len(candles) - best_i)
    m = ok[:kmax]
    h = highs[best_i:best_i + kmax]
    A = np.vstack([h[m], np.ones(m.sum())]).T
    slope, icpt = np.linalg.lstsq(A, top[:kmax][m], rcond=None)[0]   # top_y = slope * high + icpt
    px_per_price = -slope
    p0 = 0.0
    y0 = icpt                                                       # y of price 0
    f = Fit(best_i, xs[0], dx, y0, p0, px_per_price, best_c, 0.0, kmax)
    # 4. how well do candle highs and lows line up with the fit?
    hits = tot = 0
    for k in range(kmax):
        xi = int(round(xs[k]))
        for p, off in ((highs[best_i + k], 1.5), (lows[best_i + k], -1.5)):
            yi = int(round(f.y_of(p) + off))
            if 0 <= yi < a.shape[0]:
                tot += 1
                hits += bool(cand[max(yi - 1, 0):yi + 2, max(xi - 1, 0):xi + 2].any())
    f.hit = hits / max(tot, 1)
    return f


@dataclass
class Line:
    side: int              # +1 bullish (green), -1 bearish (red)
    x_left: float
    x_right: float
    y: float
    dashes: int
    pivot_bar: int         # index in the candle table
    break_bar: int
    level: float


def structure_lines(a: np.ndarray, f: Fit, plot_x: tuple[int, int], plot_y: tuple[int, int],
                    min_px: float = 20.0, max_gap: float = 16.0) -> list[Line]:
    """Dashed horizontal lines of either colour that end at a candle (not at the right edge)."""
    out: list[Line] = []
    h, w = a.shape[:2]
    m_all = masks(a)
    covers = _vertical_runs(m_all["bull"] | m_all["bear"], 4)          # candles (tall coloured strokes)
    for side, mask in ((1, m_all["bull"]), (-1, m_all["bear"])):
        dash_rows: dict[int, list[tuple[int, int]]] = {}
        for y in range(plot_y[0], plot_y[1]):
            row = mask[y]
            d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
            for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0] - 1):
                ln = e - s + 1
                if ln < 3 or ln > 12 or s < plot_x[0] or e > plot_x[1]:
                    continue
                above = mask[y - 3, s:e + 1].any() if y >= 3 else False
                below = mask[y + 3, s:e + 1].any() if y + 3 < h else False
                if not above and not below:
                    dash_rows.setdefault(y, []).append((s, e))
        chains = []
        for y, runs in dash_rows.items():
            runs.sort()
            cur = [y, runs[0][0], runs[0][1], 1]
            for s, e in runs[1:]:
                if s - cur[2] <= max_gap:
                    cur[2], cur[3] = e, cur[3] + 1
                else:
                    chains.append(cur)
                    cur = [y, s, e, 1]
            chains.append(cur)
        chains.sort(key=lambda c: (c[0], c[1]))
        merged: list[list] = []
        for c in chains:
            for m in merged:
                if abs(c[0] - m[0]) <= 2 and min(c[2], m[2]) - max(c[1], m[1]) > 0:
                    m[1], m[2], m[3] = min(m[1], c[1]), max(m[2], c[2]), max(m[3], c[3])
                    break
            else:
                merged.append(list(c))
        # a candle drawn over a line hides it for a few bars: bridge fragments on one row when candles
        # actually cover the gap (otherwise two separate lines at one price would be glued together)
        merged.sort(key=lambda m: (m[0], m[1]))
        bridged: list[list] = []
        for m in merged:
            for b in bridged:
                gap = m[1] - b[2]
                if abs(m[0] - b[0]) <= 2 and 0 < gap <= 110:
                    cols = np.arange(b[2] + 1, m[1])
                    y = int(round((m[0] + b[0]) / 2))
                    covered = covers[max(y - 1, 0):y + 2][:, cols].any(0).mean() if len(cols) else 1.0
                    if covered >= 0.55:
                        b[2], b[3] = m[2], b[3] + m[3]
                        break
            else:
                bridged.append(list(m))
        merged = [m for m in bridged if m[3] >= 3 and m[2] - m[1] >= min_px]   # short leftovers are noise
        for y, xl, xr, n in merged:
            if xr - xl > 900 or xr > plot_x[1] - 6:         # the current-price line, or a box running right
                continue
            out.append(Line(side, xl, xr, float(y), n, f.bar_of(xl), f.bar_of(xr), f.price_of(y)))
    out.sort(key=lambda ln: ln.x_right)
    return out


# ------------------------------------------------------------------ labels
def glyph_mask(a: np.ndarray, side_mask: np.ndarray, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
    """Pixels of label text in a window: coloured, and not part of a tall stroke (a candle)."""
    y0, x0 = max(y0, 0), max(x0, 0)
    win = side_mask[y0:y1, x0:x1]
    return win & ~_vertical_runs(win, 14)


def cut_template(a: np.ndarray, centre: tuple[int, int], half_w: int = 45, half_h: int = 12) -> np.ndarray:
    """A label's text as a boolean template, cut around ``centre`` (x, y) of a clean example."""
    m = masks(a)
    cx, cy = centre
    g = glyph_mask(a, m["bull"] | m["bear"], cy - half_h, cy + half_h, cx - half_w, cx + half_w)
    cols = np.where(g.sum(0) > 0)[0]
    groups, cur = [], [cols[0]]
    for x in cols[1:]:
        if x - cur[-1] <= 6:
            cur.append(x)
        else:
            groups.append(cur)
            cur = [x]
    groups.append(cur)
    grp = max(groups, key=len)
    g = g[:, grp[0]:grp[-1] + 1]
    rows = np.where(g.sum(1) > 0)[0]
    return g[rows[0]:rows[-1] + 1]


def classify_label(a: np.ndarray, line: Line, templates: dict[str, np.ndarray],
                   search: tuple[int, int] = (50, 14)) -> tuple[str, float]:
    """Best-matching label type near a line's midpoint (above it if bullish, below if bearish).

    The score is the share of a template's pixels found in the picture, less a penalty for glyph
    pixels inside the template's box that the template does not explain.
    """
    m = masks(a)
    side_mask = m["bull"] if line.side > 0 else m["bear"]
    mid = int((line.x_left + line.x_right) / 2)
    scores: dict[str, float] = {}
    for name, t in templates.items():
        th, tw = t.shape
        if line.side > 0:
            ya, yb = int(line.y - 42), int(line.y - 4)
        else:
            ya, yb = int(line.y + 4), int(line.y + 42)
        xa, xb = mid - search[0] - tw // 2, mid + search[0] + tw // 2
        g = glyph_mask(a, side_mask, ya, yb, xa, xb)
        gd = g.copy()
        gd[1:] |= g[:-1]; gd[:-1] |= g[1:]; gd[:, 1:] |= g[:, :-1]; gd[:, :-1] |= g[:, 1:]   # 1px tolerance
        H, W = g.shape
        for dy in range(0, H - th + 1):
            for dxp in range(0, W - tw + 1):
                hit = (t & gd[dy:dy + th, dxp:dxp + tw]).sum() / t.sum()
                extra = (g[dy:dy + th, dxp:dxp + tw] & ~t).sum() / max(t.sum(), 1)
                sc = hit - 0.5 * extra
                if sc > scores.get(name, -1.0):
                    scores[name] = sc
    good = [n for n, sc in scores.items() if sc >= 0.85]
    if good:   # CHoCH+ contains CHoCH, so when both fit, the longer text is the right one
        name = max(good, key=lambda n: templates[n].shape[1])
        return name, scores[name]
    name = max(scores, key=scores.get)
    return name, scores[name]


# ------------------------------------------------------------------ whole windows
PLOT_X = (10, 1392)       # chart area of a 1400x864 zoom capture of the plot
PLOT_Y = (130, 700)       # below the legend and trading widget, above the volume bars
DX_GUESS = 6.638          # pixels per bar of the capture at Vela's current chart zoom
EDGE = 20                 # columns near either side where a line may be cut off


@dataclass
class Event:
    break_bar: int
    pivot_bar: int
    side: int
    kind: str
    score: float
    window: int
    level_error: float = 0.0     # how far the drawn level was from the snapped pivot's high/low, in price
    inferred: bool = False       # the visible line ended early (hidden by candles); the break is the first close beyond


def refine(ln: Line, f: Fit, candles: pd.DataFrame) -> tuple[int, int, float, bool]:
    """Snap a line's ends to real bars using the level it was drawn at.

    A candle drawn over the end of a dashed line hides its last dash, so the ends read off the picture are a
    bar or two out. The line's height is the level of the swing it comes from: the pivot is the candle near
    the line's left end whose high (bullish) or low (bearish) is at that level, and the break is the first close
    beyond the level shortly after the line's right end.
    """
    high = candles["high"].to_numpy()
    low = candles["low"].to_numpy()
    close = candles["close"].to_numpy()
    n = len(candles)
    level = ln.level
    lo, hi = max(ln.pivot_bar - 3, 0), min(ln.pivot_bar + 2, n - 1)
    series = high if ln.side > 0 else low
    j = min(range(lo, hi + 1), key=lambda b: abs(series[b] - level))
    err = abs(series[j] - level)
    exact = series[j]
    def beyond(b: int) -> bool:
        return bool(close[b] > exact) if ln.side > 0 else bool(close[b] < exact)

    b0 = max(ln.break_bar - 1, j + 1)
    for b in range(b0, min(ln.break_bar + 4, n - 1) + 1):        # the visible end: the break is right here
        if beyond(b):
            return j, b, err, False
    for b in range(min(ln.break_bar + 5, n - 1), min(ln.break_bar + 40, n - 1) + 1):   # truncated: look on
        if beyond(b):
            return j, b, err, True
    return j, ln.break_bar, err, False


def read_window(path: str, candles: pd.DataFrame, templates: dict[str, np.ndarray], window: int = 0,
                min_score: float = 0.6) -> tuple[Fit, list[Event]]:
    a = load(path)
    f = fit(a, candles, DX_GUESS, PLOT_X, PLOT_Y)
    events = []
    for ln in structure_lines(a, f, PLOT_X, PLOT_Y):
        if ln.x_left < PLOT_X[0] + EDGE or ln.x_right > PLOT_X[1] - EDGE or ln.break_bar >= len(candles):
            continue                                        # cut off by the edge of the capture
        kind, sc = classify_label(a, ln, templates)
        if sc < min_score:
            continue                                        # no label: an order-block midline or a fragment
        pivot, brk, err, inferred = refine(ln, f, candles)
        events.append(Event(brk, pivot, ln.side, kind, sc, window, err, inferred))
    return f, events


def dedupe(events: list[Event]) -> list[Event]:
    """One event per (break bar, side): windows overlap, so the same line can be read twice."""
    seen: dict[tuple[int, int], Event] = {}
    for e in events:
        k = (e.break_bar, e.side)
        if k not in seen or e.score > seen[k].score:
            seen[k] = e
    return sorted(seen.values(), key=lambda e: e.break_bar)
