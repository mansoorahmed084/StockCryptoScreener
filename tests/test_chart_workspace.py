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


# --- stocks (Yahoo) ---------------------------------------------------------
from backend.data import yahoo as yh  # noqa: E402

IST = 19800
D0 = 1790467200          # 2026-09-27 00:00 UTC (a Sunday)


def _yahoo_chart(ts, closes, gmtoffset=IST, first_trade=0):
    return {"chart": {"result": [{
        "meta": {"gmtoffset": gmtoffset, "longName": "Tata Consultancy Services",
                 "firstTradeDate": first_trade, "regularMarketPrice": closes[-1],
                 "chartPreviousClose": closes[0]},
        "timestamp": ts,
        "indicators": {"quote": [{"open": closes, "high": [c + 1 for c in closes],
                                  "low": [c - 1 for c in closes], "close": closes,
                                  "volume": [10] * len(ts)}]}}]}}


def test_yahoo_builds_4h_from_hourly_candles_per_session():
    # Monday NSE 60m candles: 09:15 .. 15:15 IST, then the 15:30 close print.
    mon = D0 + 86400 + 3 * 3600 + 45 * 60                   # 09:15 IST in UTC
    ts = [mon + i * 3600 for i in range(7)] + [mon + 6 * 3600 + 900]
    closes = [100, 101, 102, 103, 104, 105, 106, 107]
    raw = _yahoo_chart(ts, closes)["chart"]["result"][0]
    bars = yh.Yahoo._bars(raw, "4h", 4)
    assert [b["time"] for b in bars] == [mon, mon + 4 * 3600]
    assert bars[0]["close"] == 103 and bars[0]["volume"] == 40
    # the off-grid 15:30 print folds into the last candle
    assert bars[1]["close"] == 107 and bars[1]["high"] == 108 and bars[1]["volume"] == 40


def test_yahoo_daily_candles_sit_on_the_exchange_date():
    mon_open = D0 + 86400 + 3 * 3600 + 45 * 60
    raw = _yahoo_chart([mon_open, mon_open + 86400], [10, 11])["chart"]["result"][0]
    assert [b["time"] for b in yh.Yahoo._bars(raw, "1d", 1)] == [D0 + 86400, D0 + 2 * 86400]
    # A US close stamped after midnight UTC still lands on its New York date.
    ny = yh.Yahoo._bars(_yahoo_chart([D0 + 86400 + 13 * 3600 + 1800], [5],
                                     gmtoffset=-14400)["chart"]["result"][0], "1d", 1)
    assert ny[0]["time"] == D0 + 86400
    monthly = yh.Yahoo._bars(_yahoo_chart([D0], [5])["chart"]["result"][0], "1M", 1)
    assert monthly[0]["time"] == 1788220800          # 2026-09-01


