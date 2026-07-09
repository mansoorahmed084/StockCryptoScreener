"""Signal construction for the RS + VMC-divergence strategy research.

Everything is positional on the coin's 1h frame. The cardinal rule is
*knowability*: a VMC divergence pivot is only confirmed ``PIVOT_RIGHT`` candles
after the pivot; a 4h/1d state is only known at that bucket's close; the engine
then enters at the NEXT 1h open. All mappings below encode that explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.config import Config
from backend.data.frames import resample_ohlcv
from backend.indicators.vumanchu import VuManChuCipherB
from backend.screener import rs

PIVOT_RIGHT = 3  # matches VuManChuCipherB(pivot_lookback=3)


@dataclass
class DivEvent:
    i_conf: int        # 1h bar position at whose CLOSE the divergence is knowable
    pivot_low: float   # low of the divergence pivot candle (stop anchor)
    tf: str
    wt2_pivot: float = float("nan")   # divergence-TF WT2 at the pivot (oversold depth)


@dataclass
class Prep:
    coin: str
    df: pd.DataFrame                 # 1h OHLCV
    atr: np.ndarray                  # ATR(14) on 1h
    wt_up: np.ndarray                # WT1 crossed above WT2 at this 1h close
    wt_dn: np.ndarray
    wt2: np.ndarray
    div1h: list[DivEvent] = field(default_factory=list)
    div4h: list[DivEvent] = field(default_factory=list)
    div4h_active: np.ndarray | None = None   # 4h bull div within last N buckets
    rs1d: np.ndarray | None = None           # RS-vs-BTC 1d direction per 1h bar
    rs4h: np.ndarray | None = None
    btc1d: np.ndarray | None = None          # BTC/USDT 1d direction per 1h bar
    alt1d: np.ndarray | None = None          # the alt's own USDT 1d direction
    wt2_4h: np.ndarray | None = None         # last CLOSED 4h bucket's WT2 per 1h bar
    wt2_4h_rising: np.ndarray | None = None  # 1.0 where that bucket's WT2 rose
    mfi_4h: np.ndarray | None = None         # last closed 4h bucket's money flow
    alt4h: np.ndarray | None = None          # the alt's own 4h trend direction
    ema200: np.ndarray | None = None         # EMA200 of 1h closes


def _atr(df: pd.DataFrame, length: int = 14) -> np.ndarray:
    prev_c = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev_c).abs(),
                    (df["low"] - prev_c).abs()], axis=1).max(axis=1)
    return tr.rolling(length, min_periods=length).mean().to_numpy()


def _known_at_positions(idx_1h: pd.DatetimeIndex,
                        known_times: pd.DatetimeIndex) -> np.ndarray:
    """For each known-at wall-clock time, the 1h bar position at whose close the
    information is first available (bar labeled T-1h closes exactly at T)."""
    return idx_1h.searchsorted(known_times, side="left") - 1


def _numeric_per_bar(idx_1h: pd.DatetimeIndex, labels: pd.DatetimeIndex,
                     values: np.ndarray, bucket: pd.Timedelta) -> np.ndarray:
    """Map a coarse-TF numeric series onto 1h bars honouring knowability."""
    known_from = labels + bucket
    out = np.full(len(idx_1h), np.nan)
    pos = idx_1h.searchsorted(known_from, side="left")
    for p, v in zip(pos, values):
        if p < len(idx_1h):
            out[p:] = v
    return out


def _state_per_bar(idx_1h: pd.DatetimeIndex, labels: pd.DatetimeIndex,
                   directions: np.ndarray, bucket: pd.Timedelta) -> np.ndarray:
    """Map a coarse-TF direction series onto 1h bars, honouring knowability:
    a bucket's state applies to 1h bars labeled >= bucket_label + bucket."""
    known_from = labels + bucket
    out = np.full(len(idx_1h), "unknown", dtype=object)
    pos = idx_1h.searchsorted(known_from, side="left")
    for p, d in zip(pos, directions):
        if p < len(idx_1h):
            out[p:] = d  # overwritten by later buckets
    return out


