"""RESEARCH: headlines and sentiment for the watchlist. Free sources only.

  Google News RSS     headlines for every symbol (no key)
  Finnhub             extra company news for US stocks, only if
                      FINNHUB_API_KEY is in .env (free key at finnhub.io)
  alternative.me      crypto Fear & Greed index (no key)
  Binance futures     funding rate per coin: positive = longs pay shorts,
                      a crowded long side (no key)

Tone is a word count over each headline (rally, beats, upgrade ... vs
plunge, probe, downgrade ...), from -1 to +1. It is rough: it does not
read the article and it misses sarcasm and negation.

"Buzz" is the last 24 hours' headline count divided by the median 24-hour
count of the desk's earlier nights (one per day, up to 14). Google News sends
at most about 100 headlines, newest first, so the feed's own 7-day count is
cut off for busy names and cannot be the base. Buzz stays empty until 3
earlier nights exist. A spike (buzz >= spike_ratio with enough headlines)
flags a story. X and Reddit are not read: both need paid or signed-in API
access now.
"""
from __future__ import annotations

import email.utils
import logging
import os
import re
import statistics
import time
import xml.etree.ElementTree as ET

import httpx

from .settings import MARKETS, Settings, market_of, short
from .store import DeskStore

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
GNEWS = "https://news.google.com/rss/search"
REGION = {"india": ("en-IN", "IN", "IN:en"), "us": ("en-US", "US", "US:en"),
          "crypto": ("en-US", "US", "US:en")}

POS = set("""surge surges surged surging rally rallies rallied rallying soar soars soared
soaring jump jumps jumped gain gains gained rise rises rising rose climb climbs climbed
beat beats upgrade upgrades upgraded bullish bull record outperform outperforms buy
profit profits growth grows grew boost boosts boosted approval approved approves win
wins won partnership expands expansion breakout rebound rebounds rebounded recovers
recovery optimism upbeat inflow inflows""".split())
NEG = set("""plunge plunges plunged plunging fall falls fell falling drop drops dropped
slump slumps slumped crash crashes crashed sink sinks sank tumble tumbles tumbled slide
slides slid decline declines declined downgrade downgrades downgraded bearish bear miss
misses missed loss losses lose loses lawsuit sued sues probe investigation fraud scam
hack hacked exploit ban bans banned delist delisted delisting selloff weak weaker
warning warns layoffs fined penalty default bankruptcy outflow outflows liquidation
liquidations fears fear concern concerns""".split())

COIN_NAMES = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "BNB": "BNB", "XRP": "XRP",
    "LINK": "Chainlink", "AVAX": "Avalanche", "DOGE": "Dogecoin", "ADA": "Cardano",
    "DOT": "Polkadot", "LTC": "Litecoin", "TRX": "Tron", "ATOM": "Cosmos",
    "NEAR": "NEAR Protocol", "FIL": "Filecoin", "ETC": "Ethereum Classic",
    "BCH": "Bitcoin Cash", "XLM": "Stellar", "UNI": "Uniswap", "AAVE": "Aave",
    "SUI": "Sui", "APT": "Aptos", "TON": "Toncoin", "PEPE": "Pepe coin",
    "SHIB": "Shiba Inu", "ARB": "Arbitrum", "OP": "Optimism", "TAO": "Bittensor",
    "FET": "Fetch.ai", "RENDER": "Render token", "WIF": "dogwifhat", "BONK": "Bonk coin",
}
_TAILS = re.compile(r"[,.]?\s+(limited|ltd\.?|inc\.?|incorporated|corporation|corp\.?|"
                    r"co\.?|plc|class [a-c]|holdings?|common stock)$", re.I)


def tone(title: str) -> float:
    words = re.findall(r"[a-z]+", title.lower())
    pos = sum(w in POS for w in words)
    neg = sum(w in NEG for w in words)
    return 0.0 if pos + neg == 0 else (pos - neg) / (pos + neg)


def label(avg_tone: float) -> str:
    return "bullish" if avg_tone > 0.15 else "bearish" if avg_tone < -0.15 else "mixed"


def clean_name(name: str) -> str:
    prev = None
    while prev != name:
        prev, name = name, _TAILS.sub("", name.strip())
    return name


def query_for(symbol: str, name: str | None = None) -> str:
    market = market_of(symbol)
    if market == "crypto":
        coin = short(symbol).split("/")[0]
        return f'"{COIN_NAMES.get(coin, coin)}" crypto'
    nm = clean_name(name or short(symbol))
    return f'"{nm}" stock' if nm else f"{short(symbol)} stock"


