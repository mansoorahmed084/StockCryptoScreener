"""Coins-vs-BTC strength board (the dashboard's "BTC Strength" page).

Answers two questions per coin:

  1. Is it stronger or weaker than the benchmark on 1h / 4h / 1d / 1w / 1M?
     The benchmark is BTC or BTC.D:
     * BTC   — the COIN/BTC ratio (COIN/USDT ÷ BTC/USDT). BTC cannot be
       measured against itself, so its row shows BTC.D instead.
     * BTC.D — COIN/USDT ÷ BTC.D. Up means the coin rises faster than BTC's
       share of the market. (Coin dominance ÷ BTC dominance would cancel to
       COIN/BTC again, so the coin's price is used.) BTC gets a normal row.
     For each cell:
     * ``direction`` / ``strength`` — the ratio run through the same
       noise-filtered classifier as the main matrix (closed candles only).
     * ``pct_vs`` — how much the coin gained or lost against the benchmark
       over the last 1h / 4h / 24h / 7d / 30d, up to the live price.

  2. Is its own price trending up or down on the short / medium / long term?
     Last closed daily candle against EMA 20 / 50 / 200 (see config.yaml).

The BTC.D row always shows BTC.D's own direction: up = BTC taking share.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.config import Config, timeframe_to_seconds
from backend.data import quality
from backend.data.dominance import BtcDominance
from backend.data.frames import OHLCV_COLUMNS, empty_ohlcv
from backend.data.pairs import RatioBuilder
from . import rs, universe

BTC = "BTC"
BTC_D = "BTC.D"
USDT = "USDT"
BENCHMARKS = (BTC, BTC_D)
PINNED = (BTC_D, BTC)          # always the first two rows, never ranked

DEFAULT_TIMEFRAMES = ("1h", "4h", "1d", "1w", "1M")
DEFAULT_WORKERS = 8

# "% vs" window per timeframe: (seconds back, candle timeframe to read it
# from). Each is the finest series whose 500 candles still cover the window,
# so the start price is off by at most one of those candles.
WINDOWS: dict[str, tuple[int, str]] = {
    "1h": (3600, "15m"),
    "4h": (4 * 3600, "15m"),
    "1d": (24 * 3600, "1h"),
    "1w": (7 * 24 * 3600, "1h"),
    "1M": (30 * 24 * 3600, "4h"),
}

DEFAULT_TREND_EMAS = {"short": 20, "medium": 50, "long": 200}
UP, DOWN, SIDEWAYS = "up", "down", "sideways"
TREND_SLOPE_BARS = 5   # EMA must be higher/lower than this many candles ago

STRENGTH_COLUMNS = ["asset", "timeframe", "direction", "strength",
                    "pct_vs", "reason"]
TREND_COLUMNS = ["asset", "horizon", "ema", "state", "dist_pct"]
_STATE_RANK = {rs.BULL: 2, rs.NEUTRAL: 1, rs.BEAR: 0}


@dataclass
class Board:
    strength: pd.DataFrame      # STRENGTH_COLUMNS, one row per (asset, timeframe)
    trends: pd.DataFrame        # TREND_COLUMNS, one row per (asset, horizon)
    timeframes: list[str]
    benchmark: str = BTC
    btc_dominance_pct: float | None = None
    order: list[str] = field(default_factory=list)   # BTC.D, BTC, then strongest

    def summary(self) -> pd.DataFrame:
        """Per coin: timeframes it beats / lags the benchmark on, mean strength."""
        return summarise(self.strength)

    def ranked(self, sort_by: str = "overall", *,
               weakest_first: bool = False) -> list[str]:
        """Coins (not BTC.D / BTC) strongest first; see :func:`rank_coins`."""
        return rank_coins(self.strength, sort_by, weakest_first=weakest_first)

    def breadth(self) -> pd.DataFrame:
        """Per timeframe: how many coins are stronger / weaker than the benchmark."""
        coins = self.strength[~self.strength["asset"].isin(PINNED)]
        known = coins[coins["direction"] != rs.UNKNOWN]
        out = []
        for tf in self.timeframes:
            sub = known[known["timeframe"] == tf]
            out.append({"timeframe": tf,
                        "stronger": int((sub["direction"] == rs.BULL).sum()),
                        "weaker": int((sub["direction"] == rs.BEAR).sum()),
                        "known": len(sub)})
        return pd.DataFrame(out, columns=["timeframe", "stronger", "weaker", "known"])


# -- pure helpers --------------------------------------------------------------
def change_since(frame: pd.DataFrame, timeframe: str, seconds: int, *,
                 now: pd.Timestamp | None = None) -> float:
    """% change of ``frame`` from ``seconds`` ago to its latest close.

    The latest close is the forming candle, i.e. the live price. The start is
    the close of the last candle that had finished by ``now - seconds``.
    """
    if frame.empty:
        return float("nan")
    close = frame["close"].dropna()
    if close.empty:
        return float("nan")
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    step = pd.Timedelta(seconds=timeframe_to_seconds(timeframe))
    finished = close[close.index + step <= now - pd.Timedelta(seconds=seconds)]
    if finished.empty or finished.iloc[-1] == 0:
        return float("nan")
    return float(close.iloc[-1] / finished.iloc[-1] - 1.0) * 100


def trend_state(close: pd.Series, ema_len: int, *,
                slope_bars: int = TREND_SLOPE_BARS,
                drop_forming: bool = True) -> tuple[str, float]:
    """Return (up | down | sideways | unknown, % distance of close from EMA).

    Up = last closed candle above a rising EMA; down = below a falling EMA;
    anything else (above a falling EMA, below a rising one) is sideways.
    """
    close = close.dropna().astype(float)
    if drop_forming and len(close) > 0:
        close = close.iloc[:-1]
    if len(close) < ema_len + slope_bars:
        return rs.UNKNOWN, float("nan")
    ema = close.ewm(span=ema_len, adjust=False).mean()
    last, now_ema = close.iloc[-1], ema.iloc[-1]
    dist = float(last / now_ema - 1.0) * 100
    rising = now_ema > ema.iloc[-1 - slope_bars]
    if last > now_ema and rising:
        return UP, dist
    if last < now_ema and not rising:
        return DOWN, dist
    return SIDEWAYS, dist


def summarise(strength: pd.DataFrame) -> pd.DataFrame:
    """Per coin: ``beats`` / ``lags`` (timeframe counts) and mean ``score``,
    strongest first. BTC.D and BTC are left out — they are pinned rows."""
    coins = strength[~strength["asset"].isin(PINNED)]
    rows = []
    for asset, sub in coins.groupby("asset", sort=False):
        known = sub[sub["direction"] != rs.UNKNOWN]
        rows.append({
            "asset": asset,
            "beats": int((known["direction"] == rs.BULL).sum()),
            "lags": int((known["direction"] == rs.BEAR).sum()),
            "score": float(known["strength"].mean()) if len(known) else float("nan"),
        })
    out = pd.DataFrame(rows, columns=["asset", "beats", "lags", "score"])
    return out.sort_values(["beats", "score"], ascending=[False, False],
                           na_position="last").reset_index(drop=True)


def rank_coins(strength: pd.DataFrame, sort_by: str = "overall", *,
               weakest_first: bool = False) -> list[str]:
    """Coins ordered by strength; coins with no reading always go last.

    ``overall`` ranks by (timeframes stronger - timeframes weaker, mean score);
    a timeframe ranks by that cell's state, then its score.
    """
    if sort_by == "overall":
        s = summarise(strength)
        s["net"] = s["beats"] - s["lags"]
        known = s[s["score"].notna()]
        keys = list(zip(known["net"], known["score"]))
        names = known["asset"].tolist()
        missing = s.loc[s["score"].isna(), "asset"].tolist()
    else:
        coins = strength[~strength["asset"].isin(PINNED)
                         & (strength["timeframe"] == sort_by)]
        ok = coins["direction"].isin(_STATE_RANK) & coins["strength"].notna()
        known = coins[ok]
        keys = list(zip(known["direction"].map(_STATE_RANK), known["strength"]))
        names = known["asset"].tolist()
        missing = coins.loc[~ok, "asset"].tolist()
    ordered = [n for _, n in sorted(zip(keys, names), key=lambda kv: kv[0],
                                    reverse=not weakest_first)]
    return ordered + missing


def divide(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    """``a ÷ b`` candle by candle on shared timestamps; volume from ``a``.

    Same result as the ratio builder's divide, in NumPy: a board of 500 coins
    builds thousands of ratios, and the pandas version cost ~20 ms each.
    """
    if a.empty or b.empty:
        return empty_ohlcv()
    idx = a.index.intersection(b.index)
    if len(idx) == 0:
        return empty_ohlcv()
    cols = ["open", "high", "low", "close"]
    num = a.loc[idx, cols].to_numpy(dtype=float)
    den = b.loc[idx, cols].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = num / den
    ok = np.isfinite(r[:, 3])
    r = np.where(np.isfinite(r), r, np.nan)
    out = pd.DataFrame({
        "open": r[:, 0],
        "high": np.nanmax(r, axis=1, initial=-np.inf, where=~np.isnan(r)),
        "low": np.nanmin(r, axis=1, initial=np.inf, where=~np.isnan(r)),
        "close": r[:, 3],
        "volume": a.loc[idx, "volume"].to_numpy(dtype=float),
    }, index=idx)[OHLCV_COLUMNS]
    out.index.name = "ts"
    return out[ok]


def _strength_row(asset: str, tf: str, rsr: rs.RSResult, pct: float,
                  reason: str = "") -> dict:
    return {"asset": asset, "timeframe": tf, "direction": rsr.direction,
            "strength": rsr.strength, "pct_vs": pct,
            "reason": reason or rsr.reason}


def _trend_rows(asset: str, close: pd.Series, emas: dict[str, int]) -> list[dict]:
    rows = []
    for horizon, ema_len in emas.items():
        state, dist = trend_state(close, int(ema_len))
        rows.append({"asset": asset, "horizon": horizon, "ema": int(ema_len),
                     "state": state, "dist_pct": dist})
    return rows


# -- board ---------------------------------------------------------------------
def build_board(builder: RatioBuilder, config: Config, coins: list[str],
                dominance: BtcDominance,
                timeframes: list[str] | tuple[str, ...] | None = None, *,
                benchmark: str = BTC, liquidity_gate: bool = True,
                now: pd.Timestamp | None = None,
                workers: int | None = None,
                progress: Callable[[int, int], None] | None = None) -> Board:
    """``progress(done, total)`` is called as each coin finishes."""
    if benchmark not in BENCHMARKS:
        raise ValueError(f"benchmark must be one of {BENCHMARKS}, not {benchmark!r}")
    settings = config.btc_strength
    timeframes = list(timeframes or settings.get("timeframes", DEFAULT_TIMEFRAMES))
    trend_tf = settings.get("trend_timeframe", "1d")
    trend_emas = dict(settings.get("trend_emas", DEFAULT_TREND_EMAS))
    workers = workers or int(settings.get("workers", DEFAULT_WORKERS))
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    coins = list(dict.fromkeys(c.upper() for c in coins if c.upper() not in PINNED))
    service = builder.service
    min_qv = config.min_quote_volume_24h if liquidity_gate else 0.0

    def window(tf: str) -> tuple[int, str]:
        return WINDOWS.get(tf, (timeframe_to_seconds(tf), tf))

    # Longest timeframe first: its big fetch then serves the shorter ones
    # (1M's 1000 daily candles also give 1w and 1d; see OHLCVService._source).
    fetch_order = sorted(timeframes, key=timeframe_to_seconds, reverse=True)
    needed = list(dict.fromkeys(
        tf for t in fetch_order for tf in (t, window(t)[1])))

    def bench(tf: str) -> pd.DataFrame:
        # Always COIN/USDT ÷ BTC/USDT, never CoinDCX's native X/BTC book: it is
        # priced to ~6 decimals, so cheap coins come back flat (see RatioBuilder).
        if benchmark == BTC:
            return service.get(BTC, USDT, tf)
        return dominance.candles(tf)

    def trend(asset: str) -> list[dict]:
        # BTC's trend is a pinned row, built once below.
        if asset == BTC:
            return []
        return _trend_rows(asset, service.get(asset, USDT, trend_tf)["close"],
                           trend_emas)

    def measure(asset: str) -> tuple[list[dict], list[dict]]:
        if not universe.liquidity_ok(service.adapter, asset, USDT, min_qv):
            # No downloads for a coin too thin to trade; its trend is unknown too.
            return ([_strength_row(asset, tf, rs.RSResult(), float("nan"),
                                   "illiquid") for tf in timeframes],
                    _trend_rows(asset, pd.Series(dtype=float), trend_emas))
        ratios: dict[str, tuple[pd.DataFrame, quality.QualityReport]] = {}

        def ratio(tf: str) -> tuple[pd.DataFrame, quality.QualityReport]:
            if tf not in ratios:
                frame = divide(service.get(asset, USDT, tf), bench(tf))
                ratios[tf] = (frame, quality.assess(
                    frame, tf, stale_multiplier=config.stale_multiplier))
            return ratios[tf]

        cells: dict[str, dict] = {}
        for tf in fetch_order:
            frame, rep = ratio(tf)
            rsr = (rs.classify(frame["close"], config.classifier_params(tf))
                   if rep.ok else rs.RSResult(reason=rep.reason))
            secs, wtf = window(tf)
            wframe, wrep = ratio(wtf)
            pct = change_since(wframe, wtf, secs, now=now) if wrep.ok else float("nan")
            cells[tf] = _strength_row(asset, tf, rsr, pct)
        # After the loop, so the trend reuses the big daily fetch.
        return [cells[tf] for tf in timeframes], trend(asset)

    # Warm the legs every coin shares before the threads start, so they are
    # fetched once, not once per thread.
    for tf in sorted(set(needed) | {trend_tf}, key=timeframe_to_seconds, reverse=True):
        dominance.candles(tf)
        service.get(BTC, USDT, tf)

    # BTC.D row: BTC.D's own direction. Up = BTC taking share from the alts.
    rows: list[dict] = []
    for tf in timeframes:
        frame = dominance.candles(tf)
        rep = quality.assess(frame, tf, stale_multiplier=config.stale_multiplier)
        rsr = (rs.classify(frame["close"], config.classifier_params(tf))
               if rep.ok else rs.RSResult(reason=rep.reason))
        secs, wtf = window(tf)
        pct = change_since(dominance.candles(wtf), wtf, secs, now=now)
        rows.append(_strength_row(BTC_D, tf, rsr, pct))

    trend_rows = (_trend_rows(BTC_D, dominance.candles(trend_tf)["close"], trend_emas)
                  + _trend_rows(BTC, service.get(BTC, USDT, trend_tf)["close"],
                                trend_emas))

    measured = coins if benchmark == BTC else [BTC, *coins]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for done, (srows, trows) in enumerate(pool.map(measure, measured), 1):
            rows.extend(srows)
            trend_rows.extend(trows)
            if progress:
                progress(done, len(measured))

    strength = pd.DataFrame(rows, columns=STRENGTH_COLUMNS)
    trends = pd.DataFrame(trend_rows, columns=TREND_COLUMNS)
    order = [BTC_D, BTC] + rank_coins(strength)
    return Board(strength=strength, trends=trends, timeframes=timeframes,
                 benchmark=benchmark, btc_dominance_pct=dominance.current_pct(),
                 order=order)
