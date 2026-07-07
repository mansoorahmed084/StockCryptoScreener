"""Build the coins x bases x timeframes relative-strength matrix.

Produces a tidy long-form DataFrame (one row per cell) that everything else —
the filter engine, the dashboard heatmap, sector aggregation — consumes.
"""
from __future__ import annotations

import pandas as pd

from backend.config import Config
from backend.data.pairs import RatioBuilder
from . import rs, universe

CELL_COLUMNS = [
    "coin", "base", "timeframe", "direction", "strength", "change_pct",
    "rank", "method", "synthetic", "quote_volume_24h", "quality_ok",
    "quality_reason", "n",
]


def build_matrix(builder: RatioBuilder, config: Config, coins: list[str],
                 bases: list[str], timeframes: list[str], *,
                 apply_liquidity_gate: bool = True,
                 drop_forming: bool = True) -> pd.DataFrame:
    """Return the long-form RS matrix as a DataFrame."""
    adapter = builder.service.adapter
    min_qv = config.min_quote_volume_24h if apply_liquidity_gate else 0.0
    rows: list[dict] = []

    for coin in coins:
        coin = coin.upper()
        for base in bases:
            base = base.upper()
            if coin == base:
                continue
            liquid = universe.liquidity_ok(adapter, coin, base, min_qv)
            qv = universe.pair_quote_volume(adapter, coin, base)
            for tf in timeframes:
                params = config.classifier_params(tf)
                if not liquid:
                    rows.append(_cell(coin, base, tf, rs.RSResult(
                        direction=rs.UNKNOWN, reason="illiquid"),
                        method="", synthetic=False, qv=qv, quality_ok=False,
                        quality_reason="illiquid"))
                    continue
                res = builder.ratio(coin, base, tf)
                if not res.quality.ok:
                    rows.append(_cell(coin, base, tf, rs.RSResult(
                        direction=rs.UNKNOWN, reason=res.quality.reason),
                        method=res.method, synthetic=res.synthetic, qv=qv,
                        quality_ok=False, quality_reason=res.quality.reason))
                    continue
                rsr = rs.classify(res.close, params, drop_forming=drop_forming)
                rows.append(_cell(coin, base, tf, rsr, method=res.method,
                                  synthetic=res.synthetic, qv=qv,
                                  quality_ok=True, quality_reason=""))

    df = pd.DataFrame(rows, columns=CELL_COLUMNS)
    return _add_ranks(df)


def _cell(coin: str, base: str, tf: str, rsr: rs.RSResult, *, method: str,
          synthetic: bool, qv: float, quality_ok: bool, quality_reason: str) -> dict:
    return {
        "coin": coin, "base": base, "timeframe": tf,
        "direction": rsr.direction, "strength": rsr.strength,
        "change_pct": rsr.change_pct, "rank": rsr.rank,
        "method": method, "synthetic": synthetic, "quote_volume_24h": qv,
        "quality_ok": quality_ok, "quality_reason": quality_reason, "n": rsr.n,
    }


def _add_ranks(df: pd.DataFrame) -> pd.DataFrame:
    """Percentile-rank strength within each (base, timeframe) group (0-100)."""
    if df.empty:
        return df
    known = df["direction"].isin([rs.BULL, rs.BEAR, rs.NEUTRAL]) & df["strength"].notna()
    df["rank"] = pd.NA
    if known.any():
        ranks = (
            df.loc[known]
            .groupby(["base", "timeframe"])["strength"]
            .rank(pct=True) * 100
        )
        df.loc[known, "rank"] = ranks
    return df


def pivot_direction(df: pd.DataFrame, base: str) -> pd.DataFrame:
    """Coins x timeframes grid of directions for a single base (for display)."""
    sub = df[df["base"] == base.upper()]
    return sub.pivot(index="coin", columns="timeframe", values="direction")
