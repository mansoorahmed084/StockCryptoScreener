import httpx

from backend.data import marketcap
from backend.data.ohlcv import OHLCVService
from backend.config import load_config
from backend.screener import universe
from backend.watchlists import WatchlistStore, parse_symbols
from .util import FakeAdapter, make_ohlcv


def test_parse_symbols_handles_exchange_tickers():
    text = "BINANCE:SOLUSDT, solusdt.p SOL/USDT B-DOGE_USDT\nWBTC PYUSD ethusdt " \
           "COINBASE:BTCUSD BINANCE:WBTCBTC pepe"
    assert parse_symbols(text) == ["SOL", "DOGE", "WBTC", "PYUSD", "ETH", "BTC", "PEPE"]


def test_store_saves_replaces_and_deletes(tmp_path):
    store = WatchlistStore(tmp_path / "sub" / "watchlists.json")
    assert store.load() == {}
    assert store.save(" Alts ", ["sol", "ETH", "sol"]) == ["SOL", "ETH"]
    store.save("Memes", ["PEPE"])
    store.save("Alts", ["LINK"])
    assert store.load() == {"Alts": ["LINK"], "Memes": ["PEPE"]}
    store.delete("Memes")
    assert store.load() == {"Alts": ["LINK"]}


def test_is_pegged_drops_stablecoins_and_named_wrappers():
    assert universe.is_pegged("USDC") and universe.is_pegged("PYUSD")
    assert universe.is_pegged("WBTC", ["WBTC"])
    assert not universe.is_pegged("SOL", ["WBTC"])


def test_top_symbols_keeps_the_biggest_coin_per_symbol():
    pages = {"1": [{"symbol": "btc"}, {"symbol": "eth"}, {"symbol": "u"}],
             "2": [{"symbol": "u"}, {"symbol": "sol"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[request.url.params["page"]])
    pages["1"] += [{"symbol": f"x{i}"} for i in range(247)]   # a full page
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert marketcap.top_symbols(300, client=client, pause=0)[:3] == ["BTC", "ETH", "U"]
    # Only listed coins count, and later pages are read to find them
    assert marketcap.top_symbols(3, among={"ETH", "U", "SOL"}, client=client,
                                 pause=0) == ["ETH", "U", "SOL"]

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)
    assert marketcap.top_symbols(10, rate_limit_wait=0, client=httpx.Client(
        transport=httpx.MockTransport(down))) == []


def test_bigger_cached_fetch_serves_smaller_timeframes():
    class Counting(FakeAdapter):
        calls = 0

        def fetch_ohlcv(self, coin, quote, timeframe, limit=500):
            Counting.calls += 1
            return super().fetch_ohlcv(coin, quote, timeframe, limit).tail(limit)

    frames = {("SOL", "USDT", "1h"): make_ohlcv([1.0 + i for i in range(1000)])}
    service = OHLCVService(Counting(frames), load_config(), cache_ttl=60)
    assert len(service.get("SOL", "USDT", "4h")) > 0     # fetches 1000 x 1h
    assert len(service.get("SOL", "USDT", "1h")) == 500   # served from that fetch
    assert Counting.calls == 1