def _div_events(df: pd.DataFrame, idx_1h: pd.DatetimeIndex, tf: str,
                bucket: pd.Timedelta | None) -> list[DivEvent]:
    """Confirmed VMC bull-divergence events, expressed as 1h bar positions."""
    res = VuManChuCipherB().compute(df)
    wt2 = res.panes.get("wt2")
    events: list[DivEvent] = []
    for m in res.markers:
        if m.kind != "bull_div":
            continue
        p = df.index.get_loc(m.ts)
        p_conf = p + PIVOT_RIGHT
        if p_conf >= len(df):
            continue  # not confirmed within the data
        pivot_low = float(df["low"].iloc[p])
        wt2_pivot = float(wt2.iloc[p]) if wt2 is not None else float("nan")
        if bucket is None:                      # native 1h
            i_conf = p_conf
        else:                                   # coarse TF -> knowable at bucket close
            known_time = df.index[p_conf] + bucket
            i_conf = int(idx_1h.searchsorted(known_time, side="left")) - 1
        if 0 <= i_conf < len(idx_1h):
            events.append(DivEvent(i_conf=int(i_conf), pivot_low=pivot_low,
                                   tf=tf, wt2_pivot=wt2_pivot))
    return events


def _active_mask(n: int, events: list[DivEvent], active_bars: int) -> np.ndarray:
    mask = np.zeros(n, dtype=bool)
    for ev in events:
        mask[ev.i_conf: min(n, ev.i_conf + active_bars)] = True
    return mask


def prepare(coin: str, df1h: pd.DataFrame, btc1h: pd.DataFrame,
            config: Config, *, div4h_active_buckets: int = 12) -> Prep:
    idx = df1h.index
    df4h = resample_ohlcv(df1h, "4h")
    df1d = resample_ohlcv(df1h, "1d")

    vmc = VuManChuCipherB().compute(df1h)
    wt1 = vmc.panes["wt1"].to_numpy()
    wt2 = vmc.panes["wt2"].to_numpy()
    wt_up = np.zeros(len(idx), dtype=bool)
    wt_dn = np.zeros(len(idx), dtype=bool)
    wt_up[1:] = (wt1[:-1] <= wt2[:-1]) & (wt1[1:] > wt2[1:])
    wt_dn[1:] = (wt1[:-1] >= wt2[:-1]) & (wt1[1:] < wt2[1:])

    prep = Prep(coin=coin, df=df1h, atr=_atr(df1h), wt_up=wt_up, wt_dn=wt_dn,
                wt2=wt2)
    prep.div1h = _div_events(df1h, idx, "1h", None)
    prep.div4h = _div_events(df4h, idx, "4h", pd.Timedelta("4h"))
    prep.div4h_active = _active_mask(len(idx), prep.div4h,
                                     div4h_active_buckets * 4)

    vmc4h = VuManChuCipherB().compute(df4h)
    wt2_4h_series = vmc4h.panes["wt2"]
    prep.wt2_4h = _numeric_per_bar(idx, df4h.index, wt2_4h_series.to_numpy(),
                                   pd.Timedelta("4h"))
    prep.wt2_4h_rising = _numeric_per_bar(
        idx, df4h.index, (wt2_4h_series.diff() > 0).astype(float).to_numpy(),
        pd.Timedelta("4h"))
    prep.mfi_4h = _numeric_per_bar(idx, df4h.index,
                                   vmc4h.panes["mfi"].to_numpy(),
                                   pd.Timedelta("4h"))
    alt4h_hist = rs.classify_history(df4h["close"],
                                     config.classifier_params("4h"),
                                     drop_forming=False)
    prep.alt4h = _state_per_bar(idx, alt4h_hist.index,
                                alt4h_hist["direction"].to_numpy(),
                                pd.Timedelta("4h"))
    prep.ema200 = df1h["close"].ewm(span=200, adjust=False).mean().to_numpy()

    # RS vs BTC states (previous closed bucket only)
    btc_1d = resample_ohlcv(btc1h, "1d")
    btc_4h = resample_ohlcv(btc1h, "4h")
    for tf, alt_c, btc_c, attr in (
            ("1d", df1d["close"], btc_1d["close"], "rs1d"),
            ("4h", df4h["close"], btc_4h["close"], "rs4h")):
        common = alt_c.index.intersection(btc_c.index)
        ratio = (alt_c.loc[common] / btc_c.loc[common]).dropna()
        hist = rs.classify_history(ratio, config.classifier_params(tf),
                                   drop_forming=False)
        setattr(prep, attr, _state_per_bar(
            idx, hist.index, hist["direction"].to_numpy(),
            pd.Timedelta("1d") if tf == "1d" else pd.Timedelta("4h")))

    btc_hist = rs.classify_history(btc_1d["close"],
                                   config.classifier_params("1d"),
                                   drop_forming=False)
    prep.btc1d = _state_per_bar(idx, btc_hist.index,
                                btc_hist["direction"].to_numpy(),
                                pd.Timedelta("1d"))
    alt_hist = rs.classify_history(df1d["close"],
                                   config.classifier_params("1d"),
                                   drop_forming=False)
    prep.alt1d = _state_per_bar(idx, alt_hist.index,
                                alt_hist["direction"].to_numpy(),
                                pd.Timedelta("1d"))
    return prep


