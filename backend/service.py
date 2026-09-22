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
from backend.data import marketcap
from backend.data.binance_futures import BinanceFutures
from backend.data.dominance import BtcDominance
from backend.data.ohlcv import OHLCVService
from backend.data.pairs import RatioBuilder
from backend.screener import btc_strength as btc_strength_mod
from backend.screener import confluence as confluence_mod
from backend.screener import liquidation as liquidation_mod
from backend.screener import market_read as market_read_mod
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
        self._dominance: BtcDominance | None = None
        self._futures: BinanceFutures | None = None

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

    def dominance(self) -> BtcDominance:
        """BTC.D source (lazy, shared so its short cache is reused)."""
        if self._dominance is None:
            self._dominance = BtcDominance()
        return self._dominance

    def btc_board(self, coins: list[str] | None = None,
                  timeframes: list[str] | None = None, *,
                  benchmark: str = btc_strength_mod.BTC,
                  liquidity_gate: bool = True,
                  progress=None) -> btc_strength_mod.Board:
        """Coins vs BTC or BTC.D per timeframe, plus short/medium/long trends."""
        coins = [c.upper() for c in (coins or self.universe())]
        return btc_strength_mod.build_board(
            self.builder(), self.config, coins, self.dominance(), timeframes,
            benchmark=benchmark, liquidity_gate=liquidity_gate, progress=progress)

    def usdt_coins(self) -> list[str]:
        """Every coin with a CoinDCX USDT market, busiest first."""
        return universe_mod.usdt_coins(self.adapter)

    def top_coins(self, n: int) -> tuple[list[str], str]:
        """The ``n`` biggest coins by CoinGecko market cap that CoinDCX lists
        against USDT, without stablecoins and wrapped tokens. Falls back to
        CoinDCX 24h volume when CoinGecko is down.

        Returns (coins, how they were ranked)."""
        extra = self.config.btc_strength.get("exclude", [])
        listed = [c for c in self.usdt_coins()
                  if not universe_mod.is_pegged(c, extra)]
        ranked = marketcap.top_symbols(n, among=set(listed))
        if not ranked:
            return listed[:n], "24h volume on CoinDCX (CoinGecko did not answer)"
        if len(ranked) < n:
            # CoinGecko stopped early (rate limit): top up with the busiest rest.
            have = set(ranked)
            extra_coins = [c for c in listed if c not in have][:n - len(ranked)]
            return (ranked + extra_coins,
                    f"market cap (CoinGecko) for {len(ranked)}, "
                    f"24h volume on CoinDCX for the other {len(extra_coins)}")
        return ranked, "market cap (CoinGecko)"

    # -- liquidation heatmap -------------------------------------------------
    def futures(self) -> BinanceFutures:
        """Binance USDT-M futures data (lazy, shared for its short cache)."""
        if self._futures is None:
            self._futures = BinanceFutures()
        return self._futures

    def liquidation_coins(self, n: int = 10) -> dict[str, str]:
        """Coin -> Binance perpetual for the ``n`` biggest coins by market cap
        (BTC first), without stablecoins and wrapped tokens."""
        perps = self.futures().perpetuals()
        extra = self.config.btc_strength.get("exclude", [])
        pool = {c for c in perps if not universe_mod.is_pegged(c, extra)}
        ranked = marketcap.top_symbols(n, among=pool) or [
            c for c in ("BTC", "ETH", "BNB", "XRP", "SOL", "DOGE", "ADA", "TRX",
                        "LINK", "AVAX") if c in pool][:n]
        return {c: perps[c] for c in ranked}

    def liquidation_map(self, symbol: str,
                        range_key: str = "1d") -> liquidation_mod.LiqMap:
        """Estimated liquidation levels for a Binance perpetual over a range
        in :data:`liquidation.RANGES` (12h .. 30d)."""
        period, n = liquidation_mod.RANGES[range_key]
        fut = self.futures()
        params = liquidation_mod.LiqParams.from_config(
            self.config.raw.get("liquidation", {}))
        return liquidation_mod.build(fut.klines(symbol, period, n),
                                     fut.open_interest(symbol, period, n + 1),
                                     params)

    def market_read(self, n: int = 10) -> list[market_read_mod.CoinRead]:
        """Rules-based short-term lean for BTC and the top ``n`` coins, from
        1h candles, open interest, funding and the 1d / 7d liquidation maps."""
        from concurrent.futures import ThreadPoolExecutor

        fut = self.futures()
        funding = fut.funding_rates()

        def one(item: tuple[str, str]) -> market_read_mod.CoinRead | None:
            coin, symbol = item
            try:
                return market_read_mod.read_coin(
                    coin, symbol, fut.klines(symbol, "1h", 200),
                    fut.open_interest(symbol, "1h", 30),
                    funding.get(symbol, 0.0),
                    self.liquidation_map(symbol, "1d"),
                    self.liquidation_map(symbol, "7d"))
            except Exception:                  # one bad coin must not sink the list
                return None

        with ThreadPoolExecutor(max_workers=6) as pool:
            reads = list(pool.map(one, self.liquidation_coins(n).items()))
        return [r for r in reads if r is not None]
