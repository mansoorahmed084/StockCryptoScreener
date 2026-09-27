import hashlib
import hmac
import json

import httpx
import pytest

from backend.trading import risk
from backend.trading.client import CoinDcxError, FuturesClient, UnknownOutcome
from backend.trading.manager import DRY_RUN, LIVE, TradeError, TradeManager
from backend.trading.store import CLOSED, FAILED, OPEN, PENDING, TradeStore

PAIR = "B-SOL_USDT"
INSTRUMENT = {
    "pair": PAIR, "status": "active", "price_increment": 0.01, "quantity_increment": 0.01,
    "min_quantity": 0.01, "max_quantity": 50000, "max_market_order_quantity": 5000,
    "min_notional": 6.0, "taker_fee": 0.075, "multiplier_up": 8.0, "multiplier_down": 8.0,
    "exit_only": False, "max_leverage_long": 20.0,
    "dynamic_position_leverage_details": {"10": 1000000.0, "20": 100000.0},
    "dynamic_safety_margin_details": {"50000": 1.5, "100000": 2.0},
}
LIMITS = risk.Limits(max_risk_inr=1000, max_margin_inr=20000, max_leverage=10,
                     max_open_positions=2, max_daily_loss_inr=2000, min_stop_pct=0.3)


def req(**kw):
    base = dict(pair="SOL", side=risk.LONG, stop_loss=95.0, take_profit=110.0,
                risk_inr=500.0, leverage=5)
    return risk.TradeRequest(**{**base, **kw})


def plan_for(r, **kw):
    r.pair = risk.to_pair(r.pair)
    args = dict(last_price=100.0, rate=90.0, limits=LIMITS)
    return risk.build_plan(r, risk.Instrument.from_api(INSTRUMENT), **{**args, **kw})


# -- sizing and checks ---------------------------------------------------------

def test_size_comes_from_inr_risk_with_fees():
    p = plan_for(req())
    assert p.ok, p.errors
    # 5 USDT stop + 0.075% taker fee on 100 and 95, at 90 INR/USDT
    per_unit = (5 + 195 * 0.00075) * 90
    assert p.qty == pytest.approx(int(500 / per_unit * 100) / 100)
    assert p.risk_inr <= 500
    assert p.margin_inr == pytest.approx(p.qty * 100 * 90 / 5)
    assert p.rr == pytest.approx(p.reward_inr / p.risk_inr)


@pytest.mark.parametrize("kw, text", [
    (dict(stop_loss=101.0), "must be below entry"),
    (dict(side=risk.SHORT, stop_loss=95.0, take_profit=90.0), "must be above entry"),
    (dict(take_profit=99.0), "target"),
    (dict(stop_loss=99.9), "minimum is 0.3%"),
    (dict(stop_loss=0.0), "needs a stop loss"),
    (dict(leverage=12), "above your limit of 10x"),
    (dict(risk_inr=5000.0), "above your limit"),
    (dict(leverage=10, stop_loss=85.0, risk_inr=400.0), "liquidated"),
    (dict(entry_type=risk.LIMIT, limit_price=None), "needs a limit price"),
    (dict(entry_type=risk.LIMIT, limit_price=80.0, stop_loss=78.0), "between"),
])
def test_bad_trades_are_blocked(kw, text):
    p = plan_for(req(**kw))
    assert not p.ok
    assert any(text in e for e in p.errors), p.errors
    assert "BLOCKED" in p.summary()


def test_size_by_margin():
    p = plan_for(req(risk_inr=0.0, margin_inr=1000.0, leverage=5))
    assert p.ok, p.errors
    assert p.qty == pytest.approx(int(1000 * 5 / (100 * 90) * 100) / 100)
    assert p.margin_inr <= 1000
    big = plan_for(req(risk_inr=0.0, margin_inr=15000.0, leverage=5))
    assert any("risk Rs" in e for e in big.errors), big.errors