def invert_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Price inversion: a SHORT on X is a LONG on 1/X (high/low swap roles).

    Lets the entire long-only pipeline (divergences, oversold, gates, engine)
    price the short side unchanged. R-multiples are log-symmetric to true
    shorts up to a small convexity term; funding is not modelled.
    """
    return pd.DataFrame({
        "open": 1.0 / df["open"], "high": 1.0 / df["low"],
        "low": 1.0 / df["high"], "close": 1.0 / df["close"],
        "volume": df["volume"],
    }, index=df.index)


def prepare_daily(coin: str, df1d: pd.DataFrame, btc1d: pd.DataFrame,
                  config: Config, *, divw_active_weeks: int = 4) -> Prep:
    """Daily-native prep. Field mapping (Prep was named for the 1h path):

    df = 1d bars · div1h = DAILY div events · div4h = WEEKLY div events ·
    wt2_4h = weekly WT2 per day · rs1d = RS-vs-BTC on 1d · rs4h = RS-vs-BTC on
    1w · btc1d/alt1d = 1d regimes. Same-frame states align positionally (a bar's
    state is knowable at its own close); weekly states shift to the week close.
    """
    idx = df1d.index
    df1w = resample_ohlcv(df1d, "1w")

    vmc = VuManChuCipherB().compute(df1d)
    wt1 = vmc.panes["wt1"].to_numpy()
    wt2 = vmc.panes["wt2"].to_numpy()
    wt_up = np.zeros(len(idx), dtype=bool)
    wt_dn = np.zeros(len(idx), dtype=bool)
    wt_up[1:] = (wt1[:-1] <= wt2[:-1]) & (wt1[1:] > wt2[1:])
    wt_dn[1:] = (wt1[:-1] >= wt2[:-1]) & (wt1[1:] < wt2[1:])

    prep = Prep(coin=coin, df=df1d, atr=_atr(df1d), wt_up=wt_up, wt_dn=wt_dn,
                wt2=wt2)
    prep.div1h = _div_events(df1d, idx, "1d", None)
    prep.div4h = _div_events(df1w, idx, "1w", pd.Timedelta("7d"))
    prep.div4h_active = _active_mask(len(idx), prep.div4h,
                                     divw_active_weeks * 7)
    vmc1w = VuManChuCipherB().compute(df1w)
    prep.wt2_4h = _numeric_per_bar(idx, df1w.index,
                                   vmc1w.panes["wt2"].to_numpy(),
                                   pd.Timedelta("7d"))

    common = df1d.index.intersection(btc1d.index)
    ratio_1d = (df1d["close"].loc[common] / btc1d["close"].loc[common]).dropna()
    hist_1d = rs.classify_history(ratio_1d, config.classifier_params("1d"),
                                  drop_forming=False)
    prep.rs1d = (hist_1d["direction"].reindex(idx, method="ffill")
                 .fillna("unknown").to_numpy())

    ratio_1w = ratio_1d.resample("W-MON", label="left", closed="left").last().dropna()
    hist_1w = rs.classify_history(ratio_1w, config.classifier_params("1w"),
                                  drop_forming=False)
    prep.rs4h = _state_per_bar(idx, hist_1w.index,
                               hist_1w["direction"].to_numpy(),
                               pd.Timedelta("7d"))

    btc_hist = rs.classify_history(btc1d["close"],
                                   config.classifier_params("1d"),
                                   drop_forming=False)
    prep.btc1d = (btc_hist["direction"].reindex(idx, method="ffill")
                  .fillna("unknown").to_numpy())
    alt_hist = rs.classify_history(df1d["close"],
                                   config.classifier_params("1d"),
                                   drop_forming=False)
    prep.alt1d = alt_hist["direction"].to_numpy()
    return prep


def gen_signals(prep: Prep, p: dict) -> list:
    """Turn prepared state + a parameter dict into engine Signals."""
    from .engine import Signal

    closes = prep.df["close"].to_numpy()
    n = len(closes)
    events = prep.div1h if p.get("div_tf", "1h") == "1h" else prep.div4h
    sigs: list[Signal] = []
    for ev in events:
        i = ev.i_conf
        if i >= n - 1:
            continue
        # ---- filters, all evaluated with information known at bar i close ----
        rs_f = p.get("rs_filter")
        if rs_f == "1d" and prep.rs1d[i] != rs.BULL:
            continue
        if rs_f == "4h" and prep.rs4h[i] != rs.BULL:
            continue
        if p.get("btc_regime") == "not_bear_1d" and prep.btc1d[i] == rs.BEAR:
            continue
        if p.get("alt_regime") == "not_bear_1d" and prep.alt1d[i] == rs.BEAR:
            continue
        if p.get("multi_tf_div") and not prep.div4h_active[i]:
            continue
        # oversold depth measured on the divergence TF at the PIVOT itself
        if p.get("oversold_only") and not (
                ev.wt2_pivot <= p.get("oversold_level", 0)):
            continue
        # higher-TF stretch: last CLOSED 4h bucket's WT2 must also be oversold
        if p.get("htf_oversold") is not None and not (
                prep.wt2_4h[i] <= p["htf_oversold"]):
            continue
        # ---- optional confirmation: WT cross-up within k bars ----
        i_sig = i
        if p.get("confirm") == "wt_cross":
            k = p.get("confirm_within", 6)
            hits = [j for j in range(i, min(n - 1, i + k + 1)) if prep.wt_up[j]]
            if not hits:
                continue
            i_sig = hits[0]
        # ---- stop ----
        atr = prep.atr[i_sig]
        if np.isnan(atr):
            continue
        mode, mult = p.get("sl", ("pivot", 0.5))
        if mode == "pivot":
            stop = ev.pivot_low - mult * atr
        else:  # 'atr'
            stop = closes[i_sig] - mult * atr
        # sanity: risk must be positive and not absurdly wide
        risk_pct = (closes[i_sig] - stop) / closes[i_sig]
        if risk_pct <= 0 or risk_pct > p.get("max_risk_pct", 0.10):
            continue
        # entry style: market at next open, or buy-limit on a retest
        limit = None
        ttl = 6
        entry = p.get("entry")
        if entry and entry[0] == "limit_atr":
            _, retest_mult, ttl = entry
            limit = closes[i_sig] - retest_mult * atr
            if limit <= stop:
                continue  # retest would sit below the stop — nonsensical order
        sigs.append(Signal(ts=prep.df.index[i_sig], stop=float(stop),
                           tag=ev.tf, limit=None if limit is None else float(limit),
                           ttl=int(ttl)))
    return sigs


def gen_pullback_signals(prep: Prep, p: dict) -> list:
    """Trend-continuation entries: 1h WT cross-up from a pullback zone, gated by
    4h context and optional regime filters. All filters read state knowable at
    the cross bar's close; entry is next open (engine)."""
    from .engine import Signal

    closes = prep.df["close"].to_numpy()
    lows = prep.df["low"].to_numpy()
    n = len(closes)
    lo, hi = p.get("cross_zone", (-60.0, 0.0))
    warmup = 250  # let EMA200/ATR/4h states settle

    # Precomputed context arrays for the optional structure gates
    thrust_max = dip_min = ema_prev = None
    if p.get("recent_htf_thrust"):
        bars, _level = p["recent_htf_thrust"]
        thrust_max = (pd.Series(prep.wt2_4h).rolling(bars, min_periods=1)
                      .max().to_numpy())
    if p.get("dip_depth"):
        bars, _level = p["dip_depth"]
        dip_min = (pd.Series(prep.wt2).rolling(bars, min_periods=1)
                   .min().to_numpy())
    if p.get("ema200_rising"):
        ema_prev = np.roll(prep.ema200, p["ema200_rising"])

    sigs: list[Signal] = []
    for i in np.where(prep.wt_up)[0]:
        if i < warmup or i >= n - 1:
            continue
        if not (lo <= prep.wt2[i] <= hi):
            continue
        if thrust_max is not None and not (
                thrust_max[i] >= p["recent_htf_thrust"][1]):
            continue
        if dip_min is not None and not (dip_min[i] <= p["dip_depth"][1]):
            continue
        if ema_prev is not None and not (prep.ema200[i] > ema_prev[i]):
            continue
        # ---- 4h context (the multi-timeframe part) ----
        if p.get("htf_wt_min") is not None and not (
                prep.wt2_4h[i] >= p["htf_wt_min"]):
            continue
        if p.get("htf_wt_rising") and prep.wt2_4h_rising[i] != 1.0:
            continue
        if p.get("htf_mfi_pos") and not (prep.mfi_4h[i] > 0):
            continue
        if p.get("alt4h_bull") and prep.alt4h[i] != rs.BULL:
            continue
        if p.get("ema200_up") and not (closes[i] > prep.ema200[i]):
            continue
        # ---- regime gates ----
        if p.get("btc_regime") == "not_bear_1d" and prep.btc1d[i] == rs.BEAR:
            continue
        if p.get("alt_regime") == "not_bear_1d" and prep.alt1d[i] == rs.BEAR:
            continue
        # ---- stop ----
        atr = prep.atr[i]
        if np.isnan(atr) or atr <= 0:
            continue
        mode = p.get("sl", ("swing", 10, 0.5))
        if mode[0] == "swing":
            _, nback, buf = mode
            stop = float(lows[max(0, i - nback + 1): i + 1].min()) - buf * atr
        else:  # ("atr", mult)
            stop = closes[i] - mode[1] * atr
        risk_pct = (closes[i] - stop) / closes[i]
        # too-tight stops make costs dominate and noise fatal; too-wide is junk
        if risk_pct < p.get("min_risk_pct", 0.005) \
                or risk_pct > p.get("max_risk_pct", 0.08):
            continue
        sigs.append(Signal(ts=prep.df.index[i], stop=float(stop), tag="pullback"))
    return sigs


