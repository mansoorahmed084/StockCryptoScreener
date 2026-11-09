"""Market Desk settings (market_desk/desk.yaml) and symbol helpers."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from backend.chart.symbols import parse

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DESK_YAML = Path(__file__).with_name("desk.yaml")
MARKETS = ("crypto", "india", "us")
MARKET_NAMES = {"crypto": "Crypto", "india": "India", "us": "US"}
_INDIA_YAHOO = ("^NSE", "^CNX", "^BSE", "NIFTY")


def to_symbol(market: str, item: str) -> str:
    """A watchlist entry as a TradingView-style symbol."""
    item = str(item).strip().upper()
    if ":" in item:
        return parse(item).full
    if market == "crypto":
        return f"BINANCE:{item}USDT"
    if market == "india":
        return f"NSE:{item}"
    return f"YAHOO:{item}"


def market_of(symbol: str) -> str:
    """crypto | india | us"""
    sym = parse(symbol)
    if sym.is_crypto:
        return "crypto"
    ys = sym.yahoo_symbol.upper()
    if sym.exchange in ("NSE", "BSE") or ys.endswith((".NS", ".BO")) \
            or ys.startswith(_INDIA_YAHOO):
        return "india"
    return "us"


def short(symbol: str) -> str:
    """BINANCE:SOLUSDT -> SOL, NSE:RELIANCE -> RELIANCE, NASDAQ:AAPL -> AAPL."""
    sym = parse(symbol)
    if sym.market in ("perp", "spot"):
        base, quote = sym.pair
        return base if quote == "USDT" else f"{base}/{quote}"
    return sym.ticker


@dataclass
class Settings:
    raw: dict
    path: Path = DESK_YAML
    _watch: dict | None = field(default=None, repr=False)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Settings":
        p = Path(path) if path else DESK_YAML
        with open(p, encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh) or {}, p)

    def section(self, name: str) -> dict:
        return dict(self.raw.get(name) or {})

    def _symbols(self, key: str) -> dict[str, list[str]]:
        src = self.raw.get(key) or {}
        out: dict[str, list[str]] = {m: [] for m in MARKETS}
        for market in MARKETS:
            for item in src.get(market) or []:
                try:
                    s = to_symbol(market, item)
                except ValueError as exc:
                    log.warning("desk.yaml %s.%s: %s", key, market, exc)
                    continue
                if s not in out[market]:
                    out[market].append(s)
        return out

    @property
    def watch(self) -> dict[str, list[str]]:
        if self._watch is None:
            self._watch = self._symbols("watchlist")
            name = str(self.raw.get("chart_watchlist") or "").strip()
            if name:
                for s in chart_watchlist(name):
                    m = market_of(s)
                    if s not in self._watch[m]:
                        self._watch[m].append(s)
        return self._watch

    @property
    def control(self) -> dict[str, list[str]]:
        return self._symbols("control")

    def watch_all(self) -> list[str]:
        return [s for m in MARKETS for s in self.watch[m]]

    def fee(self, market: str) -> float:
        return float(self.section("fees").get(market, 0.1)) / 100

    @property
    def slippage(self) -> float:
        return float(self.raw.get("slippage", 0.05)) / 100

    @property
    def backtest(self) -> dict:
        cfg = {"years": 5, "order_bars": 3, "max_hold": 20, "min_trades": 30,
               "min_exp_r": 0.05, "min_pf": 1.1, "recent_years": 1}
        cfg.update(self.section("backtest"))
        return cfg

    @property
    def rules(self) -> dict[str, dict]:
        """Enabled rules -> their settings."""
        return {k: dict(v or {}) for k, v in self.section("rules").items()
                if (v or {}).get("enabled", True)}

    @property
    def paper(self) -> dict:
        cfg = {"start_equity": 100000, "risk_pct": 1.0, "max_position_pct": 20,
               "max_open": 5, "max_per_market": 3, "max_total_risk_pct": 5,
               "max_new_per_day": 3, "max_new_plans": 5}
        cfg.update(self.section("paper"))
        return cfg

    @property
    def db_path(self) -> Path:
        return ROOT / "data_cache" / "market_desk.db"

    @property
    def cache_dir(self) -> Path:
        return ROOT / "data_cache" / "market_desk" / "candles"


def chart_watchlist(name: str) -> list[str]:
    """Symbols of one Chart Workspace watchlist (read-only). [] if missing."""
    try:
        from backend.chart.store import ChartStore
        store = ChartStore(ROOT / "data_cache" / "chart.db")
        list_id = store.list_id(name)
        if list_id is None:
            log.warning("no Chart Workspace watchlist named %r", name)
            return []
        out = []
        for item in store.get_list(list_id)["items"]:
            s = item["symbol"]
            if s.startswith("###"):
                continue
            sym = parse(s)
            if sym.market != "dominance":
                out.append(sym.full)
        return out
    except Exception as exc:   # the desk must start even if chart.db is odd
        log.warning("reading Chart Workspace watchlist %r failed: %s", name, exc)
        return []
