"""Screener snapshots for the cloud page.

Streamlit Cloud runs in the US, where Binance refuses connections, so the
cloud page cannot run the screener itself. The EC2 server (Mumbai) runs
the screener's own code every 30 minutes and saves the results to the
desk database; the "Screener" page in market_desk/app.py reads them.

  rs        the relative-strength matrix (every coin x base x timeframe)
            and the market regime header, as on the main screener page
  btc       BTC Strength for the top 50 coins by market cap
  patterns  the Pattern Scanner over the top 50 Binance perpetuals,
            15m / 1h / 4h / 1d, every pattern
  liq       liquidation levels (1d and 7d) and the market read for BTC and
            the top 10 coins, as on the Liquidation Heatmap page

Read-only use of the screener: nothing here trades.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import pandas as pd

log = logging.getLogger(__name__)

PARTS = ("rs", "btc", "patterns", "liq")
PATTERN_TFS = ["15m", "1h", "4h", "1d"]
LIQ_RANGES = ("1d", "7d")


def frame_json(df: pd.DataFrame) -> str:
    return df.to_json(orient="split", date_format="iso", default_handler=str)


def frame_from(text: str) -> pd.DataFrame:
    from io import StringIO
    return pd.read_json(StringIO(text), orient="split")


def build_rs(svc) -> dict:
    cfg = svc.config
    df = svc.build_matrix(svc.universe(), cfg.bases, cfg.timeframes, liquidity_gate=True)
    reg = svc.regime(df)
    keep = [c for c in ("coin", "base", "timeframe", "direction", "strength") if c in df]
    return {"bases": list(cfg.bases), "timeframes": list(cfg.timeframes),
            "regime": {"label": reg.label, "btc_trend": dict(reg.btc_trend),
                       "breadth": {k: float(v) for k, v in reg.breadth.items()}},
            "matrix": frame_json(df[keep])}


def build_btc(svc, n: int = 50) -> dict:
    coins, source = svc.top_coins(n)
    tfs = list(svc.config.btc_strength.get("timeframes") or ["1h", "4h", "1d", "1w", "1M"])
    board = svc.btc_board(list(coins), tfs, liquidity_gate=True)
    return {"coins_from": source, "timeframes": tfs, "benchmark": board.benchmark,
            "btc_dominance_pct": board.btc_dominance_pct, "order": list(board.order),
            "strength": frame_json(board.strength), "trends": frame_json(board.trends),
            "summary": frame_json(board.summary())}


def build_patterns(svc, n: int = 50) -> dict:
    from backend.screener import pattern_scan as ps
    coins = svc.liquidation_coins(n)
    df = ps.scan(svc.futures().klines, coins, PATTERN_TFS, patterns=ps.ALL_PATTERNS)
    return {"coins": len(coins), "timeframes": PATTERN_TFS, "table": frame_json(df)}


def build_liq(svc, n: int = 10) -> dict:
    from backend.screener import liquidation as liq
    coins = svc.liquidation_coins(n)
    overview = {}
    for rk in LIQ_RANGES:
        def one(item: tuple[str, str]) -> dict:
            coin, symbol = item
            try:
                row = liq.summary(svc.liquidation_map(symbol, rk))
            except Exception as exc:          # one bad symbol must not sink the table
                row = {"error": str(exc)}
            return {"coin": coin, "symbol": symbol, **row}
        with ThreadPoolExecutor(max_workers=6) as pool:
            overview[rk] = frame_json(pd.DataFrame(list(pool.map(one, coins.items()))))
    reads = [asdict(r) for r in svc.market_read(n)]
    return {"overview": overview, "market_read": reads}


BUILDERS = {"rs": build_rs, "btc": build_btc, "patterns": build_patterns, "liq": build_liq}


def run(store, svc=None, parts: tuple[str, ...] = PARTS) -> dict[str, str]:
    """Build and save each part; one failing part does not stop the others."""
    if svc is None:
        from backend.config import load_config
        from backend.service import ScreenerService
        svc = ScreenerService(load_config())
    out: dict[str, str] = {}
    for part in parts:
        t0 = time.time()
        try:
            store.save_snapshot(part, BUILDERS[part](svc))
            out[part] = f"ok in {time.time() - t0:.0f}s"
        except Exception as exc:
            log.exception("screener snapshot %s failed", part)
            out[part] = f"failed: {type(exc).__name__}: {exc}"[:200]
    store.set_meta("last_screener_snap", str(int(time.time())))
    return out