def test_gold_standard_rules_and_override():
    wide = plan_for(req(stop_loss=88.0, risk_inr=300.0))          # 12% stop
    assert any("at most 10%" in e for e in wide.errors)
    assert any("at most 5x" in e for e in plan_for(req(leverage=6)).errors)
    small = plan_for(req(), free_inr=10000.0)                      # 5% = Rs 500
    assert any("5% of your free balance" in e for e in small.errors)
    assert plan_for(req(risk_inr=0.0, margin_inr=500.0), free_inr=10000.0).ok
    big = plan_for(req(stop_loss=88.0, risk_inr=300.0, override=True), free_inr=10000.0)
    assert big.ok, big.errors
    assert any("OVERRIDDEN" in w for w in big.warnings)


def test_account_limits_block_new_trades():
    assert any("already hold" in e for e in plan_for(req(), has_position=True).errors)
    assert any("positions are open" in e for e in plan_for(req(), open_positions=2).errors)
    assert any("daily limit" in e for e in plan_for(req(), loss_today_inr=2500).errors)
    lim = risk.Limits.from_config({"allowed_pairs": ["BTC"]})
    assert any("allowed_pairs" in e for e in plan_for(req(), limits=lim).errors)


def test_short_liquidation_is_above_entry():
    assert risk.liquidation_price(risk.SHORT, 100, 5, 1.5) == pytest.approx(118.5)
    assert risk.liquidation_price(risk.LONG, 100, 5, 1.5) == pytest.approx(81.5)


def test_pair_names_and_rounding():
    assert risk.to_pair("sol") == risk.to_pair("SOLUSDT") == risk.to_pair("B-SOL_USDT") == PAIR
    from decimal import Decimal
    assert risk.round_step(0.123456, Decimal("0.001"), down=True) == 0.123
    assert risk.round_step(101.237, Decimal("0.01")) == 101.24


def test_moving_a_stop_through_the_price_is_refused():
    assert risk.check_stop_move(risk.LONG, stop_loss=101, take_profit=None, mark=100)
    assert not risk.check_stop_move(risk.LONG, stop_loss=99, take_profit=120, mark=100)
    assert risk.check_stop_move(risk.SHORT, stop_loss=None, take_profit=101, mark=100)


# -- signed client ---------------------------------------------------------------

def test_signature_is_hmac_of_the_exact_body_sent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        seen["headers"] = request.headers
        return httpx.Response(200, json=[])

    c = FuturesClient("k", "s3cret", client=httpx.Client(transport=httpx.MockTransport(handler)))
    c.positions([PAIR])
    body = json.loads(seen["body"])
    assert body["pairs"] == PAIR and body["margin_currency_short_name"] == ["INR"]
    assert body["timestamp"] > 1_700_000_000_000          # milliseconds
    assert seen["headers"]["X-AUTH-APIKEY"] == "k"
    assert seen["headers"]["X-AUTH-SIGNATURE"] == hmac.new(
        b"s3cret", seen["body"], hashlib.sha256).hexdigest()
    assert "s3cret" not in repr(c)


def test_writes_are_never_retried_but_reads_are():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/orders/create"):
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(503, json={"message": "down"})

    c = FuturesClient("k", "s", client=httpx.Client(transport=httpx.MockTransport(handler)),
                      retries=2)
    with pytest.raises(UnknownOutcome):
        c.create_order({"pair": PAIR})
    assert len(calls) == 1
    with pytest.raises(CoinDcxError):
        c.positions()
    assert len(calls) == 3


def test_client_refuses_private_calls_without_keys():
    c = FuturesClient(client=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=[]))))
    with pytest.raises(CoinDcxError, match="not set"):
        c.wallets()


# -- manager against a fake exchange ---------------------------------------------