def trail_series(prep: Prep, k: float) -> pd.Series:
    """Chandelier-style trail: close − k×ATR (engine only ever raises the stop)."""
    return pd.Series(prep.df["close"].to_numpy() - k * prep.atr,
                     index=prep.df.index)


def gen_btc_dip_signals(btc_prep: Prep, alt_prep: Prep, p: dict) -> list:
    """Beta-snap: BTC prints a deep-oversold 1h divergence; buy the alt if it
    is RS-bull vs BTC on the filter timeframe (strength selector)."""
    from .engine import Signal

    closes = alt_prep.df["close"].to_numpy()
    alt_idx = alt_prep.df.index
    n = len(closes)
    sigs: list[Signal] = []
    for ev in btc_prep.div1h:
        if p.get("oversold_only") and not (
                ev.wt2_pivot <= p.get("oversold_level", 0)):
            continue
        # map the BTC bar time onto the alt's index (same 1h grid normally)
        t = btc_prep.df.index[ev.i_conf]
        i = int(alt_idx.searchsorted(t, side="right")) - 1
        if i < 0 or i >= n - 1:
            continue
        rs_f = p.get("rs_filter", "4h")
        state = alt_prep.rs4h if rs_f == "4h" else alt_prep.rs1d
        if state[i] != rs.BULL:
            continue
        atr = alt_prep.atr[i]
        if np.isnan(atr):
            continue
        mode, mult = p.get("sl", ("atr", 2.0))
        stop = closes[i] - mult * atr
        risk_pct = (closes[i] - stop) / closes[i]
        if risk_pct <= 0 or risk_pct > p.get("max_risk_pct", 0.10):
            continue
        limit = None
        ttl = 6
        entry = p.get("entry")
        if entry and entry[0] == "limit_atr":
            _, retest_mult, ttl = entry
            limit = closes[i] - retest_mult * atr
            if limit <= stop:
                continue
        sigs.append(Signal(ts=alt_idx[i], stop=float(stop), tag="btc_dip",
                           limit=None if limit is None else float(limit),
                           ttl=int(ttl)))
    return sigs


def wt_exit_series(prep: Prep, *, level: float | None = None) -> pd.Series:
    """Exit request at WT bear cross (optionally only above ``level``)."""
    mask = prep.wt_dn.copy()
    if level is not None:
        mask &= prep.wt2 >= level
    return pd.Series(mask, index=prep.df.index)
