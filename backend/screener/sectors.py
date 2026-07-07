"""Narrative / sector grouping and aggregation (plan sec 4.9).

Coins are tagged with sectors in config. Aggregating cell strength by sector
shows which narrative is leading on each timeframe, and exposes a ``sector_rank``
metric (percentile of a coin's sector strength among sectors) for the filters.
"""
from __future__ import annotations

import pandas as pd

from backend.config import Config
from . import rs


def coin_sector(config: Config, coin: str) -> str | None:
    """Primary (first) sector tag for a coin, if any."""
    tags = config.sectors_for(coin.upper())
    return tags[0] if tags else None


def sector_strength(df: pd.DataFrame, config: Config,
                    base: str | None = None) -> pd.DataFrame:
    """Long-form sector aggregate: base, timeframe, sector, mean_strength, members."""
    known = df[df["direction"] != rs.UNKNOWN].copy()
    if base is not None:
        known = known[known["base"] == base.upper()]
    if known.empty:
        return pd.DataFrame(
            columns=["base", "timeframe", "sector", "mean_strength", "members"])
    known["sector"] = known["coin"].map(lambda c: coin_sector(config, c))
    known = known.dropna(subset=["sector"])
    grp = (known.groupby(["base", "timeframe", "sector"])
           .agg(mean_strength=("strength", "mean"), members=("coin", "nunique"))
           .reset_index())
    return grp


def add_sector_rank(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Add ``sector`` and ``sector_rank`` (0-100 percentile) columns to the matrix."""
    df = df.copy()
    df["sector"] = df["coin"].map(lambda c: coin_sector(config, c))
    agg = sector_strength(df, config)
    if agg.empty:
        df["sector_rank"] = pd.NA
        return df
    agg["sector_rank"] = (
        agg.groupby(["base", "timeframe"])["mean_strength"].rank(pct=True) * 100
    )
    lookup = agg.set_index(["base", "timeframe", "sector"])["sector_rank"]

    def _rank(row):
        key = (row["base"], row["timeframe"], row["sector"])
        return lookup.get(key, pd.NA) if row["sector"] is not None else pd.NA

    df["sector_rank"] = df.apply(_rank, axis=1)
    return df


def sector_heatmap(df: pd.DataFrame, config: Config, base: str) -> pd.DataFrame:
    """Sector x timeframe pivot of mean strength for display."""
    agg = sector_strength(df, config, base=base)
    if agg.empty:
        return pd.DataFrame()
    return agg.pivot(index="sector", columns="timeframe", values="mean_strength")