class FakeExchange:
    has_keys = True

    def __init__(self, *, fills=True, accepts_sl=True):
        self.fills = fills
        self.accepts_sl = accepts_sl
        self.pos: dict[str, dict] = {}
        self.open_orders: list[dict] = []
        self.writes: list[tuple] = []

    # reads
    def instrument(self, pair):
        return INSTRUMENT

    px = 100.0

    def prices(self):
        return {PAIR: {"ls": self.px, "mp": self.px}}

    def conversion_rate(self):
        return 90.0

    def positions(self, pairs=None):
        return [dict(p) for p in self.pos.values() if not pairs or p["pair"] in pairs]

    def orders(self, status="open"):
        return [o for o in self.open_orders if o["status"] in status.split(",")]

    def transactions(self, page=1, size=100):
        return []

    def wallets(self):
        return [{"currency_short_name": "INR", "balance": "50000"}]

    # writes
    def update_leverage(self, pair, lev):
        self.writes.append(("update_leverage", pair, lev))

    def create_order(self, order):
        self.writes.append(("create_order", order))
        if self.fills and order["order_type"] == "market_order":
            self.fill(order["pair"], order["total_quantity"])
        else:
            self.open_orders.append({"id": "o1", "pair": order["pair"], "status": "open"})
        return {"id": "o1"}

    def fill(self, pair, qty):
        self.pos[pair] = {"id": "p1", "pair": pair, "active_pos": qty, "avg_price": 100.0,
                          "stop_loss_trigger": None, "take_profit_trigger": None}
        self.open_orders = [o for o in self.open_orders if o["pair"] != pair]

    def create_tpsl(self, position_id, stop_loss=None, take_profit=None):
        self.writes.append(("create_tpsl", stop_loss, take_profit))
        p = next(p for p in self.pos.values() if p["id"] == position_id)
        if stop_loss is not None and self.accepts_sl:
            p["stop_loss_trigger"] = stop_loss
            self.open_orders.append({"id": "sl1", "pair": p["pair"], "status": "untriggered",
                                     "stage": "tpsl_exit", "order_type": "stop_market"})
        if take_profit is not None:
            p["take_profit_trigger"] = take_profit
        return {}

    def cancel_order(self, oid):
        self.writes.append(("cancel_order", oid))
        self.open_orders = [o for o in self.open_orders if o["id"] != oid]
        for p in self.pos.values():
            if oid == "sl1":
                p["stop_loss_trigger"] = None

    def exit_position(self, pid):
        self.writes.append(("exit_position", pid))
        self.pos = {k: v for k, v in self.pos.items() if v["id"] != pid}

    def cancel_position_orders(self, pid):
        self.writes.append(("cancel_position_orders", pid))

    def cancel_all_orders(self):
        self.writes.append(("cancel_all_orders",))
        self.open_orders = []


def manager(tmp_path, ex, mode=LIVE, **kw):
    return TradeManager(ex, TradeStore(tmp_path / "t.db"), LIMITS, mode=mode,
                        fill_timeout_s=0.01, poll_s=0.001, sleep=lambda s: None, **kw)


def test_dry_run_sends_nothing(tmp_path):
    ex = FakeExchange()
    m = manager(tmp_path, ex, mode=DRY_RUN)
    plan, tid = m.open(req(), confirm=PAIR)
    assert plan.ok and ex.writes == []
    assert m.store.trades()[0]["status"] == "dry_run"
    assert all(e["response"] == '"dry run: not sent"' for e in m.store.events())


def test_live_market_entry_gets_sl_and_tp(tmp_path):
    ex = FakeExchange()
    m = manager(tmp_path, ex)
    plan, tid = m.open(req(), confirm="b-sol_usdt")
    kinds = [w[0] for w in ex.writes]
    assert kinds == ["update_leverage", "create_order", "create_tpsl"]
    assert ex.pos[PAIR]["stop_loss_trigger"] == 95.0
    assert ex.pos[PAIR]["take_profit_trigger"] == 110.0
    t = m.store.trades()[0]
    assert t["status"] == OPEN and t["position_id"] == "p1"


def test_position_is_closed_when_stop_loss_is_not_accepted(tmp_path):
    ex = FakeExchange(accepts_sl=False)
    m = manager(tmp_path, ex)
    m.open(req(), confirm=PAIR)
    assert ("exit_position", "p1") in ex.writes
    assert PAIR not in ex.pos
    assert m.store.trades()[0]["status"] == FAILED


def test_nothing_is_sent_without_the_typed_confirmation(tmp_path):
    ex = FakeExchange()
    m = manager(tmp_path, ex)
    with pytest.raises(TradeError, match="not confirmed"):
        m.open(req(), confirm="yes")
    assert ex.writes == []