def test_yahoo_search_keeps_india_and_us_listings():
    quotes = [
        {"symbol": "TCS.NS", "exchange": "NSI", "quoteType": "EQUITY", "longname": "TCS"},
        {"symbol": "TCS.BO", "exchange": "BSE", "quoteType": "EQUITY", "shortname": "TCS"},
        {"symbol": "TCS", "exchange": "NYQ", "quoteType": "EQUITY", "shortname": "Container"},
        {"symbol": "TCS.DE", "exchange": "GER", "quoteType": "EQUITY", "shortname": "x"},
        {"symbol": "TCSX", "exchange": "NMS", "quoteType": "OPTION", "shortname": "x"},
    ]

    def handler(request):
        return httpx.Response(200, json={"quotes": quotes})
    y = yh.Yahoo(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert [r["symbol"] for r in y.search("tcs")] == ["NSE:TCS", "BSE:TCS", "NYSE:TCS"]
    assert [r["symbol"] for r in y.search("tcs", market="us")] == ["NYSE:TCS"]
    assert [r["symbol"] for r in y.search("tcs", market="india")] == ["NSE:TCS", "BSE:TCS"]


def test_stock_candles_and_quotes_through_market_data():
    now = int(__import__("time").time())
    seen = []

    def handler(request):
        seen.append(request)
        ts = [now - 86400 * i for i in range(5, 0, -1)]
        return httpx.Response(200, json=_yahoo_chart(ts, [1, 2, 3, 4, 5], first_trade=1))
    y = yh.Yahoo(client=httpx.Client(transport=httpx.MockTransport(handler)))
    m = MarketData(client=httpx.Client(transport=httpx.MockTransport(binance_handler([]))),
                   futures=FakeFutures(), yahoo=y)
    c = m.candles("NSE:TCS", "1d", limit=3)
    assert c.delayed and len(c.bars) == 3 and c.more
    assert seen[-1].url.path == "/v8/finance/chart/TCS.NS"
    assert seen[-1].url.params["interval"] == "1d"
    with pytest.raises(ValueError):
        m.candles("NSE:TCS", "3m")
    assert m.describe(m.resolve("NSE:TCS")) == "Tata Consultancy Services"
    q = m.quotes(["NSE:TCS"])["NSE:TCS"]
    assert q["last"] == 5 and q["change"] == 4 and q["change_pct"] == 400


# --- watchlists -------------------------------------------------------------
from backend.chart.store import ChartStore  # noqa: E402
from backend.watchlists import WatchlistStore  # noqa: E402


def test_chart_store_lists_items_sections_and_flags(tmp_path):
    store = ChartStore(tmp_path / "chart.db")
    lid = store.create_list("Alts", ["BINANCE:SOLUSDT.P", "nse:tcs", "BINANCE:SOLUSDT.P"])
    assert [i["symbol"] for i in store.get_list(lid)["items"]] == ["BINANCE:SOLUSDT.P", "NSE:TCS"]
    with pytest.raises(ValueError):
        store.create_list("Alts")
    got = store.set_items(lid, [{"symbol": "###Majors"}, {"symbol": "NSE:TCS", "flag": "red"},
                                {"symbol": "BINANCE:ETHBTC", "flag": "nope"}, {"symbol": "###"}])
    assert [(i["symbol"], i["flag"]) for i in got["items"]] == [
        ("###Majors", None), ("NSE:TCS", "red"), ("BINANCE:ETHBTC", None)]
    assert store.lists() == [{"id": lid, "name": "Alts", "count": 2}]
    store.rename_list(lid, "Majors")
    assert store.get_list(lid)["name"] == "Majors"
    store.delete_list(lid)
    assert store.lists() == []
    store.ensure_default()
    assert store.lists()[0]["name"] == "Watchlist"


def test_coin_view_keeps_stocks_and_sections(tmp_path):
    wl = WatchlistStore(tmp_path / "chart.db")
    lid = wl.chart.create_list("Mixed", ["###A", "BINANCE:SOLUSDT", "NSE:TCS",
                                         "BINANCE:ETHUSDT.P"])
    assert wl.load() == {"Mixed": ["SOL", "ETH"]}
    wl.save("Mixed", ["eth", "DOGE"])
    assert [i["symbol"] for i in wl.chart.get_list(lid)["items"]] == [
        "###A", "NSE:TCS", "BINANCE:ETHUSDT.P", "BINANCE:DOGEUSDT.P"]


def test_old_json_lists_are_copied_in_once(tmp_path):
    old = tmp_path / "watchlists.json"
    old.write_text('{"Memes": ["PEPE", "WIF"]}', encoding="utf-8")
    wl = WatchlistStore(tmp_path / "chart.db")
    wl.import_legacy(old)
    assert wl.load() == {"Memes": ["PEPE", "WIF"]}
    wl.delete("Memes")
    wl.import_legacy(old)                     # not again
    assert wl.load() == {}


def test_watchlist_routes_and_import(md, tmp_path, monkeypatch):
    monkeypatch.setattr(chart_routes, "_market", md)
    monkeypatch.setattr(chart_routes, "_store", ChartStore(tmp_path / "chart.db"))
    client = TestClient(api.app)
    lst = client.post("/api/chart/watchlists", json={"name": "Scalps"}).json()
    assert client.post("/api/chart/watchlists", json={"name": "Scalps"}).status_code == 400
    res = client.post(f"/api/chart/watchlists/{lst['id']}/import", json={
        "text": "###MAJORS, BINANCE:SOLUSDT.P, pepe\nETHBTC nothing!"}).json()
    assert [i["symbol"] for i in res["items"]] == [
        "###MAJORS", "BINANCE:SOLUSDT.P", "BINANCE:1000PEPEUSDT.P", "BINANCE:ETHBTC"]
    assert res["skipped"] == ["nothing!"]
    items = res["items"][::-1]
    got = client.put(f"/api/chart/watchlists/{lst['id']}/items", json={"items": items}).json()
    assert got["items"][0]["symbol"] == "BINANCE:ETHBTC"
    client.put(f"/api/chart/watchlists/{lst['id']}/active")
    assert client.get("/api/chart/watchlists").json()["active"] == lst["id"]
    assert client.delete(f"/api/chart/watchlists/{lst['id']}").status_code == 204
    assert client.get(f"/api/chart/watchlists/{lst['id']}").status_code == 404
