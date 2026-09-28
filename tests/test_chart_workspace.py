"""Chart workspace: symbols, candles and the /api/chart routes (offline)."""
import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import app as api
from backend.api import chart_routes
from backend.chart import symbols as sy
from backend.chart.market_data import MarketData


class FakeFutures:
    def perpetuals(self):
        return {"BTC": "BTCUSDT", "PEPE": "1000PEPEUSDT", "SOL": "SOLUSDT"}


def _kline(t_ms, close):
    return [t_ms, str(close), str(close + 1), str(close - 1), str(close), "10",
            t_ms + 59_999, "0", 0, "0", "0", "0"]


def binance_handler(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if path == "/api/v3/exchangeInfo":
            return httpx.Response(200, json={"symbols": [
                {"symbol": "SOLUSDT", "baseAsset": "SOL", "quoteAsset": "USDT"},
                {"symbol": "SOLBTC", "baseAsset": "SOL", "quoteAsset": "BTC"},
                {"symbol": "ETHBTC", "baseAsset": "ETH", "quoteAsset": "BTC"},
                {"symbol": "SOLEUR", "baseAsset": "SOL", "quoteAsset": "EUR"}]})
        if path.endswith("/klines"):
            limit = int(request.url.params["limit"])
            end = int(request.url.params.get("endTime", 10_000 * 60_000))
            first = end - limit * 60_000 + 1
            rows = [_kline(t, 100 + i) for i, t in
                    enumerate(range(max(first, 0) // 60_000 * 60_000, end, 60_000))]
            return httpx.Response(200, json=rows[-limit:])
        if path.endswith("/ticker/24hr"):
            return httpx.Response(200, json=[{"symbol": "SOLUSDT", "lastPrice": "150",
                                              "priceChange": "3", "priceChangePercent": "2"}])
        return httpx.Response(404)
    return handler


@pytest.fixture
def md():
    calls: list[httpx.Request] = []
    client = httpx.Client(transport=httpx.MockTransport(binance_handler(calls)))
    m = MarketData(client=client, futures=FakeFutures())
    m.calls = calls
    return m


def test_parse_symbols_in_every_form():
    assert sy.parse("binance:btcusdt.p") == sy.ChartSymbol("BINANCE", "BTCUSDT.P")
    assert sy.parse("BTCUSDT.P").market == "perp"
    assert sy.parse("ETHBTC").market == "spot"
    assert sy.parse("BTC.D").full == "CRYPTOCAP:BTC.D"
    assert sy.parse("RELIANCE.NS").full == "NSE:RELIANCE"
    assert sy.parse("500325.BO").yahoo_symbol == "500325.BO"
    assert sy.parse("NSE:NIFTY").yahoo_symbol == "^NSEI"
    assert sy.parse("^GSPC").full == "SP:SPX"
    with pytest.raises(ValueError):
        sy.parse("AAPL")              # a bare stock ticker needs its exchange
    assert sy.parse("NASDAQ:AAPL").yahoo_symbol == "AAPL"


def test_drawing_keys_share_spot_and_perp_legs_only():
    assert sy.parse("SOLUSDT.P").drawing_key == sy.parse("BINANCE:SOLUSDT").drawing_key
    assert sy.parse("SOLBTC").drawing_key != sy.parse("SOLUSDT").drawing_key
    assert sy.parse("NSE:TCS").drawing_key == "NSE:TCS"
    assert sy.parse("1000PEPEUSDT.P").coin == "PEPE"


def test_yahoo_symbols_map_to_exchanges():
    assert sy.from_yahoo("TCS.NS").full == "NSE:TCS"
    assert sy.from_yahoo("AAPL", "NMS").full == "NASDAQ:AAPL"
    assert sy.from_yahoo("JPM", "NYQ").full == "NYSE:JPM"
    assert sy.from_yahoo("^NSEI").full == "NSE:NIFTY"
    assert sy.is_listed_yahoo("TCS.NS", "NSI")
    assert not sy.is_listed_yahoo("BMW.DE", "GER")


def test_resolve_maps_a_coin_perp_to_the_real_contract(md):
    assert md.resolve("PEPEUSDT.P").full == "BINANCE:1000PEPEUSDT.P"
    with pytest.raises(LookupError):
        md.resolve("DOGEUSDT.P")
    with pytest.raises(LookupError):
        md.resolve("SOLETH")          # not a listed spot pair


def test_candles_page_backwards_by_end_time(md):
    first = md.candles("BTCUSDT.P", "1m", limit=5)
    assert len(first.bars) == 5 and first.more
    times = [b["time"] for b in first.bars]
    assert times == sorted(times)
    older = md.candles("BTCUSDT.P", "1m", end=times[0], limit=5)
    assert older.bars[-1]["time"] < times[0]
    req = md.calls[-1]
    assert req.url.path == "/fapi/v1/klines"
    assert int(req.url.params["endTime"]) == times[0] * 1000 - 1
    md.candles("ETHBTC", "1m", limit=3)
    assert md.calls[-1].url.path == "/api/v3/klines"
    with pytest.raises(ValueError):
        md.candles("BTCUSDT.P", "7m")


def test_search_ranks_perps_first_and_skips_other_quotes(md):
    rows = md.search_crypto("sol")
    assert [r["symbol"] for r in rows] == [
        "BINANCE:SOLUSDT.P", "BINANCE:SOLUSDT", "BINANCE:SOLBTC"]
    assert md.search_crypto("btc.d")[0]["symbol"] == "CRYPTOCAP:BTC.D"


def test_quotes_for_crypto(md):
    q = md.quotes(["BINANCE:SOLUSDT", "BINANCE:ETHBTC", "junk"])
    assert q == {"BINANCE:SOLUSDT": {"last": 150.0, "change": 3.0, "change_pct": 2.0}}


def test_routes(md, monkeypatch):
    monkeypatch.setattr(chart_routes, "_market", md)
    client = TestClient(api.app)
    r = client.get("/api/chart/resolve", params={"symbol": "SOLUSDT.P"}).json()
    assert r["binance"] == "SOLUSDT" and r["drawing_key"] == "BINANCE:SOLUSDT"
    assert r["description"] == "SOL / USDT perpetual"
    c = client.get("/api/chart/candles", params={"symbol": "SOLUSDT.P", "tf": "1m",
                                                 "limit": 3}).json()
    assert len(c["candles"]) == 3 and c["delayed"] is False
    assert client.get("/api/chart/candles", params={"symbol": "X", "tf": "1m"}).status_code == 400
    assert client.get("/api/chart/resolve", params={"symbol": "DOGEUSDT.P"}).status_code == 404
    page = client.get("/workspace")
    assert page.status_code == 200 and "Chart Workspace" in page.text
    assert client.get("/workspace/static/js/main.js").status_code == 200
