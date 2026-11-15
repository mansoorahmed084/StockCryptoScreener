"""Wave & Flow Matrix.

A momentum wave and a money-flow gauge in one 0–100 pane, cross-checked
against each other:

* **Wave** — where price sits in its recent range, smoothed adaptively: fast
  when price is travelling in a straight line, slow when it is chopping, so
  trends show and noise mostly does not. A signal line trails it; the wave
  crossing its signal is a *turning point* (a strong one when it happens in
  the oversold / overbought zone).
* **Money flow** — the share of recent traded value that went through on
  rising bars, around a 50 midline. Its two thresholds are learned from how
  far flow usually travels on each side; flow beyond a threshold is one-sided.
* **Overflow** — flow beyond its threshold in a run that has already lasted
  longer than runs usually do: late money, which tends to be exhaustion.
* **Reversals** — a turning point that comes right after an activity climax
  (volume, or bar range when there is no volume) with the wave on the far
  side of 50. Major when the climax is large and the wave turned from the
  oversold / overbought zone. A higher reversal factor asks for a bigger
  climax, so fewer signals.
* **Divergences** — found at each turning point from the swing just finished
  against the one before, so they need no bars to the right and never move.
* **Confluence** — how many of wave and flow are on the same side (0, 1, 2),
  and a meter that folds the lot into one 0–100 reading.

This is an original design. It covers the same ground as multi-component
oscillator suites such as LuxAlgo's "Oscillator Matrix", whose calculations
are not published; it does not reproduce them, is not affiliated with
LuxAlgo, and will not match that product's values.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Indicator, IndicatorResult, Marker
from . import common

SIGNAL_TYPES = ("sma", "trail")
DIV_MAX_GAP = 60          # bars between the two swings of a divergence
DIV_MEMORY = 10           # bars a divergence keeps counting in the meter
CLIMAX_WINDOW = 3         # bars back a climax still backs a turning point


def adaptive_wave(df: pd.DataFrame, length: int) -> pd.Series:
    """Range position (0–100) run through an efficiency-weighted average.

    Efficiency is net move / path travelled over ``length`` bars: 1 for a
    straight line, near 0 for chop. It sets the smoothing factor between a
    2-bar and a ``4 * length``-bar average.
    """
    close = df["close"]
    raw = common.stochastic(close, df["high"], df["low"], length).to_numpy(dtype=float)
    path = close.diff().abs().rolling(length).sum()
    eff = ((close - close.shift(length)).abs() / path.replace(0, np.nan)).clip(0, 1)
    fast, slow = 2 / 3, 2 / (4 * length + 1)
    alpha = (eff.fillna(0) * (fast - slow) + slow).to_numpy(dtype=float)
    out = np.full(len(raw), np.nan)
    prev = np.nan
    for i, v in enumerate(raw):
        if np.isnan(v):
            continue
        prev = v if np.isnan(prev) else prev + alpha[i] * (v - prev)
        out[i] = prev
    return pd.Series(out, index=df.index)


def trailing_signal(wave: pd.Series, mult: float, span: int = 10) -> pd.Series:
    """A stop that ratchets behind the wave at ``mult`` average wave-steps and
    jumps to the other side when the wave goes through it."""
    w = wave.to_numpy(dtype=float)
    gap = (wave.diff().abs().ewm(span=span, adjust=False).mean() * mult).to_numpy(dtype=float)
    out = np.full(len(w), np.nan)
    stop, up = np.nan, True
    for i, v in enumerate(w):
        if np.isnan(v) or np.isnan(gap[i]):
            continue
        if np.isnan(stop):
            stop = v - gap[i]
        elif up:
            if v < stop:
                up, stop = False, v + gap[i]
            else:
                stop = max(stop, v - gap[i])
        else:
            if v > stop:
                up, stop = True, v - gap[i]
            else:
                stop = min(stop, v + gap[i])
        out[i] = min(100.0, max(0.0, stop))
    return pd.Series(out, index=wave.index)


def money_flow(df: pd.DataFrame, length: int, smooth: int) -> pd.Series:
    """Share of the last ``length`` bars' traded value that printed on rising
    bars (0–100), smoothed. Without volume, the size of the move stands in
    for it."""
    tp = common.hlc3(df)
    step = tp.diff()
    has_volume = bool((df["volume"] > 0).any())
    weight = tp * df["volume"] if has_volume else step.abs()
    up = weight.where(step > 0, 0.0).rolling(length).sum()
    down = weight.where(step < 0, 0.0).rolling(length).sum()
    total = up + down
    flow = (100 * up / total.replace(0, np.nan)).where(total.isna() | (total != 0), 50.0)
    return common.ema(flow, smooth).where(flow.notna())


def flow_thresholds(flow: pd.Series, length: int) -> tuple[pd.Series, pd.Series]:
    """Upper / lower one-sided levels: 50 plus the usual excursion on that
    side plus its usual spread, each an average that only updates while flow
    is on that side."""
    f = flow.to_numpy(dtype=float)
    a = 2 / (length + 1)
    upper, lower = np.full(len(f), np.nan), np.full(len(f), np.nan)
    mean = {1: np.nan, -1: np.nan}
    spread = {1: 0.0, -1: 0.0}
    for i, v in enumerate(f):
        if not np.isnan(v) and v != 50:
            side = 1 if v > 50 else -1
            reach = abs(v - 50)
            if np.isnan(mean[side]):
                mean[side] = reach
            else:
                spread[side] += a * (abs(reach - mean[side]) - spread[side])
                mean[side] += a * (reach - mean[side])
        upper[i] = 50 + mean[1] + spread[1]
        lower[i] = 50 - mean[-1] - spread[-1]
    return pd.Series(upper, index=flow.index), pd.Series(lower, index=flow.index)


def overflow(flow: pd.Series, upper: pd.Series, lower: pd.Series, length: int) -> pd.Series:
    """Signed excess of flow beyond its threshold, counted only once the
    current run on that side of 50 has outlasted the average finished run."""
    f, up, lo = (s.to_numpy(dtype=float) for s in (flow, upper, lower))
    out = np.zeros(len(f))
    side, run, usual = 0, 0, float(length)
    for i, v in enumerate(f):
        if np.isnan(v):
            out[i] = np.nan
            continue
        now = 1 if v > 50 else -1 if v < 50 else side
        if now != side:
            if side and run:
                usual += 0.25 * (run - usual)
            side, run = now, 0
        run += 1
        if run > usual:
            if side > 0 and v > up[i]:
                out[i] = v - up[i]
            elif side < 0 and v < lo[i]:
                out[i] = v - lo[i]
    return pd.Series(out, index=flow.index)


def swing_divergences(wave: np.ndarray, high: np.ndarray, low: np.ndarray,
                      turn_up: np.ndarray, turn_down: np.ndarray,
                      min_gap: float) -> tuple[list[int], list[int]]:
    """Divergences read at turning points. When the wave turns down, the
    up-swing that just ended is complete: its wave peak and price peak are
    compared with the previous up-swing's. Mirror for lows. Returns the bar
    positions (bullish, bearish) of the turning points that confirm one."""
    bull: list[int] = []
    bear: list[int] = []
    start = 0
    prev_top = prev_bot = None          # (bar, wave extreme, price extreme)
    for i in range(len(wave)):
        if not (turn_up[i] or turn_down[i]):
            continue
        seg = slice(start, i + 1)
        if np.isnan(wave[seg]).all():
            start = i
            continue
        if turn_down[i]:
            top = (i, float(np.nanmax(wave[seg])), float(np.nanmax(high[seg])))
            if (prev_top and i - prev_top[0] <= DIV_MAX_GAP and prev_top[1] > 50
                    and top[2] > prev_top[2] and top[1] <= prev_top[1] - min_gap):
                bear.append(i)
            prev_top = top
        else:
            bot = (i, float(np.nanmin(wave[seg])), float(np.nanmin(low[seg])))
            if (prev_bot and i - prev_bot[0] <= DIV_MAX_GAP and prev_bot[1] < 50
                    and bot[2] < prev_bot[2] and bot[1] >= prev_bot[1] + min_gap):
                bull.append(i)
            prev_bot = bot
        start = i
    return bull, bear


class WaveFlowMatrix(Indicator):
    name = "wave_flow_matrix"

    def __init__(self, wave_len: int = 7, signal_type: str = "sma", signal_len: int = 3,
                 flow_len: int = 35, flow_smooth: int = 6, reversal_factor: float = 5.0,
                 div_min_gap: float = 10.0, overbought: float = 80.0, oversold: float = 20.0):
        self.wave_len = int(wave_len)
        self.signal_type = str(signal_type).lower()
        self.signal_len = int(signal_len)
        self.flow_len = int(flow_len)
        self.flow_smooth = int(flow_smooth)
        self.reversal_factor = float(reversal_factor)
        self.div_min_gap = float(div_min_gap)
        self.overbought = float(overbought)
        self.oversold = float(oversold)
        if min(self.wave_len, self.signal_len, self.flow_len, self.flow_smooth) < 1:
            raise ValueError("lengths must be 1 or more")
        if self.signal_type not in SIGNAL_TYPES:
            raise ValueError(f"signal_type must be one of {SIGNAL_TYPES}")
        if self.reversal_factor <= 0:
            raise ValueError("reversal_factor must be above 0")

    def compute(self, df: pd.DataFrame) -> IndicatorResult:
        result = IndicatorResult()
        if df.empty or len(df) < max(self.wave_len, self.flow_len) + 5:
            return result

        wave = adaptive_wave(df, self.wave_len)
        if self.signal_type == "trail":
            signal = trailing_signal(wave, self.signal_len)
        else:
            signal = wave.rolling(self.signal_len).mean()
        flow = money_flow(df, self.flow_len, self.flow_smooth)
        upper, lower = flow_thresholds(flow, self.flow_len)
        over = overflow(flow, upper, lower, self.flow_len)

        # ---- turning points --------------------------------------------------
        above = wave > signal
        was_above = above.shift(1, fill_value=False)
        known = signal.notna() & signal.shift(1).notna()
        turn_up = (above & ~was_above & known).to_numpy()
        turn_down = (~above & was_above & known & wave.notna()).to_numpy()
        w = wave.to_numpy(dtype=float)
        # the zone the wave turned from: its extreme over the last few bars
        trough = wave.rolling(CLIMAX_WINDOW, min_periods=1).min().to_numpy()
        crest = wave.rolling(CLIMAX_WINDOW, min_periods=1).max().to_numpy()
        strong_up = turn_up & (trough <= self.oversold)
        strong_down = turn_down & (crest >= self.overbought)

        # ---- reversals: a turning point on the heels of an activity climax ---
        has_volume = bool((df["volume"] > 0).any())
        activity = df["volume"] if has_volume else common.true_range(df)
        usual = activity.rolling(self.flow_len, min_periods=self.wave_len).mean().shift(1)
        rel = (activity / usual.replace(0, np.nan)).rolling(CLIMAX_WINDOW, min_periods=1).max()
        # factor 5: activity 2x its usual level is a climax, 3x a major one
        minor = (rel >= 1 + 0.2 * self.reversal_factor).fillna(False).to_numpy()
        major = (rel >= 1 + 0.4 * self.reversal_factor).fillna(False).to_numpy()
        rev_up_major = strong_up & major
        rev_down_major = strong_down & major
        rev_up = turn_up & minor & (trough < 50) & ~rev_up_major
        rev_down = turn_down & minor & (crest > 50) & ~rev_down_major

        # ---- divergences -----------------------------------------------------
        bull, bear = swing_divergences(w, df["high"].to_numpy(dtype=float),
                                       df["low"].to_numpy(dtype=float),
                                       turn_up, turn_down, self.div_min_gap)

        # ---- confluence ------------------------------------------------------
        ready = wave.notna() & flow.notna()
        conf_up = ((wave > 50).astype(int) + (flow > 50).astype(int)).where(ready)
        conf_down = ((wave < 50).astype(int) + (flow < 50).astype(int)).where(ready)

        n = len(df)
        div = np.zeros(n)
        for b in bull:
            div[b:b + DIV_MEMORY] = 1
        for b in bear:
            div[b:b + DIV_MEMORY] = -1
        votes = pd.DataFrame({
            "cross": np.sign(wave - signal),
            "trend": np.sign(wave - 50),
            "flow": np.sign(flow - 50),
            "overflow": -np.sign(over),          # late money argues for the other side
            "div": div,
        }, index=df.index)
        cast = 3 + (votes["overflow"] != 0).astype(int) + (votes["div"] != 0).astype(int)
        meter = (50 + 50 * votes.sum(axis=1) / cast).where(ready & signal.notna())

        result.panes = {
            "wave": wave, "signal": signal, "flow": flow,
            "flow_upper": upper.where(flow.notna()), "flow_lower": lower.where(flow.notna()),
            "overflow": over, "confluence_up": conf_up, "confluence_down": conf_down,
            "meter": meter,
        }

        kinds = (
            ("turn_up", turn_up & ~strong_up, "low", "turn up"),
            ("turn_down", turn_down & ~strong_down, "high", "turn down"),
            ("turn_up_strong", strong_up, "low", "strong turn up"),
            ("turn_down_strong", strong_down, "high", "strong turn down"),
            ("rev_up", rev_up, "low", "reversal up"),
            ("rev_down", rev_down, "high", "reversal down"),
            ("rev_up_major", rev_up_major, "low", "major reversal up"),
            ("rev_down_major", rev_down_major, "high", "major reversal down"),
        )
        markers: list[Marker] = []
        for kind, mask, side, label in kinds:
            for i in np.where(mask)[0]:
                markers.append(Marker(df.index[i], kind, float(df[side].iloc[i]), label))
        for b in bull:
            markers.append(Marker(df.index[b], "bull_div", float(df["low"].iloc[b]), "bull div"))
        for b in bear:
            markers.append(Marker(df.index[b], "bear_div", float(df["high"].iloc[b]), "bear div"))
        markers.sort(key=lambda m: m.ts)
        result.markers = markers

        last = n - 1
        over_now = over.iloc[-1]
        result.signals = {
            "matrix_turn_up": bool(turn_up[last]),
            "matrix_turn_down": bool(turn_down[last]),
            "matrix_strong_turn_up": bool(strong_up[last]),
            "matrix_strong_turn_down": bool(strong_down[last]),
            "matrix_reversal_up": bool(rev_up[last] or rev_up_major[last]),
            "matrix_reversal_down": bool(rev_down[last] or rev_down_major[last]),
            "matrix_major_reversal_up": bool(rev_up_major[last]),
            "matrix_major_reversal_down": bool(rev_down_major[last]),
            "matrix_bull_div": last in bull,
            "matrix_bear_div": last in bear,
            "matrix_overflow_bull": bool(over_now > 0),
            "matrix_overflow_bear": bool(over_now < 0),
            "matrix_confluence_bull": bool(conf_up.iloc[-1] == 2),
            "matrix_confluence_bear": bool(conf_down.iloc[-1] == 2),
        }
        return result
