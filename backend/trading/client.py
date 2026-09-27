"""Signed CoinDCX futures client (docs.coindcx.com, "Futures End Points").

Every private call is a JSON body carrying a millisecond ``timestamp``, signed
with HMAC-SHA256 of the exact bytes sent. The server rejects a body more than
10 s old, so a body is built and signed right before it is sent.

Reads retry on network and 5xx errors. Writes (create, cancel, exit, leverage,
TP/SL) are sent once: after a timeout the order may or may not exist, and a
blind retry could open a second position. The manager re-reads state instead.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

API_BASE = "https://api.coindcx.com"
FUTURES = "/exchange/v1/derivatives/futures"
PRICES_URL = "https://public.coindcx.com/market_data/v3/current_prices/futures/rt"
MARGIN = "INR"
MIN_GAP_S = 0.07          # CoinDCX allows 16 requests/s; stay under it


class CoinDcxError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"CoinDCX {status}: {message}")
        self.status = status
        self.message = message


class UnknownOutcome(Exception):
    """A write was sent but no answer came back: it may have gone through."""


class FuturesClient:
    def __init__(self, key: str = "", secret: str = "", *,
                 client: httpx.Client | None = None, timeout: float = 10.0,
                 retries: int = 3):
        self._key = key
        self._secret = secret.encode()
        self._http = client or httpx.Client(timeout=timeout, headers={
            "User-Agent": "crypto-rs-screener/0.1"})
        self._retries = retries
        self._lock = threading.Lock()
        self._last = 0.0

    @classmethod
    def from_env(cls, **kw) -> "FuturesClient":
        from backend.alerts.telegram import load_dotenv
        load_dotenv()
        return cls(os.environ.get("COINDCX_API_KEY", "").strip(),
                   os.environ.get("COINDCX_API_SECRET", "").strip(), **kw)

    @property
    def has_keys(self) -> bool:
        return bool(self._key and self._secret)

    def __repr__(self) -> str:
        return f"FuturesClient(keys={'set' if self.has_keys else 'missing'})"

    # -- transport -------------------------------------------------------------
    def _throttle(self) -> None:
        with self._lock:
            wait = self._last + MIN_GAP_S - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def _send(self, method: str, path: str, body: dict[str, Any] | None,
              signed: bool) -> Any:
        self._throttle()
        url = path if path.startswith("http") else API_BASE + path
        if not signed:
            resp = self._http.request(method, url)
        else:
            if not self.has_keys:
                raise CoinDcxError(0, "COINDCX_API_KEY / COINDCX_API_SECRET are not set in .env")
            payload = json.dumps({**(body or {}), "timestamp": int(time.time() * 1000)},
                                 separators=(",", ":"))
            sig = hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
            resp = self._http.request(method, url, content=payload, headers={
                "Content-Type": "application/json",
                "X-AUTH-APIKEY": self._key,
                "X-AUTH-SIGNATURE": sig,
            })
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("message") or resp.text
            except ValueError:
                msg = resp.text
            raise CoinDcxError(resp.status_code, str(msg)[:300])
        return resp.json()

    def _read(self, method: str, path: str, body: dict | None = None,
              signed: bool = True) -> Any:
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                return self._send(method, path, body, signed)
            except CoinDcxError as exc:
                if exc.status < 500:
                    raise
                last = exc
            except (httpx.HTTPError, ValueError) as exc:
                last = exc
            log.warning("%s %s failed (attempt %d/%d): %s", method, path,
                        attempt + 1, self._retries, last)
            time.sleep(0.5 * 2 ** attempt)
        assert last is not None
        raise last

    def _write(self, path: str, body: dict) -> Any:
        try:
            return self._send("POST", path, body, True)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise UnknownOutcome(f"{path}: {exc}") from exc

    # -- public market data ----------------------------------------------------
    def active_pairs(self) -> list[str]:
        return list(self._read(
            "GET", f"{FUTURES}/data/active_instruments?margin_currency_short_name[]={MARGIN}",
            signed=False))

    def instrument(self, pair: str) -> dict:
        data = self._read(
            "GET", f"{FUTURES}/data/instrument?pair={pair}&margin_currency_short_name={MARGIN}",
            signed=False)
        return data.get("instrument", data)

    def prices(self) -> dict[str, dict]:
        """pair -> {"ls": last price, "mp": mark price, ...}"""
        return dict(self._read("GET", PRICES_URL, signed=False).get("prices", {}))

    def candles(self, pair: str, minutes: int, lookback_s: int = 4 * 3600) -> list[dict]:
        """CoinDCX futures candles, oldest first (the last one may still be forming).
        The docs list 1, 5, 60 and 1D; 15 works too (checked 2026-09-27)."""
        now = int(time.time())
        data = self._read("GET", "https://public.coindcx.com/market_data/candlesticks"
                          f"?pair={pair}&from={now - lookback_s}&to={now}"
                          f"&resolution={minutes}&pcode=f", signed=False)
        return sorted(data.get("data", []), key=lambda c: c["time"])

    def spot_usdt_inr(self) -> float:
        for t in self._read("GET", "/exchange/ticker", signed=False):
            if t.get("market") == "USDTINR":
                return float(t["last_price"])
        raise CoinDcxError(0, "no USDTINR ticker")

    # -- private reads ---------------------------------------------------------
    def conversion_rate(self) -> float:
        """INR per USDT that CoinDCX uses for INR-margined futures."""
        rows = self._read("GET", "/api/v1/derivatives/futures/data/conversions", {})
        for r in rows:
            if r.get("margin_currency_short_name") == MARGIN:
                return float(r["conversion_price"])
        raise CoinDcxError(0, "no INR conversion price in the response")

    def wallets(self) -> list[dict]:
        return list(self._read("GET", f"{FUTURES}/wallets", {}))

    def positions(self, pairs: list[str] | None = None) -> list[dict]:
        body: dict[str, Any] = {"page": "1", "size": "100",
                                "margin_currency_short_name": [MARGIN]}
        if pairs:
            body["pairs"] = ",".join(pairs)
        return list(self._read("POST", f"{FUTURES}/positions", body))

    def orders(self, status: str = "open,partially_filled,untriggered") -> list[dict]:
        out: list[dict] = []
        for side in ("buy", "sell"):
            out += self._read("POST", f"{FUTURES}/orders", {
                "status": status, "side": side, "page": "1", "size": "100",
                "margin_currency_short_name": [MARGIN]})
        return out

    def transactions(self, page: int = 1, size: int = 100) -> list[dict]:
        """Newest first. CoinDCX answers 422 to a page size above 100."""
        return list(self._read("POST", f"{FUTURES}/positions/transactions", {
            "stage": "all", "page": str(page), "size": str(min(size, 100)),
            "margin_currency_short_name": [MARGIN]}))

    # -- writes ----------------------------------------------------------------
    def update_leverage(self, pair: str, leverage: int) -> Any:
        return self._write(f"{FUTURES}/positions/update_leverage", {
            "pair": pair, "leverage": str(leverage), "margin_currency_short_name": MARGIN})

    def create_order(self, order: dict) -> dict:
        resp = self._write(f"{FUTURES}/orders/create",
                           {"order": {**order, "margin_currency_short_name": MARGIN}})
        return resp[0] if isinstance(resp, list) else resp

    def cancel_order(self, order_id: str) -> Any:
        return self._write(f"{FUTURES}/orders/cancel", {"id": order_id})

    def create_tpsl(self, position_id: str, *, stop_loss: float | None = None,
                    take_profit: float | None = None) -> dict:
        body: dict[str, Any] = {"id": position_id}
        if take_profit is not None:
            body["take_profit"] = {"stop_price": str(take_profit),
                                   "order_type": "take_profit_market"}
        if stop_loss is not None:
            body["stop_loss"] = {"stop_price": str(stop_loss), "order_type": "stop_market"}
        return self._write(f"{FUTURES}/positions/create_tpsl", body)

    def exit_position(self, position_id: str) -> Any:
        return self._write(f"{FUTURES}/positions/exit", {"id": position_id})

    def cancel_position_orders(self, position_id: str) -> Any:
        return self._write(f"{FUTURES}/positions/cancel_all_open_orders_for_position",
                           {"id": position_id})

    def cancel_all_orders(self) -> Any:
        return self._write(f"{FUTURES}/positions/cancel_all_open_orders",
                           {"margin_currency_short_name": [MARGIN]})
