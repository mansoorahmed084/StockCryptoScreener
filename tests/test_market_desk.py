"""Market Desk: offline tests on synthetic candles."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from market_desk import alerts, heatmap, news, paper
from market_desk.backtest import BtTrade, backtest_frame, stats, verdict
from market_desk.data import DAY, complete, frame
from market_desk.notify import Sender, morning_card, night_card
from market_desk.plans import kept_rules, make_plans
from market_desk.rules import Setup, arrays, setup_at, with_indicators
from market_desk.screen import score_frame
from market_desk.settings import Settings, market_of, short, to_symbol
from market_desk.sim import find_fill, manage, r_multiple
from market_desk.store import DeskStore

T0 = 1_700_000_000 // DAY * DAY


def settings(**paper_over) -> Settings:
    raw = {
        "watchlist": {"crypto": ["SOL"], "india": ["RELIANCE"], "us": ["NASDAQ:AAPL"]},
        "control": {"crypto": ["ADA"], "india": [], "us": []},
        "fees": {"crypto": 0.10, "india": 0.12, "us": 0.02},
        "slippage": 0.05,
        "backtest": {"years": 3, "order_bars": 3, "max_hold": 20, "min_trades": 4,
                     "min_exp_r": 0.05, "min_pf": 1.1, "recent_years": 1},
        "rules": {"breakout20": {"target_r": 3}, "pullback20": {"target_r": 2},
                  "rsi_dip": {"target_r": 2}},
        "paper": {"start_equity": 100000, "risk_pct": 1.0, "max_position_pct": 20,
                  "max_open": 5, "max_per_market": 3, "max_total_risk_pct": 5,
                  "max_new_per_day": 3, "max_new_plans": 5, **paper_over},
        "notify": {"telegram": True},
    }
    return Settings(raw)


def trend_bars(n: int, drift: float, seed: int = 1, start: float = 100.0,
               noise: float = 0.02) -> list[dict]:
    rng = np.random.RandomState(seed)
    closes = start * np.exp(np.cumsum(drift + rng.normal(0, noise, n)))
    bars, prev = [], start
    for i, c in enumerate(closes):
        o = prev
        h = max(o, c) * (1 + abs(rng.normal(0, 0.01)))
        lo = min(o, c) * (1 - abs(rng.normal(0, 0.01)))
        bars.append({"time": T0 + i * DAY, "open": float(o), "high": float(h),
                     "low": float(lo), "close": float(c), "volume": 1000.0 + i})
        prev = c
    return bars


def bar(day: int, o, h, lo, c):
    return {"time": T0 + day * DAY, "open": o, "high": h, "low": lo, "close": c,
            "volume": 1.0}


class FakeSender(Sender):
    def __init__(self):
        self.enabled = True
        self.sent: list[str] = []

    def send(self, html: str) -> bool:
        self.sent.append(html)
        return True


class FakeData:
    def __init__(self, bars: dict[str, list[dict]] | None = None, quotes=None):
        self.bars = bars or {}
        self._quotes = quotes or {}

    def history(self, symbol, years=6.0):
        return frame(self.bars[symbol])

    def recent(self, symbol, since, now=None):
        return [b for b in self.bars[symbol] if b["time"] >= since]

    def last_bars(self, symbol, n=40):
        return self.bars[symbol][-n:]

    def quotes(self, symbols):
        return {s: self._quotes[s] for s in symbols if s in self._quotes}

    def name(self, symbol):
        return symbol


# ------------------------------------------------------------------ symbols
def test_symbols_and_markets():
    assert to_symbol("crypto", "sol") == "BINANCE:SOLUSDT"
    assert to_symbol("india", "TCS") == "NSE:TCS"
    assert to_symbol("us", "NASDAQ:AAPL") == "NASDAQ:AAPL"
    assert market_of("BINANCE:SOLUSDT") == "crypto"
    assert market_of("NSE:RELIANCE") == "india"
    assert market_of("YAHOO:^CNXAUTO") == "india"
    assert market_of("YAHOO:NIFTY_FIN_SERVICE.NS") == "india"
    assert market_of("AMEX:XLK") == "us"
    assert short("BINANCE:SOLUSDT") == "SOL"
    assert short("BINANCE:ETHBTC") == "ETH/BTC"
    s = settings()
    assert s.watch["crypto"] == ["BINANCE:SOLUSDT"]
    assert s.fee("india") == pytest.approx(0.0012)
    assert set(s.rules) == {"breakout20", "pullback20", "rsi_dip"}


def test_shipped_desk_yaml_loads():
    s = Settings.load()
    assert all(s.watch[m] for m in ("crypto", "india", "us"))
    assert not set(s.watch_all()) & {x for m in s.control.values() for x in m}, \
        "a control symbol is also on the watchlist"
    assert heatmap.tiles(s)


def test_complete_drops_the_forming_candle():
    df = frame([bar(0, 1, 1, 1, 1), bar(1, 1, 1, 1, 1)])
    assert len(complete(df, now=T0 + 2 * DAY)) == 2
    assert len(complete(df, now=T0 + 2 * DAY - 1)) == 1


# ------------------------------------------------------------------ fills and exits
def test_fill_on_touch_and_on_gap():
    o, h = np.array([10.0, 10.0]), np.array([10.5, 11.0])
    state, fill = find_fill(o, h, 0, 10.8, 12.0, 3, 0.001, 2)
    assert state == "filled" and fill.idx == 1 and fill.price == pytest.approx(10.8 * 1.001)
    state, fill = find_fill(np.array([11.0]), np.array([11.5]), 0, 10.8, 12.0, 3, 0.0, 1)
    assert state == "filled" and fill.price == 11.0          # opened above the entry


def test_miss_expire_and_pending():
    state, _ = find_fill(np.array([12.5]), np.array([13.0]), 0, 10.8, 12.0, 3, 0.0, 1)
    assert state == "missed"
    o = h = np.array([10.0, 10.0, 10.0])
    assert find_fill(o, h, 0, 10.8, 12.0, 3, 0.0, 3)[0] == "expired"
    assert find_fill(o, h, 0, 10.8, 12.0, 3, 0.0, 2)[0] == "pending"   # last still forming


def test_manage_stop_first_gap_target_and_time():
    # touches stop and target on one candle -> stop
    ex = manage(np.array([10.0]), np.array([13.0]), np.array([8.0]), np.array([10.0]),
                0, 9.0, 12.0, 20, 0.0)
    assert ex.why == "stop" and ex.price == 9.0
    # gap down through the stop fills at the open
    o, h = np.array([10.0, 8.5]), np.array([10.2, 8.7])
    lo, c = np.array([9.8, 8.2]), np.array([10.0, 8.4])
    ex = manage(o, h, lo, c, 0, 9.0, 12.0, 20, 0.0)
    assert ex.idx == 1 and ex.price == 8.5
    # target
    ex = manage(np.array([10.0, 11.0]), np.array([10.5, 12.5]), np.array([9.5, 10.8]),
                np.array([10.2, 12.2]), 0, 9.0, 12.0, 20, 0.0)
    assert ex.why == "target" and ex.price == 12.0
    # time exit only on a closed candle
    flat = np.full(3, 10.0)
    assert manage(flat, flat + 0.1, flat - 0.1, flat, 0, 9.0, 12.0, 3, 0.0, 2) is None
    ex = manage(flat, flat + 0.1, flat - 0.1, flat, 0, 9.0, 12.0, 3, 0.0, 3)
    assert ex.why == "time" and ex.idx == 2


def test_r_multiple_counts_fees():
    assert r_multiple(100, 98, 104, 0.0) == pytest.approx(2.0)
    assert r_multiple(100, 98, 104, 0.001) == pytest.approx((4 - 0.204) / 2)
    assert r_multiple(100, 100, 104, 0.0) == 0.0


# ------------------------------------------------------------------ rules + backtest
def test_rules_give_sane_plans():
    d = with_indicators(frame(trend_bars(400, 0.004, seed=3)))
    a = arrays(d)
    found = 0
    for i in range(200, len(d)):
        for rule in ("breakout20", "pullback20", "rsi_dip"):
            s = setup_at(rule, a, i, 2.0)
            if s:
                found += 1
                assert s.stop < s.entry < s.target
                assert 0.5 <= s.risk_pct <= 20
                assert s.rr == pytest.approx(2.0)
    assert found > 0
    assert setup_at("breakout20", a, 150) is None            # warm-up
    with pytest.raises(ValueError):
        setup_at("nope", a, 300)


def test_backtest_trades_never_overlap():
    df = frame(trend_bars(1000, 0.002, seed=7))
    trades = backtest_frame(df, "BINANCE:SOLUSDT", "pullback20", fee=0.001, slip=0.0005,
                            target_r=2, order_bars=3, max_hold=20, years=3,
                            now=T0 + 2000 * DAY)
    assert trades
    for a, b in zip(trades, trades[1:]):
        assert b.signal_time >= a.exit_time
        assert b.fill_time > a.exit_time
    for t in trades:
        assert t.why in ("stop", "target", "time")
        if t.why == "target":
            assert t.r > 0


def _t(r, k=0):
    return BtTrade("X", "r", 0, k, k, 1, 0.9, 1.2, 1, 1, "stop", r)


def test_stats_and_verdict():
    s = stats([_t(2.0, 1), _t(-1.0, 2), _t(-1.0, 3), _t(2.0, 4)])
    assert s["trades"] == 4 and s["win_rate"] == 50
    assert s["exp_r"] == pytest.approx(0.5) and s["pf"] == pytest.approx(2.0)
    assert s["max_dd_r"] == pytest.approx(2.0) and s["total_r"] == pytest.approx(2.0)
    assert stats([])["trades"] == 0
    cfg = settings().backtest
    good = {"trades": 40, "exp_r": 0.3, "pf": 1.5}
    assert verdict(good, {"trades": 20, "exp_r": 0.1}, cfg)[0]
    keep, why = verdict(good, {"trades": 20, "exp_r": -0.1}, cfg)
    assert not keep and "control" in why
    assert not verdict(good, {"trades": 20, "exp_r": 0.01}, cfg)[0]   # break-even is no edge
    assert not verdict({"trades": 2, "exp_r": 1, "pf": 3}, good, cfg)[0]
    assert "loses" in verdict({"trades": 40, "exp_r": -0.1, "pf": 0.8}, good, cfg)[1]


# ------------------------------------------------------------------ screen + plans
def test_screen_ranks_uptrend_over_downtrend():
    up = score_frame(frame(trend_bars(300, 0.004, seed=2, noise=0.005)))
    down = score_frame(frame(trend_bars(300, -0.004, seed=2, noise=0.005)))
    assert up["score"] > down["score"]
    assert up["trend"] == "up" and down["trend"] == "down"
    assert score_frame(frame(trend_bars(30, 0.0))) is None


def test_plans_only_for_kept_rules_and_one_per_symbol(tmp_path, monkeypatch):
    st = settings()
    store = DeskStore(tmp_path / "d.db")
    sym = "BINANCE:SOLUSDT"
    data = FakeData({sym: trend_bars(400, 0.003, seed=5)})
    setup = Setup("pullback20", 101.0, 98.0, 107.0)
    monkeypatch.setattr("market_desk.plans.setup_at", lambda *a, **k: setup)
    rows = [{"symbol": sym, "market": "crypto", "score": 80.0}]
    killed = [{"market": "crypto", "rule": "pullback20", "keep": 0, "w_exp": 0.3}]
    assert make_plans(st, data, store, rows, killed) == []
    kept = [{"market": "crypto", "rule": "pullback20", "keep": 1, "w_exp": 0.3}]
    assert kept_rules(kept) == {"crypto": ["pullback20"]}
    new = make_plans(st, data, store, rows, kept)
    assert len(new) == 1 and new[0]["valid_from"] == T0 + 400 * DAY
    assert make_plans(st, data, store, rows, kept) == []      # already pending


# ------------------------------------------------------------------ paper trading
def _plan(store, sym, market="crypto", **over):
    p = {"symbol": sym, "market": market, "rule": "pullback20", "entry": 101.0,
         "stop": 98.0, "target": 107.0, "valid_from": T0, "order_bars": 3, "score": 70.0,
         "note": "", **over}
    p["id"] = store.add_plan(p)
    return p


def test_paper_plan_fills_then_hits_target(tmp_path):
    st = settings()
    store = DeskStore(tmp_path / "d.db")
    sym = "BINANCE:SOLUSDT"
    _plan(store, sym)
    data = FakeData({sym: [bar(0, 100, 100.5, 99.5, 100.2), bar(1, 100.3, 101.5, 100, 101.2)]})
    sender = FakeSender()
    ev = paper.tick(st, data, store, sender, now=T0 + 2 * DAY + 1)
    assert [e.kind for e in ev] == ["open"]
    (t,) = store.trades("open")
    assert t["entry"] == pytest.approx(101 * 1.0005) and t["fill_time"] == T0 + DAY
    # size cap: 1% risk on a 3% stop is a 33% position -> capped at 20% of equity
    assert t["notional"] == pytest.approx(20000)
    assert t["risk_amt"] == pytest.approx(20000 * (t["entry"] - 98) / t["entry"])
    assert "PAPER OPEN LONG SOL" in sender.sent[0] and "desk" in sender.sent[0]
    assert store.plans("pending") == []

    data.bars[sym] += [bar(2, 101.5, 104, 101, 103.8), bar(3, 104, 107.5, 103.5, 107.2)]
    ev = paper.tick(st, data, store, sender, now=T0 + 4 * DAY + 1)
    assert [e.kind for e in ev] == ["close"]
    (c,) = store.trades("closed")
    assert c["why"] == "target" and c["exit"] == 107.0
    assert c["r"] == pytest.approx(r_multiple(c["entry"], 98, 107, 0.001))
    assert c["pnl"] == pytest.approx(c["risk_amt"] * c["r"])
    assert "PAPER CLOSED LONG SOL" in sender.sent[-1]
    acc = paper.account(st, store)
    assert acc["equity"] == pytest.approx(100000 + c["pnl"]) and acc["closed"] == 1


def test_paper_expiry_and_risk_layer(tmp_path):
    st = settings(max_open=1)
    store = DeskStore(tmp_path / "d.db")
    a, b, c = "BINANCE:SOLUSDT", "BINANCE:ETHUSDT", "BINANCE:XRPUSDT"
    _plan(store, a, score=90)
    _plan(store, b, score=80)
    _plan(store, c, score=70, entry=150.0, target=170.0)
    touch = [bar(0, 100, 102, 99.5, 101.5)]
    data = FakeData({a: touch, b: touch,
                     c: [bar(i, 100, 100.5, 99.5, 100) for i in range(3)]})
    ev = paper.tick(st, data, store, FakeSender(), now=T0 + 3 * DAY + 1)
    kinds = {e.symbol: e.kind for e in ev}
    assert kinds == {a: "open", b: "skip", c: "expired"}
    skipped = [p for p in store.plans() if p["status"] == "skipped"]
    assert "already open" in skipped[0]["note"]


def test_alerts_fire_once(tmp_path):
    store = DeskStore(tmp_path / "d.db")
    alerts.add(store, "nse:reliance", "above", 1500)
    alerts.add(store, "NSE:RELIANCE", "below", 1000)
    data = FakeData(quotes={"NSE:RELIANCE": {"last": 1510.0}})
    sender = FakeSender()
    ev = alerts.check(store, data, sender)
    assert [e.kind for e in ev] == ["alert"] and "ABOVE" in sender.sent[0]
    assert alerts.check(store, data, sender) == []
    assert len(store.alerts(active=True)) == 1
    with pytest.raises(ValueError):
        store.add_alert("NSE:TCS", "sideways", 1)


# ------------------------------------------------------------------ news
RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Reliance shares surge after record profit - Mint</title>
<link>https://x/1</link><pubDate>Mon, 09 Nov 2026 04:00:00 GMT</pubDate>
<source url="https://mint">Mint</source></item>
<item><title>Reliance faces probe over losses - ET</title>
<link>https://x/2</link><pubDate>Sun, 08 Nov 2026 01:00:00 GMT</pubDate>
<source url="https://et">ET</source></item>
<item><title>No date</title><link>https://x/3</link></item>
</channel></rss>"""


