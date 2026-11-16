"""Price action concepts: market structure, order blocks, liquidity and gaps.

Our own version of the ideas in "price action concepts" chart tools, built on
the same rules as the tested SMC engine (freqtrade-lab/research/smc.py):

  * a swing high / low at bar i is only KNOWN at bar i + k (k bars each side)
  * a structure break is a CLOSE beyond the last known, unbroken swing
  * a break with the trend is a BOS; a break against it is a CHoCH
  * the order block is the last opposite-colour candle at or just before the
    origin of the breaking leg (the extreme the leg started from)
  * the origin "swept" when its candle wicked through the swing before it and
    closed back inside -- a liquidity grab before the break

Liquidity is every swing high (buy-side: stops sit above it) and swing low
(sell-side: stops sit below it) that price has not yet taken. Each level
carries the volume traded around the swing and its share of the volume of all
levels shown. A wick through a level that closes back is a grab; a close
through it is a break.

Everything here works on CLOSED candles. Pass the forming candle and it is
dropped, so nothing repaints.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

BULL, BEAR = 1, -1


# ------------------------------------------------------------------ results
@dataclass
class Break:
    i: int                  # bar whose close broke the level
    side: int               # +1 broke a high, -1 broke a low
    kind: str               # "BOS" or "CHoCH"
    level: float            # the swing price that was broken
    level_i: int            # bar of that swing
    origin_i: int           # bar the breaking leg started from
    swept: bool             # the origin candle grabbed the swing before it
    scope: str              # "internal" or "swing"


@dataclass
class OrderBlock:
    side: int               # +1 demand (below price), -1 supply
    top: float
    bottom: float
    i: int                  # the order-block candle
    formed_i: int           # the break that confirmed it
    volume: float
    scope: str
    mitigated_i: int = -1   # first close through the far side, -1 = still live
    share: float = 0.0      # share of the volume of the blocks shown


@dataclass
class Liquidity:
    side: int               # +1 buy-side (above a swing high), -1 sell-side
    price: float
    i: int                  # the swing bar
    volume: float           # volume traded on the swing bar and k bars each side
    status: str = "open"    # "open", "grabbed" or "broken"
    end_i: int = -1         # bar that took it, -1 = still open
    share: float = 0.0      # share of the volume of the open levels shown


@dataclass
class Equal:
    side: int               # +1 equal highs, -1 equal lows
    price: float
    i0: int
    i1: int


@dataclass
class Gap:
    side: int               # +1 bullish fair value gap, -1 bearish
    top: float
    bottom: float
    i: int                  # middle candle of the three
    filled_i: int = -1


@dataclass
class Setup:
    i: int                  # the break bar; a trade would enter next open
    side: int
    stop: float             # the origin extreme
    level: float


@dataclass
class Concepts:
    n: int                                   # closed candles analysed
    internal: list[Break] = field(default_factory=list)
    swing: list[Break] = field(default_factory=list)
    trend_internal: int = 0
    trend_swing: int = 0
    order_blocks: list[OrderBlock] = field(default_factory=list)
    liquidity: list[Liquidity] = field(default_factory=list)
    equals: list[Equal] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    htf_trend: int = 0
    htf_levels: dict[str, float] = field(default_factory=dict)
    setups: list[Setup] = field(default_factory=list)


# --------------------------------------------------------------- primitives
def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    """Wilder ATR, NaN until there are n bars."""
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    tr = np.empty(len(c))
    tr[0] = h[0] - l[0]
    for i in range(1, len(c)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    a = tr[:n].mean()
    out[n - 1] = a
    for i in range(n, len(c)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def pivots(h: np.ndarray, l: np.ndarray, k: int) -> tuple[list, list]:
    """Swing highs and lows as (bar, price), same rule as smc._pivots.

    A high must beat the k bars before it strictly and not be beaten by the
    k bars after it; it becomes known at bar + k.
    """
    highs, lows = [], []
    for i in range(k, len(h) - k):
        if all(h[j] < h[i] for j in range(i - k, i)) and \
                all(h[j] <= h[i] for j in range(i + 1, i + k + 1)):
            highs.append((i, float(h[i])))
        if all(l[j] > l[i] for j in range(i - k, i)) and \
                all(l[j] >= l[i] for j in range(i + 1, i + k + 1)):
            lows.append((i, float(l[i])))
    return highs, lows


def structure(o, h, l, c, v, k: int, scope: str) -> tuple[list[Break], list[OrderBlock], np.ndarray]:
    """Breaks of structure, their order blocks, and the trend after each bar.

    Mirrors smc._structure: the live swing is the latest known pivot; a close
    beyond it breaks structure and clears it until a new pivot is known.
    """
    n = len(c)
    highs, lows = pivots(h, l, k)
    known_h = {i + k: (i, p) for i, p in highs}
    known_l = {i + k: (i, p) for i, p in lows}
    trend = np.zeros(n, np.int8)
    breaks: list[Break] = []
    obs: list[OrderBlock] = []
    sh = sl = None                          # live (bar, price)
    last_sh = np.full(n, np.nan)            # latest known swing, broken or not
    last_sl = np.full(n, np.nan)
    ref_h = ref_l = np.nan
    cur = 0
    for t in range(n):
        if t in known_h:
            sh = known_h[t]
            ref_h = sh[1]
        if t in known_l:
            sl = known_l[t]
            ref_l = sl[1]
        last_sh[t], last_sl[t] = ref_h, ref_l
        if sh is not None and c[t] > sh[1]:
            k0 = sh[0] + int(np.argmin(l[sh[0]:t + 1]))          # leg origin
            b = next((j for j in range(k0, max(k0 - 6, -1), -1) if c[j] < o[j]), k0)
            ref = last_sl[k0 - 1] if k0 > 0 else np.nan
            swept = bool(np.isfinite(ref) and l[k0] < ref and c[k0] > ref)
            breaks.append(Break(t, BULL, "BOS" if cur == BULL else "CHoCH",
                                sh[1], sh[0], k0, swept, scope))
            obs.append(OrderBlock(BULL, float(h[b]), float(l[b]), b, t, float(v[b]), scope))
            cur, sh = BULL, None
        elif sl is not None and c[t] < sl[1]:
            k0 = sl[0] + int(np.argmax(h[sl[0]:t + 1]))
            b = next((j for j in range(k0, max(k0 - 6, -1), -1) if c[j] > o[j]), k0)
            ref = last_sh[k0 - 1] if k0 > 0 else np.nan
            swept = bool(np.isfinite(ref) and h[k0] > ref and c[k0] < ref)
            breaks.append(Break(t, BEAR, "BOS" if cur == BEAR else "CHoCH",
                                sl[1], sl[0], k0, swept, scope))
            obs.append(OrderBlock(BEAR, float(h[b]), float(l[b]), b, t, float(v[b]), scope))
            cur, sl = BEAR, None
        trend[t] = cur
    for ob in obs:                          # mitigation: a close through the far side
        for t in range(ob.formed_i + 1, n):
            if (ob.side == BULL and c[t] < ob.bottom) or (ob.side == BEAR and c[t] > ob.top):
                ob.mitigated_i = t
                break
    return breaks, obs, trend


def liquidity(h, l, c, v, k: int) -> list[Liquidity]:
    """Every swing high / low and what happened to it afterwards."""
    n = len(c)
    highs, lows = pivots(h, l, k)
    out = []
    for side, pts in ((BULL, highs), (BEAR, lows)):
        for i, p in pts:
            lq = Liquidity(side, p, i, float(v[max(0, i - k):i + k + 1].sum()))
            for t in range(i + k + 1, n):
                hit = h[t] > p if side == BULL else l[t] < p
                if hit:
                    closed_back = c[t] <= p if side == BULL else c[t] >= p
                    lq.status = "grabbed" if closed_back else "broken"
                    lq.end_i = t
                    break
            out.append(lq)
    return out


def equal_levels(liq: list[Liquidity], a: np.ndarray, tol: float = 0.1) -> list[Equal]:
    """Two neighbouring open swings within `tol` ATR of each other."""
    out = []
    for side in (BULL, BEAR):
        pts = sorted((x for x in liq if x.side == side), key=lambda x: x.i)
        for x, y in zip(pts, pts[1:]):
            if x.status != "open" or y.status != "open":
                continue
            ref = a[y.i] if np.isfinite(a[y.i]) else np.nanmean(a)
            if np.isfinite(ref) and abs(x.price - y.price) <= tol * ref:
                out.append(Equal(side, (x.price + y.price) / 2, x.i, y.i))
    return out


def fair_value_gaps(h, l, c, a: np.ndarray, min_atr: float = 0.2) -> list[Gap]:
    """Three-candle gaps at least `min_atr` ATR tall, filled when price trades
    back through the whole gap."""
    out = []
    n = len(c)
    for j in range(2, n):
        ref = a[j] if np.isfinite(a[j]) else 0.0
        if l[j] > h[j - 2] and l[j] - h[j - 2] >= min_atr * ref:
            g = Gap(BULL, float(l[j]), float(h[j - 2]), j - 1)
        elif h[j] < l[j - 2] and l[j - 2] - h[j] >= min_atr * ref:
            g = Gap(BEAR, float(l[j - 2]), float(h[j]), j - 1)
        else:
            continue
        for t in range(j + 1, n):
            if (g.side == BULL and l[t] <= g.bottom) or (g.side == BEAR and h[t] >= g.top):
                g.filled_i = t
                break
        out.append(g)
    return out


def htf_trend_on(ltf_index: pd.DatetimeIndex, ltf_step: pd.Timedelta,
                 daily: pd.DataFrame, k: int = 2) -> np.ndarray:
    """Daily structure trend on every LTF bar, using only daily candles that
    had CLOSED when that LTF bar closed (as smc.htf_map does)."""
    if daily is None or len(daily) < 2 * k + 3:
        return np.zeros(len(ltf_index), np.int8)
    o, h, l, c, v = _arrays(daily)
    _, _, tr = structure(o, h, l, c, v, k, "daily")
    d_close = (daily.index + pd.Timedelta("1D")).to_numpy()
    l_close = (ltf_index + ltf_step).to_numpy()
    pos = np.searchsorted(d_close, l_close, side="right") - 1
    return np.where(pos >= 0, tr[np.maximum(pos, 0)], 0).astype(np.int8)


def daily_levels(daily: pd.DataFrame, now: pd.Timestamp) -> dict[str, float]:
    """Previous day and previous week high / low: the obvious liquidity pools."""
    if daily is None or daily.empty:
        return {}
    closed = daily[daily.index + pd.Timedelta("1D") <= now]
    if closed.empty:
        return {}
    out = {"PDH": float(closed["high"].iloc[-1]), "PDL": float(closed["low"].iloc[-1])}
    week_start = (now.normalize() - pd.Timedelta(days=now.weekday()))
    prev = closed[(closed.index >= week_start - pd.Timedelta(days=7))
                  & (closed.index < week_start)]
    if not prev.empty:
        out["PWH"] = float(prev["high"].max())
        out["PWL"] = float(prev["low"].min())
    return out


# ------------------------------------------------------------------ driver
def _arrays(df: pd.DataFrame):
    o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
    if "quote_volume" in df:
        v = df["quote_volume"].to_numpy(dtype=float)
    else:
        v = df["volume"].to_numpy(dtype=float) * c
    return o, h, l, c, v


def analyse(df: pd.DataFrame, *, k_internal: int = 3, k_swing: int = 10,
            k_liq: int = 5, k_setup: int = 5, daily: pd.DataFrame | None = None,
            ltf_step: pd.Timedelta | None = None, drop_last: bool = True,
            max_obs: int = 3, max_liq: int = 5, max_gaps: int = 4) -> Concepts:
    """Run every concept on one chart.

    `daily` adds the daily trend, previous day / week levels and the
    sweep-break style setups (a break whose origin swept liquidity, in the
    direction of the daily trend). `drop_last` removes the forming candle.
    """
    closed = df.iloc[:-1] if drop_last and len(df) > 1 else df
    n = len(closed)
    out = Concepts(n=n)
    if n < 2 * max(k_internal, k_swing, k_liq) + 3:
        return out
    o, h, l, c, v = _arrays(closed)
    a = atr(h, l, c)

    out.internal, obs_i, tr_i = structure(o, h, l, c, v, k_internal, "internal")
    out.swing, obs_s, tr_s = structure(o, h, l, c, v, k_swing, "swing")
    out.trend_internal, out.trend_swing = int(tr_i[-1]), int(tr_s[-1])

    # The latest live blocks on each side, swing ones first; shares of volume.
    keep = []
    for side in (BULL, BEAR):
        live = [ob for ob in obs_s + obs_i if ob.side == side and ob.mitigated_i < 0]
        live.sort(key=lambda ob: (ob.scope != "swing", -ob.formed_i))
        seen = set()
        for ob in live:
            if ob.i in seen:
                continue
            seen.add(ob.i)
            keep.append(ob)
            if sum(1 for x in keep if x.side == side) >= max_obs:
                break
    tot = sum(ob.volume for ob in keep) or 1.0
    for ob in keep:
        ob.share = ob.volume / tot
    out.order_blocks = keep

    liq = liquidity(h, l, c, v, k_liq)
    out.equals = equal_levels(liq, a)
    shown = []
    for side in (BULL, BEAR):
        open_ = sorted((x for x in liq if x.side == side and x.status == "open"),
                       key=lambda x: -x.i)[:max_liq]
        taken = sorted((x for x in liq if x.side == side and x.status != "open"),
                       key=lambda x: -x.end_i)[:max_liq]
        shown += open_ + taken
    tot = sum(x.volume for x in shown if x.status == "open") or 1.0
    for x in shown:
        x.share = x.volume / tot if x.status == "open" else 0.0
    out.liquidity = shown

    gaps = [g for g in fair_value_gaps(h, l, c, a) if g.filled_i < 0]
    out.gaps = sorted(gaps, key=lambda g: -g.i)[:max_gaps]

    if daily is not None and ltf_step is not None:
        ht = htf_trend_on(closed.index, ltf_step, daily)
        out.htf_trend = int(ht[-1])
        out.htf_levels = daily_levels(daily, closed.index[-1] + ltf_step)
        if k_setup == k_internal:
            setup_breaks = out.internal
        elif k_setup == k_swing:
            setup_breaks = out.swing
        else:
            setup_breaks, _, _ = structure(o, h, l, c, v, k_setup, "setup")
        for b in setup_breaks:
            if b.swept and ht[b.i] == b.side:
                stop = float(l[b.origin_i] if b.side == BULL else h[b.origin_i])
                out.setups.append(Setup(b.i, b.side, stop, b.level))
    return out


def notes(cx: Concepts, last: float) -> list[str]:
    """Plain-language summary for the page."""
    word = {BULL: "up", BEAR: "down", 0: "not set yet"}
    out = [f"Swing trend: **{word[cx.trend_swing]}**. "
           f"Internal trend: **{word[cx.trend_internal]}**."]
    if cx.htf_levels or cx.htf_trend:
        out.append(f"Daily trend: **{word[cx.htf_trend]}**.")
    for name, lst in (("swing", cx.swing), ("internal", cx.internal)):
        if lst:
            b = lst[-1]
            out.append(f"Last {name} break: **{'bullish' if b.side == BULL else 'bearish'} "
                       f"{b.kind}** through {b.level:,.6g}"
                       + (" after a liquidity grab." if b.swept else "."))
    above = [x for x in cx.liquidity if x.status == "open" and x.price > last]
    below = [x for x in cx.liquidity if x.status == "open" and x.price < last]
    if above:
        x = min(above, key=lambda x: x.price)
        out.append(f"Nearest buy-side liquidity: **{x.price:,.6g}** "
                   f"({(x.price / last - 1) * 100:+.2f}%).")
    if below:
        x = max(below, key=lambda x: x.price)
        out.append(f"Nearest sell-side liquidity: **{x.price:,.6g}** "
                   f"({(x.price / last - 1) * 100:+.2f}%).")
    return out


# ---------------------------------------------------------------- CRT
# Candle Range Theory: the previous higher-timeframe candle's high and low are
# the range. Inside the next HTF candle, a wick beyond one side is the
# "manipulation" (a liquidity grab). The setup is confirmed only when a fair
# value gap or a market structure shift back the other way follows, still
# inside that HTF candle. Entry at the confirming close, stop beyond the sweep
# extreme, target the opposite side of the range.
CRT_HTF = {"15m": "4h", "1h": "1D", "4h": "W-MON", "1d": "MS"}
CRT_NAME = {"1h": "1h", "4h": "4h", "1D": "daily", "W-MON": "weekly", "MS": "monthly"}


@dataclass
class CRTRange:
    start_i: int            # first LTF bar of the HTF candle the range applies to
    end_i: int              # last LTF bar of it
    high: float             # previous HTF candle's high / low
    low: float


@dataclass
class CRTSetup:
    side: int               # +1 long (swept the low), -1 short (swept the high)
    range_i: int            # index into CRT.ranges
    sweep_i: int            # first LTF bar beyond the level
    extreme_i: int          # bar of the sweep extreme at confirmation
    extreme: float
    confirm_i: int = -1     # -1 = swept, not (yet) confirmed
    trigger: str = ""       # "FVG" or "MSS"
    entry: float = np.nan
    stop: float = np.nan
    target: float = np.nan
    outcome: str = ""       # "won", "lost", "open"; "" when unconfirmed
    exit_i: int = -1

    @property
    def rr(self) -> float:
        risk = abs(self.entry - self.stop)
        return abs(self.target - self.entry) / risk if risk > 0 else np.nan


@dataclass
class CRT:
    htf: str
    ranges: list[CRTRange] = field(default_factory=list)
    setups: list[CRTSetup] = field(default_factory=list)

    def stats(self) -> dict:
        done = [s for s in self.setups if s.outcome in ("won", "lost")]
        won = [s for s in done if s.outcome == "won"]
        r = [s.rr if s.outcome == "won" else -1.0 for s in done]
        return {"swept": len(self.setups),
                "confirmed": sum(1 for s in self.setups if s.confirm_i >= 0),
                "won": len(won), "lost": len(done) - len(won),
                "open": sum(1 for s in self.setups if s.outcome == "open"),
                "expired": sum(1 for s in self.setups if s.outcome == "expired"),
                "win_rate": len(won) / len(done) if done else np.nan,
                "avg_r": float(np.mean(r)) if r else np.nan}


def crt(df: pd.DataFrame, htf: str, *, k_mss: int = 2, min_rr: float = 1.0,
        hold_htf: int = 2) -> CRT:
    """CRT sweeps and confirmed setups on CLOSED LTF candles `df`.

    `htf` is a pandas rule ("1h", "4h", "1D", "W-MON"). HTF candles are built
    from `df`, so the first (likely partial) one is never used as a range.
    A confirmed setup is managed for `hold_htf` HTF candles after the one it
    formed in: stop tested before target on every bar (pessimistic).
    """
    out = CRT(htf)
    if len(df) < 10:
        return out
    o, h, l, c, _ = _arrays(df)
    n = len(c)
    starts = df["close"].resample(htf, label="left", closed="left").first().dropna().index
    bin_of = np.searchsorted(starts.to_numpy(), df.index.to_numpy(), side="right") - 1
    highs, lows = pivots(h, l, k_mss)
    known_h = sorted((i + k_mss, i, p) for i, p in highs)
    known_l = sorted((i + k_mss, i, p) for i, p in lows)

    def last_pivot(known, before_i, at_t):
        """Latest swing with bar < before_i that is known by bar at_t."""
        best = None
        for kt, i, p in known:
            if kt > at_t:
                break
            if i < before_i:
                best = (i, p)
        return best

    bins = [np.flatnonzero(bin_of == j) for j in range(len(starts))]
    for j in range(2, len(starts)):
        prev, cur = bins[j - 1], bins[j]
        if len(prev) == 0 or len(cur) == 0:
            continue
        hi, lo = float(h[prev].max()), float(l[prev].min())
        out.ranges.append(CRTRange(int(cur[0]), int(cur[-1]), hi, lo))
        ri = len(out.ranges) - 1
        for side in (BEAR, BULL):
            level = hi if side == BEAR else lo
            s = None
            for t in cur:
                beyond = h[t] > level if side == BEAR else l[t] < level
                if s is None:
                    if beyond:
                        s = CRTSetup(side, ri, int(t), int(t), float(h[t] if side == BEAR else l[t]))
                    continue
                if beyond and ((side == BEAR and h[t] > s.extreme) or
                               (side == BULL and l[t] < s.extreme)):
                    s.extreme, s.extreme_i = float(h[t] if side == BEAR else l[t]), int(t)
                inside = c[t] < level if side == BEAR else c[t] > level
                if not inside:
                    continue
                trig = ""
                if t - 2 >= s.sweep_i:          # a gap formed after the sweep began
                    if side == BEAR and h[t] < l[t - 2]:
                        trig = "FVG"
                    elif side == BULL and l[t] > h[t - 2]:
                        trig = "FVG"
                if not trig:
                    piv = last_pivot(known_l if side == BEAR else known_h, s.extreme_i, t)
                    if piv and ((side == BEAR and c[t] < piv[1]) or
                                (side == BULL and c[t] > piv[1])):
                        trig = "MSS"
                if not trig:
                    continue
                entry, stop = float(c[t]), s.extreme
                target = lo if side == BEAR else hi
                s.confirm_i, s.trigger, s.entry, s.stop, s.target = int(t), trig, entry, stop, target
                break
            if s is None:
                continue
            if s.confirm_i >= 0 and not (s.rr >= min_rr):
                s.confirm_i, s.trigger = -1, ""             # too little room to target
                s.entry = s.stop = s.target = np.nan
            if s.confirm_i >= 0:
                last = bins[min(j + hold_htf, len(bins) - 1)]
                stop_at = int(last[-1]) if len(last) else n - 1
                s.outcome = "open"
                for t in range(s.confirm_i + 1, min(stop_at, n - 1) + 1):
                    if (side == BEAR and h[t] >= s.stop) or (side == BULL and l[t] <= s.stop):
                        s.outcome, s.exit_i = "lost", t
                        break
                    if (side == BEAR and l[t] <= s.target) or (side == BULL and h[t] >= s.target):
                        s.outcome, s.exit_i = "won", t
                        break
                else:
                    if j + hold_htf < len(bins) - 1:
                        s.outcome, s.exit_i = "expired", stop_at
            out.setups.append(s)
    return out
