"""High-level screener service used by the dashboard and API.

Wires the adapter, OHLCV service, ratio builder and matrix together, and layers
on sector ranks. Keeps the UI layers thin and reusable.
"""
from __future__ import annotations

import pandas as pd

from backend.config import Config, load_config
from backend.data.adapters import build_adapter
from backend.data.ohlcv import OHLCVService
from backend.data.pairs import RatioBuilder
from backend.screener import matrix as matrix_mod
from backend.screener import regime as regime_mod
from backend.screener import rs as rs_mod
from backend.screener import sectors as sectors_mod
from backend.screener import universe as universe_mod


class ScreenerService:
    def __init__(self, config: Config | None = None, *, refresh: bool = True):
        self.config = config or load_config()
        self.adapter = build_adapter(self.config)
        if refresh:
            self.adapter.refresh_markets()
        self.ohlcv = OHLCVService(self.adapter, self.config)
        self._builder: RatioBuilder | None = None

    def universe(self) -> list[str]:
        return universe_mod.select_universe(self.adapter, self.config)

    def build_matrix(self, coins: list[str] | None = None,
                     bases: list[str] | None = None,
                     timeframes: list[str] | None = None,
                     *, liquidity_gate: bool = True) -> pd.DataFrame:
        coins = [c.upper() for c in (coins or self.universe())]
        bases = [b.upper() for b in (bases or self.config.bases)]
        timeframes = timeframes or self.config.timeframes
        self._builder = RatioBuilder(self.ohlcv, self.config, universe_coins=coins)
        df = matrix_mod.build_matrix(
            self._builder, self.config, coins, bases, timeframes,
            apply_liquidity_gate=liquidity_gate)
        return sectors_mod.add_sector_rank(df, self.config)

    def regime(self, df: pd.DataFrame) -> regime_mod.Regime:
        reg = regime_mod.assess(df, quote="USDT")
        # If BTC wasn't in the selected coins, compute its trend directly so the
        # market-context header is always meaningful.
        if not reg.btc_trend and self._builder is not None:
            trend: dict[str, str] = {}
            for tf in df["timeframe"].unique():
                res = self._builder.ratio("BTC", "USDT", tf)
                if res.quality.ok:
                    rsr = rs_mod.classify(res.close, self.config.classifier_params(tf))
                    trend[tf] = rsr.direction
            reg.btc_trend = trend
        return reg

    def ratio_frame(self, coin: str, base: str, timeframe: str) -> pd.DataFrame:
        """OHLCV of a ratio for charting. Requires a prior build_matrix call."""
        builder = self._builder or RatioBuilder(self.ohlcv, self.config)
        return builder.ratio(coin, base, timeframe).frame
