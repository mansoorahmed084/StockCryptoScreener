"""Read LuxAlgo's Signals & Overlays off a Vela capture: the band, the signals and the X marks.

Like ``pac_vision`` this works on the lossless ``zoom`` capture of the chart area. Pixels become bars by
fitting the candles to the candle table. Then, per bar:

* the band: the Smart Trail line, blue under price in an uptrend and red above it in a downtrend,
  read as a price at every bar;
* the signals: the green / red labels, strong ones (with "+") being wider;
* the X marks: small crosses, blue or orange.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import pac_vision as pv

# the toolkit's own colours, measured on a capture
ORANGE = (255, 138, 0)
BLUE_X = (40, 98, 255)


def candle_mask(a: np.ndarray) -> np.ndarray:
    """Candle strokes: this chart colours candles green, red and purple (neutral)."""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    green = (g - r > 60) & (g > 150) & (b > 80) & (g > b)
    red = (r > 200) & (g < 60) & (b < 60)
    purple = (b - g > 80) & (r > 70) & (r < 130) & (b > 150)
    return pv._vertical_runs(green | red | purple, 4)


def label_masks(a: np.ndarray) -> dict[str, np.ndarray]:
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    close = lambda col, tol: (np.abs(r - col[0]) <= tol) & (np.abs(g - col[1]) <= tol) & (np.abs(b - col[2]) <= tol)
    return {
        "buy": close((40, 136, 80), 10),        # the green label fill
        "sell": close((170, 18, 18), 14),       # the red label fill
        "orange": close(ORANGE, 40),
        "blue_x": close(BLUE_X, 45),
    }


def line_masks(a: np.ndarray) -> dict[str, np.ndarray]:
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    blue = (b >= 120) & (r <= 70) & (b - r >= 70) & (g <= 150)
    red = (r >= 150) & (g >= 40) & (g <= 140) & (b >= 40) & (b <= 150) & (r - g >= 70)
    return {"blue": blue, "red": red}


def _components(mask: np.ndarray, min_area: int, max_area: int):
    """Connected components (8-neighbour: the strokes of an X only touch diagonally) as (area, x0, x1, y0, y1, cx, cy)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        stack = [(y0, x0)]
        seen[y0, x0] = True
        pts = []
        while stack:
            y, x = stack.pop()
            pts.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not seen[yy, xx]:
                    seen[yy, xx] = True
                    stack.append((yy, xx))
        if min_area <= len(pts) <= max_area:
            py = np.array([p[0] for p in pts])
            px = np.array([p[1] for p in pts])
            out.append((len(pts), px.min(), px.max(), py.min(), py.max(), px.mean(), py.mean()))
    return out


@dataclass
class Mark:
    bar: int
    side: int            # +1 green / blue, -1 red / orange
    kind: str            # "strong", "normal", or the X colour
    x: float
    y: float


@dataclass
class Capture:
    fit: pv.Fit
    trail: np.ndarray                    # price of the trail line (the band's outer edge) per bar, NaN where unread
    inner: np.ndarray                    # price of the band's price-side edge
    trail_dir: np.ndarray                # +1 blue (uptrend), -1 red (downtrend), 0 unread
    signals: list[Mark] = field(default_factory=list)
    xmarks: list[Mark] = field(default_factory=list)


RIBBON_BLUE = (28, 41, 69)
RIBBON_RED = (66, 34, 40)


def in_widget(x: float, y: float) -> bool:
    """The trading widget and the legend sit over the top of the chart."""
    return (440 <= x <= 740 and y <= 95) or (x <= 330 and y <= 115)


def read_ribbon(a: np.ndarray, f: pv.Fit, plot_y: tuple[int, int], n_table: int, tol: int = 7):
    """The band's two edges at every bar, from the flat fill between its lines.

    Candles are drawn over the band, so each bar is read in the columns between candles. Blue fill is an
    uptrend (the trail line is its lower edge), red fill a downtrend (the trail line is its upper edge).
    Returns the price of the trail-side edge and of the price-side edge, and the direction, per bar.
    """
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    fills = {1: (np.abs(r - RIBBON_BLUE[0]) <= tol) & (np.abs(g - RIBBON_BLUE[1]) <= tol) & (np.abs(b - RIBBON_BLUE[2]) <= tol),
             -1: (np.abs(r - RIBBON_RED[0]) <= tol) & (np.abs(g - RIBBON_RED[1]) <= tol) & (np.abs(b - RIBBON_RED[2]) <= tol)}
    trail = np.full(n_table, np.nan)
    inner = np.full(n_table, np.nan)
    direction = np.zeros(n_table, np.int8)
    for k in range(f.n_bars):
        i = f.i0 + k
        if i >= n_table:
            break
        found = []
        for side, m in fills.items():
            best = None
            for off in (0.5, 0.35, 0.65, 0.25, 0.75):              # between this candle and the next
                x = int(round(f.x0 + (k + off) * f.dx))
                col = m[plot_y[0]:plot_y[1], x]
                d = np.diff(np.concatenate(([0], col.view(np.int8), [0])))
                runs = [(s_, e_) for s_, e_ in zip(np.where(d == 1)[0], np.where(d == -1)[0]) if e_ - s_ >= 3]
                if runs:
                    s_, e_ = max(runs, key=lambda t: t[1] - t[0])
                    if best is None or e_ - s_ > best[1] - best[0]:
                        best = (s_ + plot_y[0], e_ + plot_y[0])
            if best is not None:
                found.append((side, best))
        if len(found) != 1:
            continue
        side, (top, bot) = found[0]
        # up: the trail is the lower edge (largest y); down: the upper edge
        y_trail, y_inner = (bot, top) if side > 0 else (top, bot)
        trail[i] = f.price_of(float(y_trail))
        inner[i] = f.price_of(float(y_inner))
        direction[i] = side
    return trail, inner, direction


