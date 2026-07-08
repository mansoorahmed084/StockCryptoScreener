"""Multi-timeframe bullish-confluence report.

For each coin, checks two things across a set of selected timeframes:

  1. **RS alignment** — is the coin's ratio vs the chosen base classified bull
     on every selected timeframe simultaneously (the noise-filtered direction
     from the RS engine, closed candles only)?
  2. **VuManChu divergences** — did Cipher B print a regular bull/bear
     divergence within the last ``div_lookback`` closed candles on that
     timeframe, and do divergences stack on multiple timeframes at once?

Output is one wide row per coin with per-timeframe direction/strength/divergence
columns plus summary flags (``all_bull``, ``multi_tf_bull_div``) and a ranking
``score``, consumed by the dashboard Report tab, the CLI ``report`` command and
the API ``/report`` endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backend.config import Config
from backend.data.pairs import RatioBuilder
from backend.indicators.base import IndicatorResult
from backend.indicators.vumanchu import VuManChuCipherB
from . import rs, universe

DIV_BULL, DIV_BEAR, DIV_BOTH, DIV_NONE = "bull", "bear", "bull+bear", ""


@dataclass
class ConfluenceParams:
    base: str = "USDT"
    timeframes: tuple[str, ...] = ("15m", "4h", "1d", "1w")
    div_lookback: int = 10        # divergence counts if within last N closed candles
    liquidity_gate: bool = True
    require_all_bull: bool = False


def _recent_divergence(result: IndicatorResult, closed: pd.DataFrame,
                       lookback: int) -> str:
    """Which divergences printed within the last ``lookback`` closed candles."""
    if closed.empty or not result.markers:
        return DIV_NONE
    window = set(closed.index[-lookback:])
    bull = any(m.kind == "bull_div" and m.ts in window for m in result.markers)
    bear = any(m.kind == "bear_div" and m.ts in window for m in result.markers)
    if bull and bear:
        return DIV_BOTH
    if bull:
        return DIV_BULL
    if bear:
        return DIV_BEAR
    return DIV_NONE


def build_report(builder: RatioBuilder, config: Config, coins: list[str],
                 params: ConfluenceParams,
                 indicator_factory=VuManChuCipherB) -> pd.DataFrame:
    """One wide row per coin: per-TF direction/strength/divergence + summary."""
    base = params.base.upper()
    adapter = builder.service.adapter
    min_qv = config.min_quote_volume_24h if params.liquidity_gate else 0.0
    rows: list[dict] = []

    for coin in coins:
        coin = coin.upper()
        if coin == base:
            continue
        liquid = universe.liquidity_ok(adapter, coin, base, min_qv)
        rec: dict = {"coin": coin}
        bull_tfs: list[str] = []
        div_bull_tfs: list[str] = []
        div_bear_tfs: list[str] = []
        known = 0

        for tf in params.timeframes:
            dir_col, str_col, div_col = f"dir_{tf}", f"strength_{tf}", f"div_{tf}"
            rec[dir_col], rec[str_col], rec[div_col] = rs.UNKNOWN, None, DIV_NONE
            if not liquid:
                continue
            res = builder.ratio(coin, base, tf)
            if not res.quality.ok:
                continue
            cls = rs.classify(res.close, config.classifier_params(tf))
            rec[dir_col] = cls.direction
            rec[str_col] = None if pd.isna(cls.strength) else round(cls.strength, 2)
            if cls.direction != rs.UNKNOWN:
                known += 1
            if cls.direction == rs.BULL:
                bull_tfs.append(tf)

            closed = res.frame.iloc[:-1]  # signals on closed candles only
            div = _recent_divergence(indicator_factory().compute(closed), closed,
                                     params.div_lookback)
            rec[div_col] = div
            if div in (DIV_BULL, DIV_BOTH):
                div_bull_tfs.append(tf)
            if div in (DIV_BEAR, DIV_BOTH):
                div_bear_tfs.append(tf)

        rec["bull_tf_count"] = len(bull_tfs)
        rec["known_tf_count"] = known
        # strict alignment: bull on EVERY selected timeframe
        rec["all_bull"] = len(bull_tfs) == len(params.timeframes)
        rec["bull_div_tfs"] = ",".join(div_bull_tfs)
        rec["bear_div_tfs"] = ",".join(div_bear_tfs)
        rec["multi_tf_bull_div"] = len(div_bull_tfs) >= 2
        # rank: alignment dominates, bull divs add confluence, bear divs warn
        rec["score"] = (2 * len(bull_tfs) + len(div_bull_tfs)
                        - len(div_bear_tfs))
        rows.append(rec)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    if params.require_all_bull:
        df = df[df["all_bull"]]
    return df.sort_values(["score", "bull_tf_count"],
                          ascending=False).reset_index(drop=True)