def test_news_parse_tone_and_spike():
    items = news.parse_rss(RSS)
    assert [i["title"] for i in items] == ["Reliance shares surge after record profit",
                                           "Reliance faces probe over losses"]
    assert news.tone(items[0]["title"]) == 1.0
    assert news.tone(items[1]["title"]) == -1.0
    assert news.tone("Reliance AGM on Monday") == 0.0
    assert news.parse_rss("not xml") == []
    now = items[0]["ts"] + 3600
    rows = [{**i, "tone": news.tone(i["title"])} for i in items * 3]
    cfg = {"days": 7, "spike_ratio": 2, "spike_min": 3}
    s = news.summarize("NSE:RELIANCE", rows, now, cfg)
    assert s["headlines_24h"] == 3 and s["headlines_7d"] == 6
    assert s["buzz"] is None and s["spike"] == 0           # no earlier nights yet
    s = news.summarize("NSE:RELIANCE", rows, now, cfg, [1, 1, 2])
    assert s["buzz"] == 3 and s["spike"] == 1
    assert news.summarize("NSE:RELIANCE", rows, now, cfg, [3, 3, 3])["spike"] == 0
    assert news.clean_name("Reliance Industries Limited") == "Reliance Industries"
    assert news.clean_name("Apple Inc.") == "Apple"
    assert news.query_for("BINANCE:SOLUSDT") == '"Solana" crypto'
    assert news.query_for("NSE:TCS", "Tata Consultancy Services Limited") == \
        '"Tata Consultancy Services" stock'