def test_a_blocked_plan_is_never_sent(tmp_path):
    ex = FakeExchange()
    m = manager(tmp_path, ex)
    with pytest.raises(TradeError, match="below entry"):
        m.open(req(stop_loss=105.0), confirm=PAIR)
    assert ex.writes == []


def test_timed_out_entry_is_checked_not_resent(tmp_path):
    ex = FakeExchange()

    def lost(order):
        ex.writes.append(("create_order", order))
        raise UnknownOutcome("timeout")

    ex.create_order = lost
    m = manager(tmp_path, ex)
    with pytest.raises(TradeError, match="not on the exchange"):
        m.open(req(), confirm=PAIR)
    assert [w[0] for w in ex.writes] == ["update_leverage", "create_order"]
    assert m.store.trades()[0]["status"] == FAILED


def test_panic_closes_everything_and_blocks_new_trades(tmp_path):
    ex = FakeExchange()
    m = manager(tmp_path, ex)
    m.open(req(), confirm=PAIR)
    with pytest.raises(TradeError):
        m.panic("yes")
    m.panic("PANIC")
    assert PAIR not in ex.pos and ("cancel_all_orders",) in ex.writes
    assert any("halted" in e for e in m.preview(req()).errors)
    m.resume()
    assert m.preview(req()).ok


def test_watcher_protects_a_filled_limit_entry_and_closes_records(tmp_path):
    ex = FakeExchange()
    m = manager(tmp_path, ex)
    m.open(req(entry_type=risk.LIMIT, limit_price=99.0), confirm=PAIR)
    assert m.store.trades()[0]["status"] == PENDING
    assert m.reconcile() == []                        # not filled yet
    ex.fill(PAIR, 1.0)
    assert m.reconcile()                              # filled -> SL/TP attached
    assert ex.pos[PAIR]["stop_loss_trigger"] == 95.0
    assert m.store.trades()[0]["status"] == OPEN
    ex.pos.clear()                                    # stop hit on the exchange
    m.reconcile()
    assert m.store.trades()[0]["status"] == CLOSED


def test_watcher_warns_once_about_a_position_with_no_stop(tmp_path):
    ex = FakeExchange()
    ex.fill(PAIR, 1.0)                                # opened by hand in the app
    m = manager(tmp_path, ex)
    assert "NO stop loss" in m.reconcile()[0]
    assert m.reconcile() == []
    m2 = manager(tmp_path, ex, close_unprotected=True)
    m2.reconcile()
    assert PAIR not in ex.pos


def test_moving_the_stop_restores_protection_if_refused(tmp_path):
    ex = FakeExchange()
    m = manager(tmp_path, ex)
    m.open(req(), confirm=PAIR)
    m.set_tpsl("SOL", stop_loss=97.0)
    assert ex.pos[PAIR]["stop_loss_trigger"] == 97.0
    assert m.store.trades()[0]["stop_loss"] == 97.0

    ex.accepts_sl = False
    with pytest.raises(TradeError, match="refused the new stop"):
        m.set_tpsl("SOL", stop_loss=98.0)
    assert ("exit_position", "p1") in ex.writes       # could not restore -> closed
    with pytest.raises(TradeError, match="wrong side"):
        ex.accepts_sl = True
        ex.fill(PAIR, 1.0)
        m.set_tpsl("SOL", stop_loss=101.0)


# -- setups from the scan: tap to place -------------------------------------------

from backend.trading import ideas  # noqa: E402


def setups(**kw):
    row = dict(coin="SOL", timeframe="1h", pattern="Bull flag", kind="now", price=100.0,
               up_level=99.0, down_level=95.0, target_up=110.0, rr=2.0, score=5.0)
    return ideas.pd.DataFrame([{**row, **kw}])


def scanner(tmp_path, ex, **kw):
    ex.active_pairs = lambda: [PAIR]
    return manager(tmp_path, ex, **kw), ideas.Settings()


