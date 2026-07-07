from backend.screener import filters
from backend.screener.filters import Condition, Filter
from .util import matrix_df


def _df():
    rows = []
    # SOL: bull on all timeframes vs BTC
    for tf in ("1h", "1d", "1w"):
        rows.append({"coin": "SOL", "base": "BTC", "timeframe": tf,
                     "direction": "bull", "strength": 1.5, "rank": 95})
    # ETH: bull 1h/1d, bear 1w
    rows.append({"coin": "ETH", "base": "BTC", "timeframe": "1h",
                 "direction": "bull", "strength": 1.2, "rank": 80})
    rows.append({"coin": "ETH", "base": "BTC", "timeframe": "1d",
                 "direction": "bull", "strength": 0.9, "rank": 70})
    rows.append({"coin": "ETH", "base": "BTC", "timeframe": "1w",
                 "direction": "bear", "strength": -1.1, "rank": 20})
    # DOGE: bear everywhere
    for tf in ("1h", "1d", "1w"):
        rows.append({"coin": "DOGE", "base": "BTC", "timeframe": tf,
                     "direction": "bear", "strength": -1.4, "rank": 10})
    return matrix_df(rows)


def test_and_across_timeframes_full_stack():
    df = _df()
    flt = filters.full_stack_bull("BTC", timeframes=("1h", "1d", "1w"))
    coins = flt.evaluate(df)
    assert coins == {"SOL"}  # only SOL is bull on all three


def test_specific_subject_condition():
    df = _df()
    flt = Filter(logic="AND", conditions=[
        Condition("SOL", "BTC", "1w", "direction", "is", "bull")])
    assert flt.evaluate(df) == {"SOL"}
    flt2 = Filter(logic="AND", conditions=[
        Condition("ETH", "BTC", "1w", "direction", "is", "bull")])
    assert flt2.evaluate(df) == set()  # ETH is bear on 1w


def test_or_logic_union():
    df = _df()
    flt = Filter(logic="OR", conditions=[
        Condition("*", "BTC", "1w", "direction", "is", "bull"),
        Condition("*", "BTC", "1w", "direction", "is", "bear")])
    assert flt.evaluate(df) == {"SOL", "ETH", "DOGE"}


def test_rank_metric_numeric():
    df = _df()
    flt = filters.fresh_momentum("BTC", "1h", min_rank=90)
    assert flt.evaluate(df) == {"SOL"}  # only SOL has rank >= 90 on 1h


def test_unknown_cells_excluded():
    df = matrix_df([
        {"coin": "XRP", "base": "BTC", "timeframe": "1h",
         "direction": "unknown", "strength": float("nan")},
    ])
    flt = Filter(conditions=[Condition("*", "BTC", "1h", "direction", "is", "bull")])
    assert flt.evaluate(df) == set()


def test_serialization_round_trip():
    flt = filters.higher_tf_pullback("ETH")
    restored = Filter.from_dict(flt.to_dict())
    assert restored.to_dict() == flt.to_dict()