def test_store_news_dedupes(tmp_path):
    store = DeskStore(tmp_path / "d.db")
    row = {"link": "https://x/1", "symbol": "NSE:TCS", "ts": 2_000_000_000, "source": "Mint",
           "title": "TCS beats", "tone": 1.0}
    assert store.add_news([row, row]) == 1
    assert len(store.news("NSE:TCS")) == 1


def test_daily_counts_one_per_day(tmp_path):
    store = DeskStore(tmp_path / "d.db")
    base = 2_000_000_000 // DAY * DAY
    s = {"symbol": "NSE:TCS", "market": "india", "headlines_7d": 0, "buzz": None, "tone": 0.0,
         "label": "mixed", "funding": None, "spike": 0}
    store.save_sentiment(base + 3600, [{**s, "headlines_24h": 4}])
    store.save_sentiment(base + 7200, [{**s, "headlines_24h": 6}])     # same day, later run
    store.save_sentiment(base + DAY + 3600, [{**s, "headlines_24h": 9}])
    assert store.daily_counts("NSE:TCS", base + 2 * DAY + 3600) == [9, 6]
    assert store.daily_counts("NSE:TCS", base + DAY + 7200) == [6]    # 20 h gap


# ------------------------------------------------------------------ heatmap + cards
def test_heatmap_changes():
    bars = [bar(i, 100 + i, 101 + i, 99 + i, 100 + i) for i in range(40)]
    ch = heatmap.changes(bars)
    assert ch["last"] == 139
    assert ch["chg_1d"] == pytest.approx((139 / 138 - 1) * 100)
    assert ch["chg_1w"] == pytest.approx((139 / 132 - 1) * 100)
    assert math.isnan(heatmap.changes(bars[:1])["chg_1d"])