def parse_rss(xml_text: str) -> list[dict]:
    """Google News RSS items: title (source cut off), link, source, ts."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("news RSS unreadable: %s", exc)
        return out
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        try:
            ts = int(email.utils.parsedate_to_datetime(item.findtext("pubDate") or "").timestamp())
        except (TypeError, ValueError):
            continue
        if title and link:
            out.append({"title": title, "link": link, "source": source, "ts": ts})
    return out


def google_news(client: httpx.Client, query: str, market: str, days: int = 7) -> list[dict]:
    hl, gl, ceid = REGION.get(market, REGION["us"])
    resp = client.get(GNEWS, params={"q": f"{query} when:{days}d", "hl": hl, "gl": gl,
                                     "ceid": ceid})
    resp.raise_for_status()
    return parse_rss(resp.text)


def finnhub_news(client: httpx.Client, ticker: str, key: str, days: int = 7) -> list[dict]:
    to = time.strftime("%Y-%m-%d", time.gmtime())
    frm = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
    resp = client.get("https://finnhub.io/api/v1/company-news",
                      params={"symbol": ticker, "from": frm, "to": to, "token": key})
    resp.raise_for_status()
    return [{"title": r.get("headline", ""), "link": r.get("url", ""),
             "source": r.get("source", "Finnhub"), "ts": int(r.get("datetime") or 0)}
            for r in resp.json() if r.get("headline") and r.get("url")]


def fear_greed(client: httpx.Client) -> dict | None:
    try:
        resp = client.get("https://api.alternative.me/fng/", params={"limit": 1})
        resp.raise_for_status()
        row = resp.json()["data"][0]
        return {"value": int(row["value"]), "label": row["value_classification"]}
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        log.warning("Fear & Greed failed: %s", exc)
        return None


def funding_rates(client: httpx.Client) -> dict[str, float]:
    """Binance perpetual -> last funding rate in % per 8 hours."""
    try:
        resp = client.get("https://fapi.binance.com/fapi/v1/premiumIndex")
        resp.raise_for_status()
        return {r["symbol"]: float(r["lastFundingRate"]) * 100 for r in resp.json()
                if r.get("lastFundingRate") not in (None, "")}
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("funding rates failed: %s", exc)
        return {}


def summarize(symbol: str, items: list[dict], now: float, cfg: dict,
              history: list[int] | None = None) -> dict:
    """``history``: 24-hour headline counts of earlier nights, one per day."""
    day = [i for i in items if i["ts"] >= now - 86400]
    week = [i for i in items if i["ts"] >= now - cfg.get("days", 7) * 86400]
    base = statistics.median(history) if history and len(history) >= 3 else None
    buzz = len(day) / base if base else None
    tones = [i["tone"] for i in week]
    avg = sum(tones) / len(tones) if tones else 0.0
    spike = buzz is not None and buzz >= cfg.get("spike_ratio", 2.0) \
        and len(day) >= cfg.get("spike_min", 5)
    return {"symbol": symbol, "market": market_of(symbol), "headlines_24h": len(day),
            "headlines_7d": len(week), "buzz": buzz, "tone": float(avg),
            "label": label(avg), "spike": int(spike)}


def research(settings: Settings, data, store: DeskStore, now: float | None = None,
             client: httpx.Client | None = None, pause: float = 0.5) -> dict:
    """Read headlines for every watchlist symbol, save them, and score them."""
    from backend.alerts.telegram import load_dotenv

    now = time.time() if now is None else now
    cfg = settings.section("news")
    days = int(cfg.get("days", 7))
    load_dotenv()
    finnhub_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    own = client is None
    client = client or httpx.Client(timeout=15, headers={"User-Agent": UA},
                                    follow_redirects=True)
    try:
        funding = funding_rates(client) if settings.watch["crypto"] else {}
        fng = fear_greed(client) if settings.watch["crypto"] else None
        rows = []
        for market in MARKETS:
            for sym in settings.watch[market]:
                name = None if market == "crypto" else data.name(sym)
                items: list[dict] = []
                try:
                    items += google_news(client, query_for(sym, name), market, days)
                except httpx.HTTPError as exc:
                    log.warning("news for %s failed: %s", sym, exc)
                if finnhub_key and market == "us":
                    try:
                        items += finnhub_news(client, short(sym), finnhub_key, days)
                    except httpx.HTTPError as exc:
                        log.warning("Finnhub news for %s failed: %s", sym, exc)
                seen, uniq = set(), []
                for i in items:
                    key = i["title"].lower()
                    if key not in seen:
                        seen.add(key)
                        uniq.append({**i, "symbol": sym, "tone": tone(i["title"])})
                store.add_news(uniq)
                row = summarize(sym, uniq, now, cfg, store.daily_counts(sym, int(now)))
                coin = short(sym).split("/")[0]
                row["funding"] = funding.get(f"{coin}USDT") if market == "crypto" else None
                rows.append(row)
                if pause:
                    time.sleep(pause)
        store.save_sentiment(int(now), rows)
        if fng:
            store.set_meta("fear_greed", f"{fng['value']}|{fng['label']}")
        return {"rows": rows, "fear_greed": fng,
                "spikes": [short(r["symbol"]) for r in rows if r["spike"]]}
    finally:
        if own:
            client.close()
