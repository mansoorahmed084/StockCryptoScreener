"""Routes for the chart workspace (frontend/chart_app), opened at /workspace."""
from __future__ import annotations

import re
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.chart.market_data import TIMEFRAMES, MarketData
from backend.chart import studies
from backend.chart.store import SECTION, ChartStore
from backend.config import load_config
from backend.data.yahoo import Yahoo
from backend.watchlists import WatchlistStore

APP_DIR = Path(__file__).resolve().parents[2] / "frontend" / "chart_app"

router = APIRouter(prefix="/api/chart", tags=["chart"])

_market: MarketData | None = None


def get_market() -> MarketData:
    global _market
    if _market is None:
        _market = MarketData(yahoo=Yahoo())
    return _market


_store: ChartStore | None = None


def get_store() -> ChartStore:
    """The chart store, with the old JSON watchlists copied in and a starter
    list for a first-time user."""
    global _store
    if _store is None:
        wl = WatchlistStore.from_config(load_config())
        wl.chart.ensure_default()
        _store = wl.chart
    return _store


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


# --- watchlists ---------------------------------------------------------------
class ListBody(BaseModel):
    name: str


class ItemsBody(BaseModel):
    items: list[dict]


class ImportBody(BaseModel):
    text: str


def _store_call(fn, *args):
    try:
        return fn(*args)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/watchlists")
def watchlists(store: ChartStore = Depends(get_store)) -> dict:
    lists = store.lists()
    active = store.get_meta("active_watchlist")
    ids = {w["id"] for w in lists}
    active_id = int(active) if active and int(active) in ids else (lists[0]["id"] if lists else None)
    return {"lists": lists, "active": active_id}


@router.post("/watchlists")
def create_watchlist(body: ListBody, store: ChartStore = Depends(get_store)) -> dict:
    list_id = _store_call(store.create_list, body.name)
    store.set_meta("active_watchlist", str(list_id))
    return store.get_list(list_id)


@router.get("/watchlists/{list_id}")
def get_watchlist(list_id: int, store: ChartStore = Depends(get_store)) -> dict:
    return _store_call(store.get_list, list_id)


@router.put("/watchlists/{list_id}")
def rename_watchlist(list_id: int, body: ListBody,
                     store: ChartStore = Depends(get_store)) -> dict:
    _store_call(store.rename_list, list_id, body.name)
    return store.get_list(list_id)


@router.delete("/watchlists/{list_id}", status_code=204)
def delete_watchlist(list_id: int, store: ChartStore = Depends(get_store)) -> None:
    store.delete_list(list_id)


@router.put("/watchlists/{list_id}/items")
def set_watchlist_items(list_id: int, body: ItemsBody,
                        store: ChartStore = Depends(get_store)) -> dict:
    return _store_call(store.set_items, list_id, body.items)


@router.put("/watchlists/{list_id}/active", status_code=204)
def set_active_watchlist(list_id: int, store: ChartStore = Depends(get_store)) -> None:
    _store_call(store.get_list, list_id)
    store.set_meta("active_watchlist", str(list_id))


@router.post("/watchlists/{list_id}/import")
def import_watchlist(list_id: int, body: ImportBody,
                     store: ChartStore = Depends(get_store),
                     md: MarketData = Depends(get_market)) -> dict:
    """Append pasted symbols (commas, spaces or new lines; ###NAME makes a
    section, as in TradingView's export). Bare tickers are guessed."""
    current = _store_call(store.get_list, list_id)["items"]
    added, skipped = [], []
    for chunk in re.split(r"[,;\n]+", body.text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith(SECTION):
            added.append({"symbol": chunk})
            continue
        for token in chunk.split():
            sym = md.resolve_loose(token)
            if sym is None:
                skipped.append(token)
            else:
                added.append({"symbol": sym.full})
    result = store.set_items(list_id, current + added)
    return {**result, "skipped": skipped}


# --- studies ------------------------------------------------------------------
class BarsBody(BaseModel):
    bars: list[dict]
    params: dict = {}


VUMANCHU_PARAMS = {"channel_len", "average_len", "ma_len", "overbought", "oversold",
                   "mfi_period", "mfi_mult", "pivot_lookback"}


@router.post("/studies/vumanchu")
def vumanchu(body: BarsBody) -> dict:
    """VuManChu Cipher B on the candles the chart has (the screener's code)."""
    params = {k: v for k, v in body.params.items() if k in VUMANCHU_PARAMS}
    try:
        return studies.vumanchu(body.bars[-5000:], **params)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, f"bad candles or settings: {exc}") from exc


@router.get("/analysis")
def analysis(symbol: str, tf: str, n: int = 300, order_blocks: bool = True,
             md: MarketData = Depends(get_market)) -> dict:
    """Auto trendlines, levels, Fibonacci, patterns, swings and daily order
    blocks — what the Chart Patterns page finds — as shapes to draw."""
    try:
        bars = md.candles(symbol, tf, limit=max(60, min(n, 1000))).bars
        daily = md.candles(symbol, "1d", limit=500).bars if order_blocks else []
    except (ValueError, LookupError) as exc:
        raise _bad_symbol(exc) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"data source error: {exc}") from exc
    return studies.analysis(studies.frame(bars), studies.frame(daily) if daily else None)