def test_cards_escape_and_render():
    rows = [{"symbol": "NSE:M&M", "score": 90.0, "trend": "up", "chg_1m": 5.0}]
    plans = [{"symbol": "NSE:M&M", "entry": 3000.0, "stop": 2900.0, "target": 3200.0,
              "rule": "pullback20"}]
    text = morning_card(rows, plans, {"india": ["pullback20"]})
    assert "M&amp;M" in text and "M&M" not in text.replace("M&amp;M", "")
    assert "desk" in text
    v = [{"market": "india", "rule": "rsi_dip", "keep": 1, "w_exp": 0.2},
         {"market": "us", "rule": "breakout20", "keep": 0, "w_exp": -0.1}]
    text = night_card(v, ["SOL"], {"value": 29, "label": "Fear"})
    assert "India rsi_dip" in text and "Fear & Greed" not in text and "Fear &amp; Greed" in text


def test_sender_respects_switch():
    s = settings()
    s.raw["notify"] = {"telegram": False}

    class Boom:
        def send_html(self, _):
            raise AssertionError("must not send")
    assert Sender(s, Boom()).send("x") is False
    s.raw["notify"] = {"telegram": True}

    class Flaky:
        def send_html(self, _):
            raise RuntimeError("network")
    assert Sender(s, Flaky()).send("x") is False