def test_scan_records_setups_and_places_nothing(tmp_path):
    ex = FakeExchange()
    m, s = scanner(tmp_path, ex)
    new = ideas.scan(m, setups(), s)
    assert [i["status"] for i in new] == [ideas.READY]
    assert "margin Rs" in new[0]["reason"]
    assert ex.writes == []
    assert ideas.scan(m, setups(), s) == []               # not recorded twice


def test_scan_blocks_rule_breakers(tmp_path):
    ex = FakeExchange()
    m, s = scanner(tmp_path, ex)
    wide, = ideas.scan(m, setups(down_level=85.0), s)          # 15% stop
    assert wide["status"] == ideas.BLOCKED and "at most 10%" in wide["reason"]
    gone, = ideas.scan(m, setups(coin="XYZ"), s)
    assert "not an INR future" in gone["reason"]
    wait, = ideas.scan(m, setups(pattern="Ascending triangle", kind="close_above"), s)
    assert wait["status"] == ideas.WAITING


def test_tap_places_with_gold_standard_size(tmp_path):
    ex = FakeExchange()
    m, s = scanner(tmp_path, ex)
    idea, = ideas.scan(m, setups(), s)
    ideas.place(m, idea["id"], s)
    order = next(w[1] for w in ex.writes if w[0] == "create_order")
    assert order["leverage"] == 5
    margin = order["total_quantity"] * 100 * 90 / 5
    assert 50000 * 0.05 * 0.95 < margin <= 50000 * 0.05    # 5% of the free balance
    assert ex.pos[PAIR]["stop_loss_trigger"] == 95.0
    assert m.store.idea(idea["id"])["status"] == ideas.PLACED
    with pytest.raises(TradeError, match="placed, not ready"):
        ideas.place(m, idea["id"], s)


def test_a_trade_closed_by_hand_is_not_offered_again(tmp_path):
    ex = FakeExchange()
    m, s = scanner(tmp_path, ex)
    idea, = ideas.scan(m, setups(), s)
    ideas.place(m, idea["id"], s)
    ex.pos.clear()                                         # you closed it in the app
    s2 = ideas.Settings(recheck_hours=0)
    again, = ideas.scan(m, setups(), s2)
    assert m.store.trades()[0]["status"] == CLOSED
    assert again["status"] == ideas.BLOCKED and "already traded" in again["reason"]
    other, = ideas.scan(m, setups(pattern="Ascending triangle"), s2)
    assert "in the last 24h" in other["reason"]            # the coin rests after a trade
    assert [w[0] for w in ex.writes].count("create_order") == 1


def test_old_setups_expire(tmp_path):
    ex = FakeExchange()
    m, s = scanner(tmp_path, ex)
    idea, = ideas.scan(m, setups(), s)
    m.store.update_idea(idea["id"], ts_ms=0)
    with pytest.raises(TradeError, match="too old"):
        ideas.place(m, idea["id"], s)
    assert m.store.idea(idea["id"])["status"] == ideas.EXPIRED
    assert ex.writes == []


# -- trailing stop -----------------------------------------------------------------

from backend.trading import trailing  # noqa: E402

TS = trailing.Settings()


def test_trailing_stop_maths():
    ns = lambda **kw: trailing.next_stop(**{**dict(  # noqa: E731
        side=risk.LONG, entry=100.0, initial_stop=95.0, best=100.0, price=100.0,
        current_stop=95.0, s=TS), **kw})
    assert ns(best=104.9, price=104.9) is None                   # under 1R: wait
    assert ns(best=105.0, price=105.0) == pytest.approx(100.2)   # 1R: breakeven + fees
    assert ns(best=112.0, price=112.0) == pytest.approx(107.0)   # 1R behind the best
    assert ns(best=112.0, price=112.0, current_stop=106.0) is None   # step under 0.25R
    assert ns(best=112.0, price=107.1) == pytest.approx(107.1 * 0.998)  # not at the price
    short = ns(side=risk.SHORT, initial_stop=105.0, best=90.0, price=90.0, current_stop=105.0)
    assert short == pytest.approx(95.0)


