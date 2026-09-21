"""Coins-vs-BTC strength board (the dashboard's "BTC Strength" page).

Answers two questions per coin:

  1. Is it stronger or weaker than BTC on 1h / 4h / 1d / 1w / 1M?
     * ``direction`` / ``strength`` — the COIN/BTC ratio run through the same
       noise-filtered classifier as the main matrix (closed candles only).
     * ``pct_vs_btc`` — how much the coin gained or lost against BTC over the
       last 1h / 4h / 24h / 7d / 30d, up to the live price.
     BTC cannot be measured against itself, so its row uses BTC.D instead:
     BTC.D rising means BTC is taking market share from the alts.

  2. Is its own price trending up or down on the short / medium / long term?
     Last closed daily candle against EMA 20 / 50 / 200 (see config.yaml).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backend.config import Config, timeframe_to_seconds
from backend.data import quality
from backend.data.dominance import BtcDominance
from backend.data.pairs import RatioBuilder
from . import rs, universe

BTC = "BTC"
BTC_D = "BTC.D"
USDT = "USDT"

DEFAULT_TIMEFRAMES = ("1h", "4h", "1d", "1w", "1M")

# "% vs BTC" window per timeframe: (seconds back, candle timeframe to read it
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
                    "pct_vs_btc", "reason"]
TREND_COLUMNS = ["asset", "horizon", "ema", "state", "dist_pct"]


@dataclass
class Board:
    strength: pd.DataFrame      # STRENGTH_COLUMNS, one row per (asset, timeframe)
    trends: pd.DataFrame        # TREND_COLUMNS, one row per (asset, horizon)
    timeframes: list[str]
    btc_dominance_pct: float | None = None
    order: list[str] = field(default_factory=list)   # display order of assets

    def summary(self) -> pd.DataFrame:
        """Per coin: timeframes it beats / lags BTC on, and its mean strength."""
        return summarise(self.strength)

    def breadth(self) -> pd.DataFrame:
        """Per timeframe: how many coins are stronger / weaker than BTC."""
        coins = self.strength[self.strength["asset"] != BTC_D]
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
    strongest first. BTC.D is left out — it is the benchmark, not a coin."""
    coins = strength[strength["asset"] != BTC_D]
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


def _strength_row(asset: str, tf: str, rsr: rs.RSResult, pct: float,
                  reason: str = "") -> dict:
    return {"asset": asset, "timeframe": tf, "direction": rsr.direction,
            "strength": rsr.strength, "pct_vs_btc": pct,
            "reason": reason or rsr.reason}


# -- board ---------------------------------------------------------------------
def build_board(builder: RatioBuilder, config: Config, coins: list[str],
                dominance: BtcDominance,
                timeframes: list[str] | tuple[str, ...] | None = None, *,
                liquidity_gate: bool = True,
                now: pd.Timestamp | None = None) -> Board:
    settings = config.btc_strength
    timeframes = list(timeframes or settings.get("timeframes", DEFAULT_TIMEFRAMES))
    trend_tf = settings.get("trend_timeframe", "1d")
    trend_emas = dict(settings.get("trend_emas", DEFAULT_TREND_EMAS))
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    coins = [c.upper() for c in coins if c.upper() not in (BTC, BTC_D)]
    adapter = builder.service.adapter
    min_qv = config.min_quote_volume_24h if liquidity_gate else 0.0

    def window(tf: str) -> tuple[int, str]:
        return WINDOWS.get(tf, (timeframe_to_seconds(tf), tf))

    rows: list[dict] = []

    # BTC's own row: BTC.D. Up = BTC stronger than the alts.
    for tf in timeframes:
        frame = dominance.candles(tf)
        rep = quality.assess(frame, tf, stale_multiplier=config.stale_multiplier)
        rsr = (rs.classify(frame["close"], config.classifier_params(tf))
               if rep.ok else rs.RSResult(reason=rep.reason))
        secs, wtf = window(tf)
        pct = change_since(dominance.candles(wtf), wtf, secs, now=now)
        rows.append(_strength_row(BTC_D, tf, rsr, pct))

    # Each coin against BTC, always as COIN/USDT ÷ BTC/USDT: native X/BTC books
    # on CoinDCX are too coarsely priced for cheap coins (see RatioBuilder).
    for coin in coins:
        # Gate on the coin's own USDT book: a thin native COIN/BTC book should
        # not hide a coin that trades well against USDT.
        if not universe.liquidity_ok(adapter, coin, USDT, min_qv):
            for tf in timeframes:
                rows.append(_strength_row(coin, tf, rs.RSResult(),
                                          float("nan"), "illiquid"))
            continue
        for tf in timeframes:
            res = builder.ratio(coin, BTC, tf, prefer_direct=False)
            rsr = (rs.classify(res.close, config.classifier_params(tf))
                   if res.quality.ok else rs.RSResult(reason=res.quality.reason))
            secs, wtf = window(tf)
            wres = builder.ratio(coin, BTC, wtf, prefer_direct=False)
            pct = (change_since(wres.frame, wtf, secs, now=now)
                   if wres.quality.ok else float("nan"))
            rows.append(_strength_row(coin, tf, rsr, pct))

    strength = pd.DataFrame(rows, columns=STRENGTH_COLUMNS)

    # Price trends: BTC.D, BTC and every coin on its own USDT chart.
    trend_rows: list[dict] = []
    closes = {BTC_D: dominance.candles(trend_tf)["close"]}
    for asset in [BTC, *coins]:
        frame = builder.service.get(asset, USDT, trend_tf)
        closes[asset] = frame["close"] if not frame.empty else pd.Series(dtype=float)
    for asset, close in closes.items():
        for horizon, ema_len in trend_emas.items():
            state, dist = trend_state(close, int(ema_len))
            trend_rows.append({"asset": asset, "horizon": horizon,
                               "ema": int(ema_len), "state": state,
                               "dist_pct": dist})
    trends = pd.DataFrame(trend_rows, columns=TREND_COLUMNS)

    order = [BTC_D, BTC] + summarise(strength)["asset"].tolist()
    return Board(strength=strength, trends=trends, timeframes=timeframes,
                 btc_dominance_pct=dominance.current_pct(), order=order)
