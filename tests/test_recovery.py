import datetime as dt
import itertools

import pytest

from backend.trading import recovery
from backend.trading.recovery import ACTIVE, DONE, SKIP, Row

DAY = dt.date(2025, 6, 1)
MS = dt.datetime(2025, 6, 1, tzinfo=dt.timezone.utc).timestamp() * 1000
_ids = itertools.count(1)


def trade(symbol, side, qty, price, ms=MS):
    return {"id": next(_ids), "symbol": symbol, "side": side, "quantity": qty, "price": price,
            "timestamp": ms}


def test_cost_basis_is_average_cost_in_inr():
    basis = recovery.cost_basis([
        trade("DOTINR", "buy", 10, 500),                 # Rs 5,000
        trade("DOTUSDT", "buy", 10, 6),                  # 60 USDT at 90 = Rs 5,400
        trade("DOTINR", "sell", 5, 700),                 # a quarter of the coins goes
        trade("USDTINR", "buy", 100, 90),                # currency swap: ignored
    ], {DAY: 90.0}, {"USDTINR": 100.0})
    qty, cost = basis["DOT"]
    assert qty == pytest.approx(15)
    assert cost == pytest.approx((5000 + 5400) * 0.75)
    assert "USDT" not in basis


def test_old_trades_use_the_yearly_rate():
    assert recovery.rate_on(dt.date(2021, 3, 1), {DAY: 90.0}) == recovery.OLD_USDT_INR[2021]
    assert recovery.rate_on(DAY + dt.timedelta(days=3), {DAY: 90.0}) == 90.0


def test_futures_pnl_counts_only_from_the_start_day():
    txs = [{"pair": "B-DOT_USDT", "amount": 1000, "fee_amount": 10, "created_at": MS + 1},
           {"pair": "B-DOT_USDT", "amount": -200, "fee_amount": 5, "created_at": MS + 2},
           {"pair": "B-DOT_USDT", "amount": 9999, "fee_amount": 0, "created_at": MS - 1},
           {"pair": "B-AR_USDT", "amount": 0, "fee_amount": 3, "created_at": MS + 3}]
    assert recovery.pnl_by_pair(txs, MS) == {"B-DOT_USDT": pytest.approx(785),
                                             "B-AR_USDT": pytest.approx(-3)}


def test_ledger_reaches_breakeven_only_past_the_cushion():
    rows = [Row("DOT", 10, 20000, "2025-06-01"), Row("AR", 5, 3000, "2025-06-01"),
            Row("S", 100, 500, "2025-06-01", SKIP), Row("OP", 1, 100, "2025-06-01", DONE)]
    ticker = {"USDTINR": 100.0, "DOTINR": 800.0, "ARUSDT": 5.0}
    pos = [{"pair": "B-AR_USDT", "active_pos": -2, "avg_price": 6.0, "mark_price": 5.0,
            "settlement_currency_avg_price": 100.0}]
    lines = {x.coin: x for x in recovery.build(
        rows, ticker=ticker, held={"DOT": 10, "AR": 5, "S": 100},
        futures_pnl={"2025-06-01": {"B-DOT_USDT": 12000.0}}, positions=pos,
        active_pairs={"B-DOT_USDT", "B-AR_USDT"}, cushion_pct=1.5)}
    dot, ar = lines["DOT"], lines["AR"]
    assert dot.spot_now_inr == 8000 and dot.spot_pnl_inr == -12000
    assert dot.total_inr == 0 and not dot.ready
    assert dot.to_go_inr == pytest.approx(120)           # 1.5% of Rs 8,000
    assert ar.spot_now_inr == 2500 and ar.futures_open_inr == pytest.approx(200)
    assert ar.total_inr == pytest.approx(-300) and ar.to_go_inr == pytest.approx(337.5)
    assert lines["S"].status == SKIP and lines["OP"].status == DONE


def test_ledger_flags_a_spot_holding_that_shrank():
    [x] = recovery.build([Row("DOT", 10, 1000, "2025-06-01")], ticker={"DOTINR": 200.0},
                         held={"DOT": 4}, futures_pnl={}, positions=[], active_pairs=set())
    assert x.qty == 4 and x.paid_inr == pytest.approx(400) and "spot holds 4" in x.note
    assert x.ready                                        # 4 coins now Rs 800, cost Rs 400
    assert not x.has_futures


def test_csv_round_trip(tmp_path):
    p = tmp_path / "r.csv"
    rows = [Row("DOT", 64.5, 31556.4, "2026-10-01", ACTIVE, "a, b"),
            Row("S", 2035, 8200, "2026-10-01", SKIP)]
    recovery.save(p, rows)
    assert recovery.load(p) == rows
    assert recovery.load(tmp_path / "none.csv") == []


class FakeSpot:
    def __init__(self, trades, balances, ticker):
        self.trades, self.balances, self.ticker = trades, balances, ticker

    def _read(self, method, path, body=None, signed=True):
        if path == "/exchange/ticker":
            return [{"market": k, "last_price": v} for k, v in self.ticker.items()]
        if path == "/exchange/v1/users/balances":
            return [{"currency": c, "balance": q, "locked_balance": 0}
                    for c, q in self.balances.items()]
        if path == "/exchange/v1/orders/trade_history":
            return [t for t in self.trades if t["id"] >= body["from_id"]][:body["limit"]]
        raise AssertionError(path)


def test_seed_leaves_out_small_buys_and_marks_deposits(monkeypatch):
    monkeypatch.setattr(recovery, "usdt_inr_history", lambda: {DAY: 90.0})
    client = FakeSpot(
        [trade("DOTINR", "buy", 10, 3000),             # Rs 30,000: kept
         trade("AVAXINR", "buy", 1, 3000),              # Rs 3,000 < $50: left out
         trade("INJINR", "buy", 2, 2000)],              # Rs 4,000 + 3 deposited coins
        {"DOT": 10, "AVAX": 1, "INJ": 5, "S": 1000, "BONK": 1, "INR": 50, "USDT": 3},
        {"USDTINR": 100.0, "DOTINR": 800.0, "AVAXINR": 2000.0, "INJINR": 1500.0,
         "SUSDT": 0.05, "BONKINR": 0.001})
    rows = {r.coin: r for r in recovery.seed(client, since=DAY)}
    assert set(rows) == {"DOT", "INJ", "S"}
    assert rows["DOT"].paid_inr == pytest.approx(30000) and rows["DOT"].status == ACTIVE
    assert rows["INJ"].paid_inr == pytest.approx(4000 + 3 * 1500)
    assert "3 of 5" in rows["INJ"].note
    assert rows["S"].status == SKIP and rows["S"].paid_inr == pytest.approx(5000)
    assert rows["DOT"].since == "2025-06-01"