def test_watcher_trails_the_stop_up_and_never_down(tmp_path):
    ex = FakeExchange()
    m = manager(tmp_path, ex)
    m.open(req(), confirm=PAIR)                          # entry 100, SL 95, TP 110
    assert trailing.run(m, TS) == []
    ex.px = 105.2                                         # just past 1R: breakeven
    msgs = trailing.run(m, TS)
    assert ex.pos[PAIR]["stop_loss_trigger"] == pytest.approx(100.2)
    assert "trailing stop" in msgs[0]
    ex.px = 108.0
    trailing.run(m, TS)
    assert ex.pos[PAIR]["stop_loss_trigger"] == pytest.approx(103.0)
    assert ex.pos[PAIR]["take_profit_trigger"] == 110.0   # the target stays
    ex.px = 104.0                                         # pullback: stop stays put
    assert trailing.run(m, TS) == []
    assert ex.pos[PAIR]["stop_loss_trigger"] == pytest.approx(103.0)
    assert m.store.trades()[0]["best_price"] == 108.0


def test_trailing_can_be_turned_off_and_skips_hand_positions(tmp_path):
    ex = FakeExchange()
    m = manager(tmp_path, ex)
    m.open(req(), confirm=PAIR)
    m.store.update_trade(m.store.trades()[0]["id"], trail=0)
    ex.px = 108.0
    assert trailing.run(m, TS) == []
    assert ex.pos[PAIR]["stop_loss_trigger"] == 95.0

    ex2 = FakeExchange()
    ex2.fill(PAIR, 1.0)                                   # opened by hand, no record
    ex2.pos[PAIR]["stop_loss_trigger"] = 95.0
    ex2.px = 108.0
    m2 = manager(tmp_path / "b", ex2)
    assert trailing.run(m2, TS) == []
    assert ex2.writes == []


def test_moving_the_stop_retries_with_the_target_when_sl_alone_is_refused(tmp_path):
    ex = FakeExchange()
    m = manager(tmp_path, ex)
    m.open(req(), confirm=PAIR)
    real = ex.create_tpsl

    def picky(position_id, stop_loss=None, take_profit=None):
        if take_profit is None:                           # "SL alone" not accepted
            ex.writes.append(("create_tpsl", stop_loss, None))
            return {}
        return real(position_id, stop_loss=stop_loss, take_profit=take_profit)

    ex.create_tpsl = picky
    ex.px = 105.5
    trailing.run(m, TS)
    assert ex.pos[PAIR]["stop_loss_trigger"] == pytest.approx(100.5)   # 1R behind 105.5
    assert ("exit_position", "p1") not in ex.writes


def test_adopted_hand_position_trails_by_percent(tmp_path):
    ex = FakeExchange()
    ex.fill(PAIR, 10.0)                                   # opened by hand: no SL, entry 100
    ex.pos[PAIR]["take_profit_trigger"] = 110.0
    ex.px = 102.0
    m = manager(tmp_path, ex)
    with pytest.raises(TradeError, match="not confirmed"):
        m.adopt("SOL", 1.5, confirm="yes")
    with pytest.raises(TradeError, match="at most 10%"):
        m.adopt("SOL", 12, confirm=PAIR)
    m.adopt("SOL", 1.5, confirm=PAIR)
    assert ex.writes == []                                # adopting sends nothing
    assert m.reconcile() == []                            # no "NO stop loss" warning now

    trailing.run(m, TS)                                   # first stop: 1.5% under 102
    assert ex.pos[PAIR]["stop_loss_trigger"] == pytest.approx(100.47)
    assert ex.pos[PAIR]["take_profit_trigger"] == 110.0
    ex.px = 102.2                                         # step under a quarter of 1.5%
    assert trailing.run(m, TS) == []
    ex.px = 105.0
    trailing.run(m, TS)
    assert ex.pos[PAIR]["stop_loss_trigger"] == pytest.approx(103.42)
    ex.px = 103.8                                         # pullback: stop stays
    assert trailing.run(m, TS) == []
    with pytest.raises(TradeError, match="already managed"):
        m.adopt("SOL", 2, confirm=PAIR)


