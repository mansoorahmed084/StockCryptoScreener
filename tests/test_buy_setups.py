import numpy as np
import pandas as pd

from backend.screener import buy_setups as bs


def _row(coin, tf="1h", pattern="Bull flag", status="broke up", setup="Broke up, fresh",
         price=100.0, down=95.0, target=120.0, room=np.nan):
    return {"coin": coin, "symbol": f"{coin}USDT", "timeframe": tf, "pattern": pattern,
            "bias": "bullish", "status": status, "price": price, "up_level": 99.0,
            "up_pct": -1.0, "down_level": down, "down_pct": -5.0, "target_up": target,
            "target_down": np.nan, "touches": "3/1", "near_pct": 1.0, "zone_above": "—",
            "zone_above_pct": room, "zone_below": "—", "zone_below_pct": np.nan,
            "setup": setup}


def test_pick_keeps_only_setups_that_pass_every_rule():
    scan = pd.DataFrame([
        _row("GOOD"),                                             # passes
        _row("GOOD", tf="4h"),                                    # same coin: one pick
        _row("FAST", tf="15m"),                                   # 15m: too noisy
        _row("DOWN"),                                             # daily trend down
        _row("BEAR"),                                             # bear setup at 4h
        _row("BEAR", tf="4h", pattern="Bear flag", status="broke down",
             setup="Broke down, fresh"),
        _row("ROOF", room=2.0),                                   # supply 2% above
        _row("LOWRR", target=104.0),                              # reward/risk 0.8
        _row("NEAR", status="inside", setup="Near breakout: 0.8% to the upper line"),
    ])
    trends = {f"{c}USDT": ("up", "up") for c in scan["coin"]}
    trends["DOWNUSDT"] = ("down", "up")
    ranked = bs.rank(scan, trends)
    picks = bs.pick(ranked, n=5)
    assert sorted(picks["coin"]) == ["GOOD", "NEAR"]
    assert picks.set_index("coin").loc["NEAR", "kind"] == "close_above"
    assert picks.set_index("coin").loc["GOOD", "timeframe"] == "4h"   # the higher score
    # A setup the journal already holds is skipped.
    again = bs.pick(ranked, n=5, taken={("GOOD", "4h", "Bull flag"), ("GOOD", "1h", "Bull flag")})
    assert list(again["coin"]) == ["NEAR"]


def test_journal_rows_for_both_kinds():
    scan = pd.DataFrame([_row("A"), _row("B", status="inside",
                                         setup="Near breakout: 0.5% to the upper line")])
    picks = bs.pick(bs.rank(scan, {"AUSDT": ("up", "up"), "BUSDT": ("up", "up")}))

    def no_candles(*_):
        raise RuntimeError("offline")

    rows = bs.journal_rows(picks, no_candles, first_id=40, day="2026-09-27",
                           when_utc="2026-09-27 14:30", list_name="27 Sep 14:30")
    by = {r["coin"]: r for r in rows}
    assert by["A"]["entry_rule"] == "now" and by["A"]["entry_price"] == 100.0
    assert by["B"]["entry_rule"] == "close_above" and by["B"]["trigger"] == 99.0
    assert {r["id"] for r in rows} == {40, 41}
    assert by["A"]["list"] == "27 Sep 14:30 buy now"
