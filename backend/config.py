"""Configuration loading and timeframe helpers.

Loads ``config.yaml`` (or a supplied path) into a lightweight ``Config`` object.
All modules read thresholds, universe, bases and timeframes from here so that
behaviour is data-driven and unit-testable.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Timeframe -> seconds. The screener's canonical timeframe vocabulary.
TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 3 * 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "2h": 2 * 60 * 60,
    "4h": 4 * 60 * 60,
    "6h": 6 * 60 * 60,
    "8h": 8 * 60 * 60,
    "1d": 24 * 60 * 60,
    "3d": 3 * 24 * 60 * 60,
    "1w": 7 * 24 * 60 * 60,
    # Calendar months vary; 30 days is the nominal length. It divides evenly
    # into 1d so OHLCVService resamples months from daily candles.
    "1M": 30 * 24 * 60 * 60,
}

# Timeframes the CoinDCX public candles endpoint actually serves (verified live,
# 2026-07). The docs list more, but only these return data — everything else is
# resampled from the largest fetchable divisor by OHLCVService.
COINDCX_FETCHABLE_TIMEFRAMES: set[str] = {"1m", "15m", "1h", "1d"}

# Max candles the public endpoint returns per request.
COINDCX_MAX_CANDLES = 1000

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def timeframe_to_seconds(tf: str) -> int:
    try:
        return TIMEFRAME_SECONDS[tf]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unknown timeframe: {tf!r}") from exc


@dataclass
class ClassifierParams:
    """Noise-filter / classification parameters for one timeframe (plan sec 4.7)."""

    ema_len: int = 21
    vol_lookback: int = 90
    neutral_band: float = 1.0
    hysteresis_out: float = 0.6
    persistence: int = 2
    weights: dict[str, float] = field(
        default_factory=lambda: {"z_return": 1.0, "ema_pos": 1.0, "ema_slope": 1.0}
    )


@dataclass
class Config:
    raw: dict[str, Any]

    # --- convenience accessors -------------------------------------------------
    @property
    def exchange(self) -> str:
        return self.raw.get("exchange", "coindcx")

    @property
    def ccxt_exchange(self) -> str:
        return self.raw.get("ccxt_exchange", "binance")

    @property
    def bases(self) -> list[str]:
        return list(self.raw.get("bases", ["BTC", "ETH", "USDT"]))

    @property
    def timeframes(self) -> list[str]:
        return list(self.raw.get("timeframes", ["1w", "1d", "4h", "1h", "15m", "3m"]))

    @property
    def universe(self) -> dict[str, Any]:
        return self.raw.get("universe", {})

    @property
    def watchlist(self) -> list[str]:
        return list(self.universe.get("watchlist", []))

    @property
    def min_quote_volume_24h(self) -> float:
        return float(self.universe.get("min_quote_volume_24h", 0.0))

    @property
    def sectors(self) -> dict[str, list[str]]:
        return dict(self.raw.get("sectors", {}))

    @property
    def index_exclude(self) -> list[str]:
        return list(self.raw.get("index", {}).get("exclude", []))

    @property
    def candle_limit(self) -> int:
        return int(self.raw.get("data", {}).get("candle_limit", 500))

    @property
    def cache_dir(self) -> str:
        return str(self.raw.get("data", {}).get("cache_dir", "data_cache"))

    @property
    def stale_multiplier(self) -> float:
        return float(self.raw.get("data", {}).get("stale_multiplier", 3))

    @property
    def watchlists_file(self) -> str:
        return str(self.raw.get("data", {}).get("watchlists_file",
                                                "data_cache/watchlists.json"))

    @property
    def alerts(self) -> dict[str, Any]:
        """Price / trendline / zone alert settings (empty -> defaults)."""
        return dict(self.raw.get("alerts", {}))

    @property
    def btc_strength(self) -> dict[str, Any]:
        """Settings for the coins-vs-BTC board (empty -> module defaults)."""
        return dict(self.raw.get("btc_strength", {}))

    def classifier_params(self, timeframe: str) -> ClassifierParams:
        """Merge the ``default`` block with any per-timeframe override."""
        cls = self.raw.get("classifier", {})
        merged: dict[str, Any] = copy.deepcopy(cls.get("default", {}))
        override = cls.get("per_timeframe", {}).get(timeframe, {})
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key].update(value)
            else:
                merged[key] = value
        return ClassifierParams(**merged) if merged else ClassifierParams()

    def sectors_for(self, coin: str) -> list[str]:
        return list(self.sectors.get(coin, []))


def load_config(path: str | Path | None = None) -> Config:
    """Load configuration from YAML. Falls back to the repo-root ``config.yaml``."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return Config(raw=raw)
