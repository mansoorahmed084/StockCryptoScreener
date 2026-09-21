import httpx

from backend.config import load_config
from backend.data.adapters.coindcx import CoinDcxAdapter


def _adapter(ticker):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ticker)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return CoinDcxAdapter(load_config(), client=client, retries=1)


def test_ticker_volume_is_already_in_quote_units():
    # Live values, 2026-09-21: PEPEUSDT volume matched Binance quoteVolume.
    a = _adapter([
        {"market": "PEPEUSDT", "volume": "105887011.7", "last_price": "0.00000493"},
        {"market": "BTCUSDT", "volume": "2375477659.1", "last_price": "86002.58"},
    ])
    vols = a._fetch_quote_volumes()
    assert vols["PEPEUSDT"] == (105887011.7, 0.00000493)   # not x price
    assert vols["BTCUSDT"][0] == 2375477659.1