def test_adopting_needs_live_mode(tmp_path):
    ex = FakeExchange()
    ex.fill(PAIR, 1.0)
    with pytest.raises(TradeError, match="live mode"):
        manager(tmp_path, ex, mode=DRY_RUN).adopt("SOL", 1.5, confirm=PAIR)


def test_candle_trail_uses_the_last_closed_candle():
    now = 10 * 900_000 - 1
    rows =[{"time": 8 * 900_000, "low": 99.0, "high": 101.0},
            {"time": 9 * 900_000, "low": 100.0, "high": 102.0}]     # still forming
    assert trailing.last_closed(rows, 15, now)["low"] == 99.0
    c = {"low": 104.0, "high": 106.0}
    assert trailing.next_stop_candle(risk.LONG, candle=c, price=106.0, current_stop=100.0,
                                     s=TS) == pytest.approx(103.896)   # 0.1% under the low
    assert trailing.next_stop_candle(risk.LONG, candle=c, price=106.0, current_stop=104.0,
                                     s=TS) is None                     # never down
    assert trailing.next_stop_candle(risk.SHORT, candle=c, price=103.0, current_stop=110.0,
                                     s=TS) == pytest.approx(106.106)   # 0.1% over the high
    assert trailing.next_stop_candle(risk.LONG, candle=c, price=104.05, current_stop=None,
                                     s=TS) == pytest.approx(104.05 * 0.998)  # not on the price


def test_watcher_trails_an_adopted_position_under_coindcx_candles(tmp_path):
    import time as _t
    ex = FakeExchange()
    ex.fill(PAIR, 10.0)
    ex.pos[PAIR]["stop_loss_trigger"] = 98.0
    ex.px = 104.0
    now = int(_t.time() * 1000)
    ex.bars = [{"time": now - 45 * 60_000, "low": 101.0, "high": 103.0},
               {"time": now - 20 * 60_000, "low": 102.5, "high": 104.0},   # last closed
               {"time": now - 5 * 60_000, "low": 90.0, "high": 104.5}]     # forming: ignored
    ex.candles = lambda pair, minutes, lookback_s=0: ex.bars
    m = manager(tmp_path, ex)
    with pytest.raises(TradeError, match="one trail"):
        m.adopt("SOL", 1.5, confirm=PAIR, trail_candle="15m")
    m.adopt("SOL", 0, confirm=PAIR, trail_candle="15m")
    trailing.run(m, TS)
    assert ex.pos[PAIR]["stop_loss_trigger"] == pytest.approx(102.39)      # 102.5 - 0.1%
    ex.bars[1]["low"] = 101.0                                              # lower low: stays
    assert trailing.run(m, TS) == []
    m.set_trail("SOL", trail_pct=2.0)
    assert m.store.trades()[0]["trail_candle"] is None


def test_candle_trail_skips_tiny_moves_and_waits_for_the_candle_to_settle():
    c = {"low": 104.0, "high": 106.0}
    # new stop 103.896: only 0.05 above 103.85, under 0.1% of the price -> skip
    assert trailing.next_stop_candle(risk.LONG, candle=c, price=105.0, current_stop=103.85,
                                     s=TS) is None
    assert trailing.next_stop_candle(risk.LONG, candle=c, price=105.0, current_stop=103.7,
                                     s=TS) == pytest.approx(103.896)
    rows = [{"time": 0, "low": 1.0}, {"time": 900_000, "low": 2.0}]   # 2nd closes at 1.8M
    assert trailing.last_closed(rows, 15, 1_800_000 + 30_000, settle_s=60)["low"] == 1.0
    assert trailing.last_closed(rows, 15, 1_800_000 + 60_000, settle_s=60)["low"] == 2.0


def test_switching_the_trail_rewrites_its_note(tmp_path):
    ex = FakeExchange()
    ex.fill(PAIR, 1.0)
    m = manager(tmp_path, ex)
    m.adopt("SOL", 1.5, confirm=PAIR)
    m.set_trail("SOL", trail_candle="15m")
    note = m.store.trades()[0]["note"]
    assert note == "adopted (opened by hand); trailing under the last closed 15m candle"