def read_capture(a: np.ndarray, candles: pd.DataFrame, dx_guess: float, plot_y: tuple[int, int] = (120, 600),
                 dx_span: float = 0.12) -> Capture:
    H, W = a.shape[:2]
    cand = candle_mask(a)
    f = pv.fit(a, candles, dx_guess, (6, W - 8), plot_y, cand=cand, dx_span=dx_span)
    n = len(candles)
    trail, inner, tdir = read_ribbon(a, f, plot_y, n)
    cap = Capture(f, trail, inner, tdir)
    lm = label_masks(a)
    # signal labels: strong ones (with "+") are about 38 px wide, normal ones 29; the pointer names the bar
    for key, side in (("buy", 1), ("sell", -1)):
        for area, x0, x1, y0, y1, cx, cy in _components(lm[key], 250, 4000):
            if in_widget(cx, cy) or cy > plot_y[1] + 20:
                continue
            tips = []
            for y in range(y0, y1 + 1):
                xs = np.where(lm[key][y, x0:x1 + 1])[0]
                if len(xs) and xs.max() - xs.min() + 1 <= 12:
                    tips.append(x0 + (xs.min() + xs.max()) / 2)
            x = float(np.mean(tips)) if tips else float(cx)
            strong = (x1 - x0 + 1) >= 34
            bar = f.bar_of(x)
            if 0 <= bar < n:
                cap.signals.append(Mark(bar, side, "strong" if strong else "normal", x, cy))
    # X marks
    for key, side in (("blue_x", 1), ("orange", -1)):
        for area, x0, x1, y0, y1, cx, cy in _components(lm[key], 12, 120):
            w_, h_ = x1 - x0 + 1, y1 - y0 + 1
            if not (4 <= w_ <= 13 and 4 <= h_ <= 13) or area > 0.9 * w_ * h_:
                continue                                         # an X is small, squarish and hollow
            if in_widget(cx, cy) or cy > plot_y[1] + 45:
                continue
            bar = f.bar_of(cx)
            if 0 <= bar < n:
                cap.xmarks.append(Mark(bar, side, "blue" if side > 0 else "orange", cx, cy))
    cap.signals.sort(key=lambda m: m.bar)
    cap.xmarks.sort(key=lambda m: m.bar)
    return cap


# ------------------------------------------------------------------ several windows into one reference
@dataclass
class Reference:
    trail: np.ndarray
    inner: np.ndarray
    direction: np.ndarray
    signals: dict            # bar -> (side, "strong" | "normal")
    xmarks: dict             # bar -> side (+1 blue, -1 orange)
    covered: np.ndarray      # bars that some window shows fully (not at an edge)
    windows: list = field(default_factory=list)


def read_windows(paths: list[str], candles: pd.DataFrame, dx_guess: float, edge: int = 24) -> Reference:
    n = len(candles)
    ref = Reference(np.full(n, np.nan), np.full(n, np.nan), np.zeros(n, np.int8), {}, {}, np.zeros(n, bool))
    for w, p in enumerate(paths):
        a = pv.load(p)
        cap = read_capture(a, candles, dx_guess)
        f = cap.fit
        H, W = a.shape[:2]
        lo = f.bar_of(edge)
        hi = f.bar_of(W - edge)
        ref.windows.append((w, f.i0, f.n_bars, round(f.corr, 3)))
        for i in range(max(lo, 0), min(hi, n - 1) + 1):
            ref.covered[i] = True
            if cap.trail_dir[i] != 0 and ref.direction[i] == 0:
                ref.trail[i], ref.inner[i], ref.direction[i] = cap.trail[i], cap.inner[i], cap.trail_dir[i]
        for m in cap.signals:
            if lo <= m.bar <= hi:
                ref.signals[m.bar] = (m.side, m.kind)
        for m in cap.xmarks:
            if lo <= m.bar <= hi:
                ref.xmarks[m.bar] = m.side
    return ref
