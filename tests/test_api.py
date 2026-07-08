import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from backend.api import app as api
from backend.config import load_config
from backend.screener import regime as regime_mod
from .util import make_ohlcv, matrix_df, trend


class FakeService:
    """Offline stand-in for ScreenerService (no network)."""

    def __init__(self):
        self.config = load_config()

    def universe(self):
        return ["SOL", "BTC", "ETH"]

    def build_matrix(self, coins=None, bases=None, timeframes=None,
                     liquidity_gate=True):
        rows = []
        for tf in ("1h", "4h", "1d", "1w"):
            rows.append({"coin": "SOL", "base": "BTC", "timeframe": tf,
                         "direction": "bull", "strength": 1.6, "rank": 95})
        rows.append({"coin": "BTC", "base": "USDT", "timeframe": "1d",
                     "direction": "bull", "strength": 1.0})
        # an unknown cell keeps its rank as pd.NA — the API must emit null for it
        rows.append({"coin": "DOGE", "base": "USDT", "timeframe": "1d",
                     "direction": "unknown", "strength": float("nan"),
                     "rank": pd.NA})
        return matrix_df(rows)

    def regime(self, df):
        return regime_mod.assess(df, quote="USDT")

    def ratio_frame(self, coin, base, timeframe):
        return make_ohlcv(trend(200, 100, 0.01, noise=0.002, seed=1), timeframe="1d")


client = TestClient(api.app)
api.app.dependency_overrides[api.get_service] = lambda: FakeService()
api._matrix_cache.clear()


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_presets_listed():
    body = client.get("/presets").json()
    assert "full_stack_bull" in body["presets"]


def test_universe():
    body = client.get("/universe").json()
    assert body["coins"] == ["SOL", "BTC", "ETH"]


def test_matrix_cells():
    body = client.get("/matrix").json()
    assert len(body["cells"]) > 0
    assert {"coin", "base", "timeframe", "direction"}.issubset(body["cells"][0])


def test_matrix_pd_na_serialized_as_null():
    body = client.get("/matrix").json()
    doge = [c for c in body["cells"] if c["coin"] == "DOGE"][0]
    assert doge["rank"] is None       # pd.NA must not leak as {'__module__': ...}
    assert doge["strength"] is None   # NaN -> null


def test_filter_full_stack_bull():
    flt = {"logic": "AND", "conditions": [
        {"subject": "*", "base": "BTC", "timeframe": tf,
         "metric": "direction", "operator": "is", "value": "bull"}
        for tf in ("1h", "4h", "1d", "1w")]}
    body = client.post("/filter", json={"filter": flt}).json()
    assert body["matches"] == ["SOL"]


def test_backtest_endpoint():
    body = client.get("/backtest",
                      params={"coin": "SOL", "base": "BTC", "timeframe": "1d"}).json()
    assert body["n"] > 0 and body["mean_fwd"] > 0


def test_chart_endpoint():
    body = client.get("/chart",
                      params={"coin": "SOL", "base": "BTC", "timeframe": "1d"}).json()
    assert len(body["candles"]) == 200
    assert "vumanchu" in body
