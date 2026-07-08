"""REST API for the screener (Phase 4).

    uvicorn backend.api.app:app --reload

Endpoints reuse ScreenerService, so the API, dashboard and CLI share one code
path. Matrix builds are cached briefly to avoid re-fetching on every request.
"""
from __future__ import annotations

import math
import time
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from backend.config import load_config
from backend.indicators.vumanchu import VuManChuCipherB
from backend.screener import filters as filters_mod
from backend.screener import sectors as sectors_mod
from backend.signals.backtest import backtest_signal
from backend.signals.journal import SignalJournal
from backend.service import ScreenerService

app = FastAPI(title="Crypto Relative-Strength Screener API", version="0.1.0")

_service: ScreenerService | None = None
_matrix_cache: dict[tuple, tuple[float, pd.DataFrame]] = {}
_CACHE_TTL = 30.0


def get_service() -> ScreenerService:
    global _service
    if _service is None:
        _service = ScreenerService(load_config())
    return _service


def _jsonable(v):
    """None for NaN/inf/pd.NA so payloads are valid JSON (pd.NA is not a float
    and would otherwise serialize as {'__module__': 'pandas'})."""
    if v is None or v is pd.NA:
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def _clean(records: list[dict]) -> list[dict]:
    """Replace NaN/inf/pd.NA with None so the payload is valid JSON."""
    return [{k: _jsonable(v) for k, v in r.items()} for r in records]


def _matrix(service: ScreenerService, coins, bases, timeframes, gate) -> pd.DataFrame:
    key = (tuple(coins) if coins else None, tuple(bases) if bases else None,
           tuple(timeframes) if timeframes else None, gate)
    now = time.monotonic()
    hit = _matrix_cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    df = service.build_matrix(coins, bases, timeframes, liquidity_gate=gate)
    _matrix_cache[key] = (now, df)
    return df


def _split(value: str | None) -> list[str] | None:
    return [v.strip().upper() for v in value.split(",")] if value else None


class FilterBody(BaseModel):
    filter: dict[str, Any]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/universe")
def universe(service: ScreenerService = Depends(get_service)) -> dict:
    return {"coins": service.universe(), "bases": service.config.bases,
            "timeframes": service.config.timeframes}


@app.get("/matrix")
def matrix(coins: str | None = None, bases: str | None = None,
           timeframes: str | None = None, liquidity_gate: bool = True,
           service: ScreenerService = Depends(get_service)) -> dict:
    df = _matrix(service, _split(coins), _split(bases),
                 [t.strip() for t in timeframes.split(",")] if timeframes else None,
                 liquidity_gate)
    return {"cells": _clean(df.to_dict("records"))}


@app.get("/regime")
def regime(service: ScreenerService = Depends(get_service)) -> dict:
    df = _matrix(service, None, None, None, True)
    reg = service.regime(df)
    return {"label": reg.label, "btc_trend": reg.btc_trend, "breadth": reg.breadth}


@app.get("/sectors")
def sectors(base: str, service: ScreenerService = Depends(get_service)) -> dict:
    df = _matrix(service, None, None, None, True)
    hm = sectors_mod.sector_heatmap(df, service.config, base.upper())
    return {"base": base.upper(),
            "heatmap": _clean(hm.reset_index().to_dict("records")) if not hm.empty
            else []}


@app.get("/presets")
def presets() -> dict:
    return {"presets": list(filters_mod.PRESETS)}


@app.get("/presets/{name}")
def preset_matches(name: str, base: str = "BTC",
                   service: ScreenerService = Depends(get_service)) -> dict:
    if name not in filters_mod.PRESETS:
        raise HTTPException(404, f"unknown preset {name!r}")
    flt = filters_mod.PRESETS[name]()
    df = _matrix(service, None, None, None, True)
    return {"preset": name, "name": flt.name, "matches": sorted(flt.evaluate(df))}


@app.post("/filter")
def evaluate_filter(body: FilterBody,
                    service: ScreenerService = Depends(get_service)) -> dict:
    flt = filters_mod.Filter.from_dict(body.filter)
    df = _matrix(service, None, None, None, True)
    matches = sorted(flt.evaluate(df))
    rows = df[df["coin"].isin(matches)]
    return {"matches": matches, "cells": _clean(rows.to_dict("records"))}


@app.get("/chart")
def chart(coin: str, base: str, timeframe: str, vumanchu: bool = True,
          service: ScreenerService = Depends(get_service)) -> dict:
    frame = service.ratio_frame(coin.upper(), base.upper(), timeframe)
    if frame.empty:
        raise HTTPException(404, "no candles for that pair/timeframe")
    payload: dict[str, Any] = {
        "coin": coin.upper(), "base": base.upper(), "timeframe": timeframe,
        "candles": _clean(frame.reset_index().assign(
            ts=lambda d: d["ts"].astype(str)).to_dict("records")),
    }
    if vumanchu:
        # Signals only on closed candles — the forming candle repaints (plan 4.7).
        res = VuManChuCipherB().compute(frame.iloc[:-1])
        payload["vumanchu"] = {
            "wt1": [_jsonable(float(x)) for x in res.panes.get("wt1", [])],
            "wt2": [_jsonable(float(x)) for x in res.panes.get("wt2", [])],
            "signals": res.signals,
            "markers": [{"ts": str(m.ts), "kind": m.kind, "price": m.price}
                        for m in res.markers],
        }
    return payload


@app.get("/backtest")
def backtest(coin: str, base: str = "BTC", timeframe: str = "1d",
             direction: str = "bull", horizon: int = 10,
             service: ScreenerService = Depends(get_service)) -> dict:
    frame = service.ratio_frame(coin.upper(), base.upper(), timeframe)
    if frame.empty:
        raise HTTPException(404, "no candles for that pair/timeframe")
    params = service.config.classifier_params(timeframe)
    stats = backtest_signal(frame["close"], params, direction=direction,
                            horizon=horizon)
    return stats.as_dict()


@app.get("/journal")
def journal(limit: int = 100) -> dict:
    j = SignalJournal()
    df = j.to_frame(limit=limit)
    j.close()
    return {"signals": _clean(df.to_dict("records"))}