# --- alerts -------------------------------------------------------------------
# Chart alerts use the screener's alert store and watcher (backend/alerts),
# which read Binance USDT perpetual candles. So a perpetual (or BTC.D, whose
# candles are the BTCDOM contract) can have alerts, and so can a USDT/USDC
# spot pair through its coin's perpetual. Other markets cannot yet.
SPOT_VIA_PERP = ("USDT", "USDC", "FDUSD")


def _service():
    from backend.api.app import get_service   # late: app imports this module
    return get_service()


def alert_target(md: MarketData, sym) -> tuple[str, str] | None:
    """(coin, Binance perpetual) that alerts for this chart symbol watch."""
    if sym.market == "perp":
        return sym.coin, sym.binance_symbol
    if sym.market == "dominance":
        return "BTC.D", sym.binance_symbol
    if sym.market == "spot" and sym.pair[1] in SPOT_VIA_PERP:
        perp = md.futures.perpetuals().get(sym.coin or "")
        if perp:
            return sym.coin, perp
    return None


def _alert_json(a) -> dict:
    from dataclasses import asdict
    return {**asdict(a), "text": a.describe()}


class AlertBody(BaseModel):
    symbol: str
    kind: str
    condition: str
    level: float | None = None
    t1: float | None = None          # line points: chart times (UTC seconds)
    p1: float | None = None
    t2: float | None = None
    p2: float | None = None
    low: float | None = None
    high: float | None = None
    timeframe: str = "1m"
    note: str = ""


@router.get("/alerts")
def chart_alerts(symbol: str, md: MarketData = Depends(get_market)) -> dict:
    from backend.alerts.price_alerts import ACTIVE, TRIGGERED
    try:
        target = alert_target(md, md.resolve(symbol))
    except (ValueError, LookupError) as exc:
        raise _bad_symbol(exc) from exc
    if target is None:
        return {"supported": False, "alerts": []}
    store = _service().alerts()
    week_ago = (time.time() - 7 * 86400) * 1000
    alerts = [a for a in store.list() if a.symbol == target[1] and (
        a.status == ACTIVE or (a.status == TRIGGERED and (a.triggered_ms or 0) > week_ago))]
    return {"supported": True, "coin": target[0], "alerts": [_alert_json(a) for a in alerts]}


@router.post("/alerts")
def create_chart_alert(body: AlertBody, md: MarketData = Depends(get_market)) -> dict:
    from backend.alerts.price_alerts import Alert
    try:
        target = alert_target(md, md.resolve(body.symbol))
    except (ValueError, LookupError) as exc:
        raise _bad_symbol(exc) from exc
    if target is None:
        raise HTTPException(400, "Alerts work on Binance perpetuals, BTC.D and USDT spot "
                                 "pairs for now, not on this market.")
    ms = lambda t: None if t is None else int(t * 1000)
    try:
        alert = Alert(coin=target[0], symbol=target[1], kind=body.kind,
                      condition=body.condition, level=body.level, t1=ms(body.t1), p1=body.p1,
                      t2=ms(body.t2), p2=body.p2, low=body.low, high=body.high,
                      timeframe=body.timeframe, note=body.note.strip()[:200])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    store = _service().alerts()
    alert.id = store.add(alert)
    return _alert_json(alert)


@router.delete("/alerts/{alert_id}", status_code=204)
def delete_chart_alert(alert_id: int) -> None:
    _service().alerts().delete(alert_id)


@router.post("/alerts/check")
def check_chart_alerts() -> dict:
    """Check every active alert once (like an open dashboard page does)."""
    fired = _service().check_alerts()
    return {"fired": [_alert_json(a) for a in fired]}


# --- drawings -----------------------------------------------------------------
@router.get("/drawings")
def drawings(key: str, store: ChartStore = Depends(get_store)) -> dict:
    return {"drawings": store.drawings(key)}


@router.put("/drawings/{drawing_id}")
def save_drawing(drawing_id: str, body: dict,
                 store: ChartStore = Depends(get_store)) -> dict:
    return _store_call(store.save_drawing, drawing_id, body)


@router.delete("/drawings/{drawing_id}", status_code=204)
def delete_drawing(drawing_id: str, store: ChartStore = Depends(get_store)) -> None:
    store.delete_drawing(drawing_id)


@router.delete("/drawings")
def delete_drawings(key: str, store: ChartStore = Depends(get_store)) -> dict:
    return {"deleted": store.delete_drawings(key)}


# --- layouts ------------------------------------------------------------------
class LayoutBody(BaseModel):
    state: dict


@router.get("/layouts")
def layouts(store: ChartStore = Depends(get_store)) -> dict:
    return {"layouts": store.layouts()}


@router.get("/layouts/{name}")
def get_layout(name: str, store: ChartStore = Depends(get_store)) -> dict:
    return _store_call(store.layout, name)


@router.put("/layouts/{name}")
def save_layout(name: str, body: LayoutBody, store: ChartStore = Depends(get_store)) -> dict:
    return _store_call(store.save_layout, name, body.state)


@router.delete("/layouts/{name}", status_code=204)
def delete_layout(name: str, store: ChartStore = Depends(get_store)) -> None:
    store.delete_layout(name)


def install(app: FastAPI) -> None:
    """Add the chart API, the page at /workspace and its static files."""
    app.include_router(router)
    app.mount("/workspace/static", StaticFiles(directory=APP_DIR), name="chart_app")

    @app.get("/workspace", include_in_schema=False)
    def workspace() -> FileResponse:
        return FileResponse(APP_DIR / "index.html",
                            headers={"Cache-Control": "no-cache"})
