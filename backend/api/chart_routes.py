"""Routes for the chart workspace (frontend/chart_app), opened at /workspace."""
from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.chart.market_data import TIMEFRAMES, MarketData

APP_DIR = Path(__file__).resolve().parents[2] / "frontend" / "chart_app"

router = APIRouter(prefix="/api/chart", tags=["chart"])

_market: MarketData | None = None


def get_market() -> MarketData:
    global _market
    if _market is None:
        _market = MarketData()
    return _market


def _bad_symbol(exc: Exception) -> HTTPException:
    return HTTPException(404 if isinstance(exc, LookupError) else 400, str(exc))


@router.get("/config")
def chart_config() -> dict:
    return {"timeframes": list(TIMEFRAMES)}


@router.get("/symbols")
def symbols(q: str = "", market: str = "all",
            md: MarketData = Depends(get_market)) -> dict:
    if market not in ("all", "crypto", "india", "us"):
        raise HTTPException(400, "market must be all, crypto, india or us")
    return {"symbols": md.search(q, market)}


@router.get("/resolve")
def resolve(symbol: str, md: MarketData = Depends(get_market)) -> dict:
    try:
        sym = md.resolve(symbol)
    except (ValueError, LookupError) as exc:
        raise _bad_symbol(exc) from exc
    return {"symbol": sym.full, "exchange": sym.exchange, "ticker": sym.ticker,
            "market": sym.market, "binance": sym.binance_symbol if sym.is_crypto
            else None, "drawing_key": sym.drawing_key, "delayed": sym.delayed,
            "description": md.describe(sym),
            "exchangeName": "Binance" if sym.is_crypto else sym.exchange}


@router.get("/candles")
def candles(symbol: str, tf: str, end: int | None = None, limit: int = 500,
            md: MarketData = Depends(get_market)) -> dict:
    try:
        return md.candles(symbol, tf, end=end, limit=limit).payload()
    except (ValueError, LookupError) as exc:
        raise _bad_symbol(exc) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"data source error: {exc}") from exc


@router.get("/quotes")
def quotes(symbols: str, md: MarketData = Depends(get_market)) -> dict:
    wanted = [s for s in symbols.split(",") if s.strip()][:200]
    try:
        return {"quotes": md.quotes(wanted)}
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"data source error: {exc}") from exc


def install(app: FastAPI) -> None:
    """Add the chart API, the page at /workspace and its static files."""
    app.include_router(router)
    app.mount("/workspace/static", StaticFiles(directory=APP_DIR), name="chart_app")

    @app.get("/workspace", include_in_schema=False)
    def workspace() -> FileResponse:
        return FileResponse(APP_DIR / "index.html",
                            headers={"Cache-Control": "no-cache"})
