from backend.data.futures import FuturesInfo, fetch_futures


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payload):
        self._payload = payload

    def get(self, url):
        return _Resp(self._payload)


def test_fetch_futures_parses_funding():
    payload = {"prices": {
        "B-BTC_USDT": {"fr": 0.0005, "efr": 0.0006, "v": 1000},
        "B-SOL_USDT": {"fr": -0.0003, "efr": -0.0002, "v": 500},
        "B-XYZ_INR": {"fr": 0.001, "v": 1},   # wrong quote, ignored
    }}
    out = fetch_futures("USDT", client=_Client(payload))
    assert set(out) == {"BTC", "SOL"}
    assert out["BTC"].funding_rate == 0.0005
    assert out["BTC"].bias == "longs_pay"
    assert out["SOL"].bias == "shorts_pay"


def test_bias_neutral():
    fi = FuturesInfo("ETH", funding_rate=1e-6, est_funding_rate=0, volume=0)
    assert fi.bias == "neutral"