def test_store_heatmap_quotes_and_numpy_values(tmp_path):
    store = DeskStore(tmp_path / "d.db")
    assert not store.pg and store.where.endswith("d.db")
    rows = heatmap.changes([bar(i, 100 + i, 101 + i, 99 + i, 100 + i) for i in range(40)])
    row = {"market": "crypto", "group": "Majors", "label": "BTC", "symbol": "BINANCE:BTCUSDT",
           **rows, "chg_1m": float("nan")}
    store.save_heatmap(10, [row])
    store.save_heatmap(20, [{**row, "last": np.float64(5.0)}])     # replaces, numpy ok
    (got,) = store.heatmap("crypto")
    assert got["ts"] == 20 and got["group"] == "Majors" and got["last"] == 5.0
    assert got["chg_1m"] is None and store.heatmap("us") == []
    store.save_quotes({"NSE:TCS": {"last": np.float64(3000.5), "change_pct": 1.2}}, ts=5)
    store.save_quotes({"NSE:TCS": {"last": 3001.0, "change_pct": 1.3}}, ts=6)
    assert store.quotes()["NSE:TCS"]["last"] == 3001.0
    pid = store.add_plan({"id": 99, "symbol": "NSE:TCS", "market": "india", "rule": "r",
                          "entry": np.float64(1.0), "stop": 0.9, "target": 1.2,
                          "valid_from": np.int64(7), "order_bars": 3, "score": 1.0, "note": ""})
    assert pid == 1 and store.plans("pending")[0]["valid_from"] == 7


