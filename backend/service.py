"""High-level screener service used by the dashboard and API.

Wires the adapter, OHLCV service, ratio builder and matrix together, and layers
on sector ranks. Keeps the UI layers thin and reusable.

One canonical RatioBuilder (over the *configured* universe) serves every caller:
the INDEX base is therefore always the configured equal-weight universe, no
matter which subset of coins a particular matrix build or chart request views,
and concurrent callers never swap builders out from under each other.
"""
from __future__ import annotations

import pandas as pd

from backend.config import Config, load_config
from backend.data.adapters import build_adapter
from backend.data.ohlcv import OHLCVService
from backend.data.pairs import RatioBuilder
from backend.screener import confluence as confluence_mod
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

    def builder(self) -> RatioBuilder:
        """Canonical ratio builder over the configured universe (lazy)."""
        if self._builder is None:
            self._builder = RatioBuilder(self.ohlcv, self.config,
                                         universe_coins=self.universe())
        return self._builder

    def build_matrix(self, coins: list[str] | None = None,
                     bases: list[str] | None = None,
                     timeframes: list[str] | None = None,
                     *, liquidity_gate: bool = True) -> pd.DataFrame:
        coins = [c.upper() for c in (coins or self.universe())]
        bases = [b.upper() for b in (bases or self.config.bases)]
        timeframes = timeframes or self.config.timeframes
        df = matrix_mod.build_matrix(
            self.builder(), self.config, coins, bases, timeframes,
            apply_liquidity_gate=liquidity_gate)
        return sectors_mod.add_sector_rank(df, self.config)

    def regime(self, df: pd.DataFrame) -> regime_mod.Regime:
        reg = regime_mod.assess(df, quote="USDT")
        # If BTC wasn't among the viewed coins, compute its trend directly so the
        # market-context header is always meaningful.
        if not reg.btc_trend:
            trend: dict[str, str] = {}
            for tf in df["timeframe"].unique():
                res = self.builder().ratio("BTC", "USDT", tf)
                if res.quality.ok:
                    rsr = rs_mod.classify(res.close, self.config.classifier_params(tf))
                    trend[tf] = rsr.direction
            reg.btc_trend = trend
        return reg

    def ratio_frame(self, coin: str, base: str, timeframe: str) -> pd.DataFrame:
        """OHLCV of a ratio for charting/backtests."""
        return self.builder().ratio(coin, base, timeframe).frame

    def report(self, coins: list[str] | None = None, base: str = "USDT",
               timeframes: list[str] | None = None, *, div_lookback: int = 10,
               liquidity_gate: bool = True,
               require_all_bull: bool = False) -> pd.DataFrame:
        """Multi-timeframe bullish-confluence report (RS alignment + VMC divs)."""
        coins = [c.upper() for c in (coins or self.universe())]
        params = confluence_mod.ConfluenceParams(
            base=base.upper(),
            timeframes=tuple(timeframes or ("15m", "4h", "1d", "1w")),
            div_lookback=div_lookback,
            liquidity_gate=liquidity_gate,
            require_all_bull=require_all_bull,
        )
        return confluence_mod.build_report(self.builder(), self.config, coins, params)
