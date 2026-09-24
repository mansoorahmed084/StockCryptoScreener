"""Automatic trendlines, support / resistance levels, Fibonacci and chart
patterns — the lines a trader draws by hand on a chart.

Everything starts from swing points: fractal pivot highs and lows (a bar that
is the extreme of ``pivot`` bars on each side). Tolerances are in ATR, so one
setting works on any coin and timeframe.

  Trendlines   every pair of swing lows (support) or swing highs (resistance)
               is a candidate line. It survives if no candle CLOSES more than
               ``tol`` through it from its first touch to now (wicks may
               poke through, as on a hand-drawn chart). Lines are ranked by
               touches, span and how recent the last touch is; near-duplicates
               are dropped.
  Levels       swing highs and lows within ``tol`` of each other form a flat
               level; two or more touches make it count.
  Fibonacci    the biggest leg in view (lowest low to highest high, in time
               order): retracements 0.236 .. 0.786 and extensions 1.272 / 1.618.
  Patterns     the best support and resistance lines, by their slopes and
               whether they converge: triangles, wedges, channels, ranges.
               Plus double tops / bottoms from the last two swing points.

Lines are drawn with hindsight over the window shown, like a trader's; they
describe the chart, they do not predict it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


SUPPORT, RESISTANCE = "support", "resistance"
FIB_RETRACE = (0.236, 0.382, 0.5, 0.618, 0.786)
FIB_EXTEND = (1.272, 1.618)


@dataclass
class Line:
    kind: str                 # support | resistance
    i0: int                   # first touch (bar index)
    i1: int                   # second anchor
    p0: float
    p1: float
    touches: int
    last_touch: int
    score: float
    broken: bool = False      # the last close is through the line

    @property
    def slope(self) -> float:
        """Price change per bar."""
        return (self.p1 - self.p0) / (self.i1 - self.i0)

    def at(self, i: float) -> float:
        return self.p0 + self.slope * (i - self.i0)


@dataclass
class Level:
    kind: str                 # support | resistance (vs the last close)
    price: float
    touches: int
    first: int
    last: int


@dataclass
class Fib:
    direction: str            # up (low came first) | down
    start_i: int
    start: float
    end_i: int
    end: float
    levels: dict[float, float]      # ratio -> price


@dataclass
class Pattern:
    name: str
    bias: str                 # bullish | bearish | neutral
    status: str               # inside | broke up | broke down | confirmed | forming
    upper: Line | None = None
    lower: Line | None = None
    start: int = 0
    breakout_up: float = float("nan")
    breakout_down: float = float("nan")
    target_up: float = float("nan")
    target_down: float = float("nan")
    points: list[tuple[int, float]] = field(default_factory=list)   # doubles
    note: str = ""


@dataclass
class ChartAnalysis:
    atr: float
    tol: float
    pivot: int
    supports: list[Line]
    resistances: list[Line]
    levels: list[Level]
    fib: Fib | None
    patterns: list[Pattern]


def swing_points(series: pd.Series, k: int, *, high: bool) -> np.ndarray:
    """Bar indexes that are the highest (lowest) of the ``k`` bars each side.

    Equal extremes are common on real charts, a flat top made of candles with
    the same high. The first of them counts, so a flat top still yields swing
    points. (indicators.common.pivot_* require a unique extreme and would
    skip it.)
    """
    v = np.asarray(series, dtype=float)
    if len(v) < 2 * k + 1:
        return np.zeros(0, dtype=int)
    w = np.lib.stride_tricks.sliding_window_view(v, 2 * k + 1)   # one row per bar
    ext = w.max(axis=1) if high else w.min(axis=1)
    first = np.argmax(w == ext[:, None], axis=1)                 # first extreme in row
    return (np.flatnonzero((w[:, k] == ext) & (first == k)) + k).astype(int)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = (df[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
    prev = np.concatenate([[np.nan], c[:-1]])
    tr = np.fmax(h - l, np.fmax(np.abs(h - prev), np.abs(l - prev)))
    return pd.Series(tr, index=df.index).rolling(n, min_periods=1).mean()


# -- trendlines ----------------------------------------------------------------
def trendlines(df: pd.DataFrame, kind: str, *, pivot: int, tol: float,
               max_lines: int = 3, max_pivots: int = 30) -> list[Line]:
    """Active support or resistance lines, best first.

    A line broken only in the last ``3 * pivot`` candles is kept and marked
    ``broken``: a fresh breakout is the most useful thing to see, and the
    pattern it ends is reported as "broke up" / "broke down".
    """
    n = len(df)
    fresh = n - 3 * pivot           # closes from here on may cross the line
    sup = kind == SUPPORT
    series = df["low"] if sup else df["high"]
    piv = swing_points(series, pivot, high=not sup)[-max_pivots:]
    # Anchors use the full swing size; touches use a finer one, so a flat top
    # tested four times counts four even when some tests were small swings.
    touch_pts = swing_points(series, max(2, pivot // 2), high=not sup)
    vals = series.to_numpy()
    closes = df["close"].to_numpy()
    last_close = float(closes[-1])
    idx = np.arange(n)
    price_span = float(df["high"].max() - df["low"].min()) or 1.0

    cands: list[Line] = []
    for a in range(len(piv)):
        for b in range(a + 1, len(piv)):
            i, j = int(piv[a]), int(piv[b])
            slope = (vals[j] - vals[i]) / (j - i)
            if abs(slope) * n > 3 * price_span:        # absurdly steep
                continue
            line = vals[i] + slope * (idx[i:] - i)
            gap = closes[i:] - line
            through = (gap < -tol) if sup else (gap > tol)
            # No close through the line from its first touch until the last
            # few candles; a cross in those is a fresh break.
            if through[:max(0, fresh - i)].any():
                continue
            broken = bool(through[-1])
            # A line far from today's price is history, not a level to watch:
            # the old rally's rising top line can sit 30% above price.
            dist = abs(float(line[-1]) - last_close) / price_span
            if dist > 0.5:
                continue
            on = touch_pts[touch_pts >= i]
            near = np.abs(vals[on] - (vals[i] + slope * (on - i))) <= tol
            touches = max(2, int(near.sum()))
            last = max(j, int(on[near].max()) if near.any() else j)
            score = (touches + 0.5 * (last - i) / n
                     + 0.75 * (1 - (n - 1 - last) / n) - 4 * dist)
            cands.append(Line(kind, i, j, float(vals[i]), float(vals[j]),
                              touches, last, score, broken))

    out: list[Line] = []
    for c in sorted(cands, key=lambda l: l.score, reverse=True):
        if all(abs(c.at(n - 1) - o.at(n - 1)) > 2 * tol
               or abs(c.at(c.i0) - o.at(c.i0)) > 2 * tol for o in out):
            out.append(c)
        if len(out) == max_lines:
            break
    return out


# -- horizontal levels -----------------------------------------------------------
def levels(df: pd.DataFrame, *, pivot: int, tol: float, max_each: int = 2) -> list[Level]:
    """Flat support / resistance where 2+ swing points sit at one price.

    Points within ``2 * tol`` merge: three "levels" 0.3% apart are one zone.
    """
    tol = 2 * tol
    k = max(2, pivot // 2)                 # finer swings: every test of a level
    hi = swing_points(df["high"], k, high=True)
    lo = swing_points(df["low"], k, high=False)
    highs, lows = df["high"].to_numpy(dtype=float), df["low"].to_numpy(dtype=float)
    pts = sorted([(float(highs[i]), int(i)) for i in hi]
                 + [(float(lows[i]), int(i)) for i in lo])
    clusters: list[list[tuple[float, int]]] = []
    for p, i in pts:
        if clusters and p - np.mean([q for q, _ in clusters[-1]]) <= tol:
            clusters[-1].append((p, i))
        else:
            clusters.append([(p, i)])
    last = float(df["close"].iloc[-1])
    found = []
    for c in clusters:
        if len(c) < 2:
            continue
        price = float(np.mean([p for p, _ in c]))
        found.append(Level(RESISTANCE if price > last else SUPPORT, price, len(c),
                           min(i for _, i in c), max(i for _, i in c)))
    out: list[Level] = []
    for kind in (RESISTANCE, SUPPORT):
        side = [lv for lv in found if lv.kind == kind]
        side.sort(key=lambda lv: (lv.touches, lv.last), reverse=True)
        out += side[:max_each]
    return out


# -- fibonacci -------------------------------------------------------------------
def fibonacci(df: pd.DataFrame) -> Fib | None:
    """Retracements and extensions of the biggest leg in view."""
    if len(df) < 3:
        return None
    hi_i = int(np.argmax(df["high"].to_numpy()))
    lo_i = int(np.argmin(df["low"].to_numpy()))
    hi, lo = float(df["high"].iloc[hi_i]), float(df["low"].iloc[lo_i])
    rng = hi - lo
    if rng <= 0:
        return None
    if lo_i < hi_i:           # up leg: retrace down from the high
        lv = {0.0: hi, **{r: hi - r * rng for r in FIB_RETRACE}, 1.0: lo,
              **{r: lo + r * rng for r in FIB_EXTEND}}
        return Fib("up", lo_i, lo, hi_i, hi, lv)
    lv = {0.0: lo, **{r: lo + r * rng for r in FIB_RETRACE}, 1.0: hi,
          **{r: hi - r * rng for r in FIB_EXTEND}}
    return Fib("down", hi_i, hi, lo_i, lo, lv)


# -- patterns --------------------------------------------------------------------
def line_pattern(df: pd.DataFrame, upper: Line, lower: Line, tol: float) -> Pattern | None:
    """Classify the space between a resistance and a support line."""
    n = len(df)
    start = max(upper.i0, lower.i0)
    end = n - 1
    if end - start < 10:
        return None
    # Both lines must still be in play: touched in the second half of the view.
    if min(upper.last_touch, lower.last_touch) < n // 2:
        return None
    w0 = upper.at(start) - lower.at(start)
    w1 = upper.at(end) - lower.at(end)
    if w0 <= 0 or w1 <= 0:
        return None
    span = end - start

    def flat(line: Line) -> bool:
        return abs(line.slope * span) < 0.25 * w0

    ratio = w1 / w0
    converging, expanding = ratio < 0.75, ratio > 1.3
    u_up, l_up = upper.slope > 0, lower.slope > 0
    uf, lf = flat(upper), flat(lower)
    if uf and lf:
        name, bias = "Range", "neutral"
    elif expanding:
        name, bias = "Broadening pattern", "neutral"
    elif uf and l_up and converging:
        name, bias = "Ascending triangle", "bullish"
    elif lf and not u_up and converging:
        name, bias = "Descending triangle", "bearish"
    elif not u_up and l_up and converging:
        name, bias = "Symmetrical triangle", "neutral"
    elif u_up and l_up and converging:
        name, bias = "Rising wedge", "bearish"
    elif not u_up and not l_up and converging:
        name, bias = "Falling wedge", "bullish"
    elif u_up and l_up:
        name, bias = "Rising channel", "bullish"
    elif not u_up and not l_up:
        name, bias = "Falling channel", "bearish"
    else:
        return None

    close = float(df["close"].iloc[-1])
    up_lvl, dn_lvl = upper.at(end), lower.at(end)
    status = ("broke up" if close > up_lvl + tol else
              "broke down" if close < dn_lvl - tol else "inside")
    return Pattern(name=name, bias=bias, status=status, upper=upper, lower=lower,
                   start=start, breakout_up=up_lvl, breakout_down=dn_lvl,
                   target_up=up_lvl + w0, target_down=dn_lvl - w0,
                   note=f"height {w0:.6g} at the start, used for the targets")


def double_top_bottom(df: pd.DataFrame, *, pivot: int, tol: float,
                      recent: float = 0.3) -> list[Pattern]:
    """Two swing highs (lows) at one price with a real dip (rally) between them,
    the second one recent. Confirmed once price closes past the neckline.

    Both are REVERSAL patterns, so the move before them matters as much as the
    shape. A double bottom must be the low of a fall: price came down into the
    first bottom by at least most of the pattern's height, and nothing in the
    stretch before it (as long as the pattern itself) traded lower. Two equal
    lows inside an uptrend — a higher low retested — are trend continuation,
    not a double bottom. Double tops are the mirror image.
    """
    n = len(df)
    close = float(df["close"].iloc[-1])
    out: list[Pattern] = []
    for top in (True, False):
        s = df["high"] if top else df["low"]
        piv = swing_points(s, pivot, high=top)
        if len(piv) < 2:
            continue
        i1, i2 = int(piv[-2]), int(piv[-1])
        p1, p2 = float(s.iloc[i1]), float(s.iloc[i2])
        if i2 < n * (1 - recent) or i2 - i1 < 2 * pivot or abs(p1 - p2) > tol:
            continue
        mid = df.iloc[i1:i2 + 1]
        neck = float(mid["low"].min() if top else mid["high"].max())
        depth = (min(p1, p2) - neck) if top else (neck - max(p1, p2))
        if depth < 3 * tol:
            continue
        before = df.iloc[max(0, i1 - (i2 - i1)):i1]
        if len(before) < pivot:
            continue                              # no history to judge the move in
        if top:
            # The tops are the high of a rise: nothing higher just before, and
            # price climbed into the first top.
            if before["high"].max() > max(p1, p2) + tol \
                    or p1 - before["low"].min() < 0.8 * depth:
                continue
        else:
            if before["low"].min() < min(p1, p2) - tol \
                    or before["high"].max() - p1 < 0.8 * depth:
                continue
        if top:
            if close > max(p1, p2) + tol:
                continue                          # broken above: not a top
            status = "confirmed" if close < neck - tol else "forming"
            out.append(Pattern("Double top", "bearish", status, start=i1,
                               breakout_down=neck, target_down=neck - depth,
                               points=[(i1, p1), (i2, p2)],
                               note=f"neckline {neck:.6g}"))
        else:
            if close < min(p1, p2) - tol:
                continue
            status = "confirmed" if close > neck + tol else "forming"
            out.append(Pattern("Double bottom", "bullish", status, start=i1,
                               breakout_up=neck, target_up=neck + depth,
                               points=[(i1, p1), (i2, p2)],
                               note=f"neckline {neck:.6g}"))
    return out


def _flag(hi: np.ndarray, lo: np.ndarray, cl: np.ndarray, trend: np.ndarray, *,
          pivot: int, tol: float, atr_: float, min_pole_atr: float,
          max_retrace: float) -> dict | None:
    """Bull flag on (high, low, close) arrays; the bear flag calls this on the
    negated chart.

    The falling line is walked forward: at each candle it is drawn from the
    flag top through the highest lower high seen BEFORE that candle, and the
    first close above it is the breakout. The line is then locked there, so a
    breakout stays a breakout as price runs on. Of the tops that qualify, the
    highest one — the real start of the flag — wins.
    """
    n = len(hi)
    k_touch = max(2, pivot // 2)
    tops = swing_points(pd.Series(hi), pivot, high=True)
    touch_pts = swing_points(pd.Series(hi), k_touch, high=True)
    found: list[dict] = []
    for top in (int(t) for t in tops if n * 0.3 <= t <= n - 2 * pivot - 1):
        # A flag continues a trend: the top sits above a rising 50-candle EMA.
        if hi[top] <= trend[top] or trend[top] <= trend[max(0, top - 2 * pivot)]:
            continue
        lookback = max(3 * pivot, 2 * (n - top))
        j0 = max(0, top - lookback)
        pole_i = j0 + int(np.argmin(lo[j0:top]))
        pole = hi[top] - lo[pole_i]
        if pole < min_pole_atr * atr_:
            continue                      # no real rise before it
        first = top + k_touch + 1         # candles right after the top belong to it
        if n - first < 2 * pivot:
            continue
        # The line a trader would draw at candle i: from the top through a
        # lower swing high already confirmed then (well inside the pullback,
        # not the first dip), still respected — no close above it yet — and
        # touching the most lower highs. A close above it counts as the
        # breakout only once it has the top plus two lower highs on it.
        def best_line(i_end: int) -> tuple[int, float, int] | None:
            known = touch_pts[(touch_pts >= top + 2 * pivot)
                              & (touch_pts <= i_end - k_touch - 1)]
            seg = np.arange(top + 1, i_end)
            best = None
            for a_ in known:
                s_ = (hi[a_] - hi[top]) / (a_ - top)
                if s_ >= 0 or (cl[seg] > hi[top] + s_ * (seg - top) + tol).any():
                    continue
                t_ = 1 + int((np.abs(hi[known] - (hi[top] + s_ * (known - top)))
                              <= tol).sum())
                if best is None or (t_, s_) > (best[0], best[1]):
                    best = (t_, float(s_), int(a_))
            return best

        broke_i, slope, anchor, touches, failed = None, None, None, 0, False
        run_max = np.maximum.accumulate(hi[first:])      # highest high since `first`
        b, seen = None, -1
        for i in range(first + 2 * pivot, n):
            if run_max[i - 1 - first] > hi[top] + tol:
                failed = True             # a new high before any break: no flag
                break
            # Redraw only when a new swing high is confirmed or a close pokes
            # above the current line (which then stops being "respected").
            confirmed = int(np.searchsorted(touch_pts, i - k_touch - 1, side="right"))
            above = b is not None and cl[i] > hi[top] + b[1] * (i - top) + tol
            if confirmed != seen or b is None or above:
                if not (above and b[0] >= 3):
                    b, seen = best_line(i), confirmed
                if b and b[0] >= 3 and cl[i] > hi[top] + b[1] * (i - top) + tol:
                    # A break must hold until price clears the flag's top: a
                    # close back under the line before that makes it a false
                    # breakout. The line is then redrawn above that poke
                    # (best_line drops lines a close has crossed) and the walk
                    # goes on, the way a trader redraws it by eye.
                    j = np.arange(i + 1, n)
                    cleared = np.flatnonzero(cl[j] > hi[top] + tol)
                    j = j[:cleared[0]] if len(cleared) else j
                    if (cl[j] < hi[top] + b[1] * (j - top) - tol).any():
                        b, seen = None, -1
                        continue
                    touches, slope, anchor = b
                    broke_i = i
                    break
        if failed:
            continue
        stop = broke_i if broke_i is not None else n
        if broke_i is None:
            b = best_line(n)
            if b is None:
                continue
            touches, slope, anchor = b
        flag_i = top + 1 + int(np.argmin(lo[top + 1:stop]))
        retrace = (hi[top] - lo[flag_i]) / pole
        if not 0.1 <= retrace <= max_retrace:
            continue                      # too shallow to be a pullback, or too deep
        if cl[-1] < lo[flag_i] - tol:
            continue                      # price is back under the flag's low: failed
        if broke_i is not None and n - 1 - broke_i > 6 * pivot:
            continue                      # an old breakout: the pattern is done
        found.append({"top": top, "anchor": anchor, "slope": slope, "touches": touches,
                      "pole": pole, "pole_i": pole_i, "flag_i": flag_i,
                      "retrace": retrace, "broke": broke_i is not None,
                      "broke_i": broke_i})
    if not found:
        return None
    return max(found, key=lambda f: (hi[f["top"]], f["top"]))


def flags(df: pd.DataFrame, *, pivot: int, tol: float,
          supports: list[Line] | None = None, min_pole_atr: float = 6.0,
          max_retrace: float = 0.618) -> list[Pattern]:
    """Bull and bear flags: a trend, a pullback under a falling line (bull) or
    above a rising one (bear), and the break of that line.

    Bull: in an uptrend (the top above a rising 50-candle EMA), a rise of at
    least ``min_pole_atr`` ATR to a swing high (the pole),
    then a pullback that keeps more than 1 - ``max_retrace`` of that rise and
    makes no new high, with a falling line from the top across its lower highs
    (2+ touches, no close above it until the last ``3 * pivot`` candles). A
    close above it is the breakout; the target is the pole's height added to
    the breakout level, and the flag's low is where the setup fails. A flag
    whose breakout is more than ``6 * pivot`` candles old, or whose price is
    back under the flag's low, is dropped.
    """
    n = len(df)
    if n < 6 * pivot:
        return []
    a = float(atr(df).median())
    out: list[Pattern] = []
    poles: list[float] = []                       # pole size / price, per flag
    for bull in (True, False):
        sign = 1.0 if bull else -1.0
        hi = (df["high"] if bull else -df["low"]).to_numpy(dtype=float)
        lo = (df["low"] if bull else -df["high"]).to_numpy(dtype=float)
        cl = (sign * df["close"]).to_numpy(dtype=float)
        ema = (sign * df["close"]).ewm(span=50, adjust=False).mean().to_numpy()
        f = _flag(hi, lo, cl, ema, pivot=pivot, tol=tol, atr_=a,
                  min_pole_atr=min_pole_atr, max_retrace=max_retrace)
        if f is None:
            continue
        top, anchor, slope = f["top"], f["anchor"], f["slope"]
        p_top, p_anchor = sign * hi[top], sign * hi[anchor]
        edge = sign * lo[f["flag_i"]]              # the flag's far side (fail level)
        line = Line(RESISTANCE if bull else SUPPORT, top, anchor, p_top, p_anchor,
                    f["touches"], anchor, 0.0, f["broke"])
        flat = Line(SUPPORT if bull else RESISTANCE, f["flag_i"], f["flag_i"] + 1,
                    edge, edge, 1, f["flag_i"], 0.0)
        level_now = line.at(n - 1)
        pole = f["pole"]
        held = ""
        for sl in supports or []:
            if bull and sl.slope > 0 and abs(sl.at(f["flag_i"]) - edge) <= 2 * tol:
                held = "; the pullback held the rising trendline"
        note = (f"{'rise' if bull else 'fall'} of {pole / abs(sign * lo[f['pole_i']]) * 100:.1f}% "
                f"before it, pullback gave back {f['retrace']:.0%}{held}")
        poles.append(pole / abs(p_top))
        if bull:
            out.append(Pattern("Bull flag", "bullish",
                               "broke up" if f["broke"] else "inside",
                               upper=line, lower=flat, start=top,
                               breakout_up=level_now, target_up=level_now + pole,
                               breakout_down=edge, note=note))
        else:
            out.append(Pattern("Bear flag", "bearish",
                               "broke down" if f["broke"] else "inside",
                               upper=flat, lower=line, start=top,
                               breakout_down=level_now, target_down=level_now - pole,
                               breakout_up=edge, note=note))
    # The same candles can read both ways: the bull flag's pullback is a
    # "pole" for a bear flag. When the two overlap, the bigger move — the
    # trend a trader would read — wins.
    if len(out) == 2 and out[1].start >= out[0].start - 2 * pivot:
        out = [out[int(np.argmax(poles))]]
    return out


def analyse(df: pd.DataFrame, *, pivot: int | None = None,
            tol_atr: float = 0.3) -> ChartAnalysis:
    """Trendlines, levels, Fibonacci and patterns for the candles in ``df``."""
    df = df.dropna(subset=["high", "low", "close"])
    n = len(df)
    pivot = pivot or max(3, min(10, n // 60))
    a = float(atr(df).median())
    tol = tol_atr * a
    sup = trendlines(df, SUPPORT, pivot=pivot, tol=tol)
    res = trendlines(df, RESISTANCE, pivot=pivot, tol=tol)
    pats: list[Pattern] = []
    if sup and res:
        p = line_pattern(df, res[0], sup[0], tol)
        if p:
            pats.append(p)
    pats += double_top_bottom(df, pivot=pivot, tol=tol * 1.5)
    pats += flags(df, pivot=pivot, tol=tol, supports=sup)
    return ChartAnalysis(atr=a, tol=tol, pivot=pivot, supports=sup,
                         resistances=res, levels=levels(df, pivot=pivot, tol=tol),
                         fib=fibonacci(df), patterns=pats)


# -- order blocks ----------------------------------------------------------------
SUPPLY, DEMAND = "supply", "demand"


@dataclass
class OrderBlock:
    """The last opposite candle before an impulsive move: price often reacts
    when it comes back. Supply sits where a sharp drop started (resistance),
    demand where a sharp rally started (support)."""
    kind: str                 # supply | demand
    bottom: float
    top: float
    i: int                    # the order-block candle
    ts: pd.Timestamp
    move_pct: float           # size of the impulse away from it
    tests: int                # candles that traded back into it before any break
    broken: bool              # a later close went through it (it "flipped")
    role: str = ""            # resistance | support, relative to the last close

    @property
    def label(self) -> str:
        state = ("flipped" if self.broken else
                 "fresh" if self.tests == 0 else f"tested ×{self.tests}")
        return f"Daily {self.kind} · {state}"


def order_blocks(df: pd.DataFrame, *, impulse_atr: float = 2.0, lookahead: int = 3,
                 structure: int = 10, max_each: int = 3,
                 max_dist: float = 0.35) -> list[OrderBlock]:
    """Order blocks near the price, nearest first on each side.

    Supply: an up candle, the next candle down, and within ``lookahead``
    candles price falls ``impulse_atr`` ATR below its low AND closes under the
    lowest low of the ``structure`` candles before it (a break of structure).
    The zone is that candle's low..high. Demand is the mirror image.

    Zones more than ``max_dist`` (a fraction) from the last close are left
    out; a broken zone is kept and flagged, since price often retests it from
    the other side.
    """
    n = len(df)
    if n < structure + lookahead + 2:
        return []
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = atr(df).to_numpy()
    last = float(c[-1])
    found: list[OrderBlock] = []
    for i in range(structure, n - lookahead - 1):
        nxt = slice(i + 1, i + 1 + lookahead)
        prior_low = l[i - structure:i].min()
        prior_high = h[i - structure:i].max()
        if (c[i] >= o[i] and c[i + 1] < o[i + 1]
                and l[nxt].min() <= l[i] - impulse_atr * a[i]
                and c[nxt].min() < prior_low):
            kind, bottom, top = SUPPLY, float(l[i]), float(h[i])
            move = (l[nxt].min() / h[i] - 1) * 100
        elif (c[i] <= o[i] and c[i + 1] > o[i + 1]
                and h[nxt].max() >= h[i] + impulse_atr * a[i]
                and c[nxt].max() > prior_high):
            kind, bottom, top = DEMAND, float(l[i]), float(h[i])
            move = (h[nxt].max() / l[i] - 1) * 100
        else:
            continue
        start = i + 1 + lookahead
        through = (c[start:] > top) if kind == SUPPLY else (c[start:] < bottom)
        broken = bool(through.any())
        stop = start + (int(np.argmax(through)) if broken else n - start)
        touched = (h[start:stop] >= bottom) if kind == SUPPLY else (l[start:stop] <= top)
        found.append(OrderBlock(kind, bottom, top, i, df.index[i], float(move),
                                int(touched.sum()), broken))

    def dist(ob: OrderBlock) -> float:
        if ob.bottom <= last <= ob.top:
            return 0.0
        return min(abs(ob.bottom - last), abs(ob.top - last)) / last

    out: list[OrderBlock] = []
    for side in ("above", "below"):
        pool = [ob for ob in found if dist(ob) <= max_dist and (
            (ob.bottom > last or ob.bottom <= last <= ob.top) if side == "above"
            else ob.top < last)]
        # Nearest first; of overlapping zones keep the more recent one.
        pool.sort(key=lambda ob: (dist(ob), -ob.i))
        kept: list[OrderBlock] = []
        for ob in pool:
            if all(ob.top < k.bottom or ob.bottom > k.top for k in kept):
                # Above the price a zone resists, below it supports. Inside
                # it, an intact supply (or a broken demand) resists.
                inside = ob.bottom <= last <= ob.top
                resists = side == "above" and not inside or inside and (
                    (ob.kind == SUPPLY) != ob.broken)
                ob.role = RESISTANCE if resists else SUPPORT
                kept.append(ob)
            if len(kept) == max_each:
                break
        out += kept
    return out


# -- price action ----------------------------------------------------------------
@dataclass
class PriceAction:
    structure: str                      # uptrend | downtrend | squeeze | expanding | unclear
    notes: list[str]                    # plain sentences, most important first
    labels: list[tuple[int, float, str]]   # (bar, price, HH / LH / HL / LL)


def swing_labels(df: pd.DataFrame, pivot: int, last: int = 6) -> list[tuple[int, float, str]]:
    """The last ``last`` swing highs and lows, each marked against the one
    before it: HH / LH for highs, HL / LL for lows."""
    out: list[tuple[int, float, str]] = []
    for high in (True, False):
        s = df["high"] if high else df["low"]
        idx = swing_points(s, pivot, high=high)[-(last + 1):]
        for a, b in zip(idx[:-1], idx[1:]):
            up = s.iloc[b] > s.iloc[a]
            out.append((int(b), float(s.iloc[b]),
                        ("HH" if up else "LH") if high else ("HL" if up else "LL")))
    return sorted(out)


def price_action(df: pd.DataFrame, pivot: int | None = None) -> PriceAction:
    """Market structure, breaks of structure, the last closed candle, volume and
    momentum, in plain sentences."""
    n = len(df)
    pivot = pivot or max(3, min(10, n // 60))
    notes: list[str] = []
    his = swing_points(df["high"], pivot, high=True)
    los = swing_points(df["low"], pivot, high=False)
    close = float(df["close"].iloc[-1])

    structure = "unclear"
    if len(his) >= 2 and len(los) >= 2:
        h1, h2 = df["high"].iloc[his[-2]], df["high"].iloc[his[-1]]
        l1, l2 = df["low"].iloc[los[-2]], df["low"].iloc[los[-1]]
        # Within 0.3 ATR counts as equal: a low 0.2% under the last one is a
        # retest that held, not a lower low.
        tol = 0.3 * float(atr(df).median())

        def step(new: float, old: float) -> int:
            return 1 if new > old + tol else -1 if new < old - tol else 0

        structure, text = {
            (1, 1): ("uptrend", "Uptrend: higher highs and higher lows."),
            (1, 0): ("uptrend", "Uptrend: higher highs, and the last low held at the "
                                "one before (a retest)."),
            (0, 1): ("squeeze", "Rising lows under a flat top — pressure building "
                                "under resistance."),
            (-1, -1): ("downtrend", "Downtrend: lower highs and lower lows."),
            (0, -1): ("downtrend", "Downtrend: lower lows, and the last high stalled "
                                   "at the one before (a retest)."),
            (-1, 0): ("squeeze", "Falling highs over a flat floor — pressure building "
                                 "on support."),
            (-1, 1): ("squeeze", "Squeeze: lower highs but higher lows — price is "
                                 "coiling, a breakout is building."),
            (1, -1): ("expanding", "Expanding: higher highs but lower lows — swings "
                                   "are getting wider."),
            (0, 0): ("range", "Range: highs and lows repeating at the same levels."),
        }[(step(h2, h1), step(l2, l1))]
        notes.append(text)

    # Break of structure: a close past the last confirmed swing.
    if len(his):
        sh = float(df["high"].iloc[his[-1]])
        if close > sh:
            notes.append(f"Closed above the last swing high {sh:.6g}: bullish break "
                         "of structure.")
    if len(los):
        sl = float(df["low"].iloc[los[-1]])
        if close < sl:
            notes.append(f"Closed below the last swing low {sl:.6g}: bearish break "
                         "of structure.")
    if len(his) and len(los):
        sh = float(df["high"].iloc[his[-1]])
        sl = float(df["low"].iloc[los[-1]])
        if sl <= close <= sh:
            notes.append(f"Between the last swing low {sl:.6g} "
                         f"({(sl / close - 1) * 100:+.1f}%) and swing high {sh:.6g} "
                         f"({(sh / close - 1) * 100:+.1f}%).")

    # The last CLOSED candle: the forming one still changes.
    if n >= 2:
        c = df.iloc[-2]
        rng = float(c["high"] - c["low"])
        if rng > 0:
            body = float(abs(c["close"] - c["open"]))
            upper = float(c["high"] - max(c["open"], c["close"]))
            lower = float(min(c["open"], c["close"]) - c["low"])
            bull = c["close"] >= c["open"]
            if body >= 0.7 * rng:
                notes.append(f"Last candle: strong {'bullish' if bull else 'bearish'} "
                             "body, closed near its " + ("high." if bull else "low."))
            elif upper >= 2 * body and upper >= 0.5 * rng:
                notes.append("Last candle: long upper wick — sellers pushed price "
                             "back down.")
            elif lower >= 2 * body and lower >= 0.5 * rng:
                notes.append("Last candle: long lower wick — buyers stepped in.")
            elif body <= 0.2 * rng:
                notes.append("Last candle: small body — indecision.")

    if n >= 22 and "volume" in df:
        v = float(df["volume"].iloc[-2])
        avg = float(df["volume"].iloc[-22:-2].mean())
        if avg > 0 and v >= 1.5 * avg:
            notes.append(f"Volume on the last candle was {v / avg:.1f}x its 20-candle "
                         "average.")
        elif avg > 0 and v <= 0.6 * avg:
            notes.append("Volume is light: the last candle traded under 60% of the "
                         "20-candle average.")
    if n >= 11:
        chg = (close / float(df["close"].iloc[-11]) - 1) * 100
        notes.append(f"{chg:+.1f}% over the last 10 candles.")

    return PriceAction(structure, notes, swing_labels(df, pivot))