def test_db_url_found_inside_a_pasted_secret(monkeypatch):
    from market_desk.settings import db_url
    url = "postgresql://desk_viewer.abc:Pw123@aws-0-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require"
    for raw in (url, f"  {url} ", f"MARKET_DESK_VIEW_DB_URL={url}", f'"{url}"', f"<{url}>"):
        assert db_url(raw) == url
    assert db_url("") == "" and db_url("not a link") == ""
    s = settings()
    monkeypatch.setenv("MARKET_DESK_DB_URL", f"MARKET_DESK_VIEW_DB_URL={url}")
    assert s.db_target == url and s.db_problem == ""
    monkeypatch.setenv("MARKET_DESK_DB_URL", "oops")
    assert "no postgresql://" in s.db_problem and s.db_target == s.db_path
    monkeypatch.setenv("MARKET_DESK_DB_URL", "")
    assert "missing" in s.db_problem


def test_db_target_from_env(monkeypatch):
    s = settings()
    monkeypatch.setenv("MARKET_DESK_DB_URL", "postgresql://u:p@h:5432/postgres")
    monkeypatch.setenv("MARKET_DESK_MODE", "view")
    assert s.db_target == "postgresql://u:p@h:5432/postgres" and s.view_only
    store = DeskStore(s.db_target)            # no connection until first use
    assert store.pg and store.where == "Supabase"
    monkeypatch.setenv("MARKET_DESK_DB_URL", "")
    monkeypatch.setenv("MARKET_DESK_MODE", "")
    assert s.db_target == s.db_path and not s.view_only


def test_store_latest_rows(tmp_path):
    store = DeskStore(tmp_path / "d.db")
    v = {"market": "us", "rule": "rsi_dip", "keep": 0, "why": "x", "w_trades": 1,
         "w_win": 0.0, "w_exp": 0.0, "w_pf": 0.0, "w_dd": 0.0, "w_total": 0.0,
         "c_trades": 0, "c_win": 0.0, "c_exp": 0.0, "c_pf": 0.0, "recent_trades": 0,
         "recent_exp": None}
    store.save_backtest(1, [v], [])
    store.save_backtest(2, [{**v, "keep": 1}], [])
    assert [r["keep"] for r in store.latest_verdicts()] == [1]
    store.save_screen(5, [{"symbol": "A", "market": "us", "score": 10.0, "close": 1.0,
                           "chg_1d": 0.0, "chg_1w": 0.0, "chg_1m": 0.0, "rsi": 50.0,
                           "trend": "up", "vol_ratio": 1.0, "setups": "", "notes": "",
                           "bar_time": 0},
                          {"symbol": "B", "market": "us", "score": 60.0, "close": 1.0,
                           "chg_1d": 0.0, "chg_1w": 0.0, "chg_1m": 0.0, "rsi": 50.0,
                           "trend": "up", "vol_ratio": 1.0, "setups": "", "notes": "",
                           "bar_time": 0}])
    assert [r["symbol"] for r in store.latest_screen()] == ["B", "A"]
    store.set_meta("k", "1")
    store.set_meta("k", "2")
    assert store.get_meta("k") == "2" and store.get_meta("zz", "d") == "d"
