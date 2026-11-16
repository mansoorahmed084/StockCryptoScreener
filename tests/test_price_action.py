import numpy as np
import pandas as pd

from backend.screener import price_action as pa


def _frame(rows, freq="4h"):
    """rows: (open, high, low, close) tuples."""
    idx = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 10.0
    return df


def _wave(mid, wick=0.3):
    mid = np.asarray(mid, float)
    op = np.concatenate([[mid[0]], mid[:-1]])
    return list(zip(op, np.maximum(op, mid) + wick, np.minimum(op, mid) - wick, mid))


def _arr(df):
    return pa._arrays(df)


def test_pivots_need_k_bars_each_side():
    h = np.array([1, 2, 5, 2, 1, 1, 1.0])
    l = h - 0.5
    highs, _ = pa.pivots(h, l, 2)
    assert highs == [(2, 5.0)]
    highs, _ = pa.pivots(h[:4], l[:4], 2)     # only one bar to the right
    assert highs == []


def test_close_above_swing_high_is_choch_then_bos():
    # up to 10, dip, break 10 (first break = CHoCH), dip, break the new high (BOS)
    mid = [5, 6, 7, 8, 10, 8, 7, 6, 7, 9, 11, 12, 14, 12, 11, 10, 11, 13, 15, 16, 16, 16]
    df = _frame(_wave(mid))
    o, h, l, c, v = _arr(df)
    br, obs, trend = pa.structure(o, h, l, c, v, 2, "internal")
    assert [b.kind for b in br][:2] == ["CHoCH", "BOS"]
    assert all(b.side == pa.BULL for b in br[:2])
    assert br[0].level == h[4]
    assert trend[-1] == pa.BULL
    # the order block is a bearish candle at or before the leg's low
    ob = obs[0]
    assert c[ob.i] < o[ob.i] and ob.i <= br[0].origin_i


def test_legs_structure_is_the_luxalgo_rule():
    """Swings need only beat the bars AFTER them (the later of equal highs wins), and each swing breaks once."""
    mid = [5, 6, 7, 8, 10, 8, 7, 6, 7, 9, 11, 12, 14, 12, 11, 10, 11, 13, 15, 16, 16, 16]
    df = _frame(_wave(mid))
    o, h, l, c, v = _arr(df)
    br, obs, trend = pa.structure_legs(o, h, l, c, v, 2, "internal")
    assert [b.kind for b in br][:2] == ["CHoCH", "BOS"] and all(b.side == pa.BULL for b in br[:2])
    assert h[4] == h[5] and br[0].level_i == 5 and br[0].level == h[5]    # equal highs: the later bar is the swing
    assert br[1].level_i == 13
    assert trend[-1] == pa.BULL
    assert len(obs) == len(br) and c[obs[0].i] < o[obs[0].i] and obs[0].i <= br[0].origin_i


def test_legs_structure_breaks_each_swing_once_on_noise():
    rng = np.random.default_rng(7)
    mid = 100 + np.cumsum(rng.normal(0, 1, 800))
    df = _frame(_wave(mid, wick=0.4))
    o, h, l, c, v = _arr(df)
    br, _, trend = pa.structure_legs(o, h, l, c, v, 5, "internal")
    assert len(br) > 20
    assert len({(b.side, b.level_i) for b in br}) == len(br)              # no swing is broken twice
    for b in br:                                                          # a close really crossed the level
        assert (c[b.i] > b.level and c[b.i - 1] <= b.level) if b.side == pa.BULL else (c[b.i] < b.level and c[b.i - 1] >= b.level)
        assert b.level_i <= b.i - 5                                       # known only k bars after it printed
    kinds = [(b.side, b.kind) for b in br]
    assert all(kind == "BOS" for (side, kind), prev in zip(kinds[1:], kinds) if prev[0] == side)
    assert all(kind == "CHoCH" for (side, kind), prev in zip(kinds[1:], kinds) if prev[0] != side)


def test_analyse_internal_structure_defaults_to_the_leg_engine_at_5():
    t = np.arange(400)
    df = _frame(_wave(100 + 10 * np.sin(t / 9) + 0.05 * t))
    o, h, l, c, v = _arr(df.iloc[:-1])
    cx = pa.analyse(df)
    ref, _, _ = pa.structure_legs(o, h, l, c, v, 5, "internal")
    assert [(b.i, b.side, b.kind) for b in cx.internal] == [(b.i, b.side, b.kind) for b in ref]
    old = pa.analyse(df, internal_engine="pivots", k_internal=5)
    ref_old, _, _ = pa.structure(o, h, l, c, v, 5, "internal")
    assert [(b.i, b.side, b.kind) for b in old.internal] == [(b.i, b.side, b.kind) for b in ref_old]


def test_liquidity_grab_vs_break():
    rows = _wave([5, 6, 7, 8, 10, 8, 7, 6, 6, 6])
    rows += [(6, 10.5, 6, 9.5)]              # wick above the 10.3 high, close back
    rows += _wave([9, 8, 8, 8])
    rows += [(8, 11, 8, 10.8)]               # now a close above
    df = _frame(rows)
    o, h, l, c, v = _arr(df)
    liq = pa.liquidity(h, l, c, v, 2)
    top = next(x for x in liq if x.side == pa.BULL and x.i == 4)
    assert top.status == "grabbed" and top.end_i == 10


def test_order_block_is_mitigated_by_a_close_through_it():
    mid = [5, 6, 7, 8, 10, 8, 7, 6, 7, 9, 11, 12, 11, 10, 9, 8, 6, 4, 3, 3]
    df = _frame(_wave(mid))
    o, h, l, c, v = _arr(df)
    _, obs, _ = pa.structure(o, h, l, c, v, 2, "internal")
    bull = [ob for ob in obs if ob.side == pa.BULL][0]
    assert bull.mitigated_i > bull.formed_i
    assert c[bull.mitigated_i] < bull.bottom


def test_fair_value_gap_found_and_filled():
    rows = [(10, 10.5, 9.5, 10), (10, 13, 10, 13), (13, 14, 12, 13.5),   # gap 10.5..12
            (13.5, 14, 13, 13.8), (13.8, 13.9, 10, 10.2)]                  # filled
    df = _frame(rows * 1)
    o, h, l, c, v = _arr(df)
    gaps = pa.fair_value_gaps(h, l, c, np.full(len(c), 1.0))
    assert len(gaps) == 1 and gaps[0].side == pa.BULL
    assert (gaps[0].bottom, gaps[0].top) == (10.5, 12)
    assert gaps[0].filled_i == 4


def test_daily_trend_uses_only_closed_days():
    days = _frame(_wave([5, 6, 7, 8, 10, 8, 7, 6, 7, 9, 11, 12, 12, 12]), freq="1D")
    ltf = pd.date_range(days.index[0], days.index[-1] + pd.Timedelta("20h"),
                        freq="4h", tz="UTC")
    tr = pa.htf_trend_on(ltf, pd.Timedelta("4h"), days, k=2)
    o, h, l, c, v = _arr(days)
    _, _, dtr = pa.structure(o, h, l, c, v, 2, "d")
    flip = int(np.argmax(dtr == pa.BULL))            # day the daily trend turned up
    first_ltf_up = int(np.argmax(tr == pa.BULL))
    # known only once that day has closed: the first 4h bar opening the next day
    assert ltf[first_ltf_up] + pd.Timedelta("4h") >= days.index[flip] + pd.Timedelta("1D")
    assert ltf[first_ltf_up - 1] + pd.Timedelta("4h") < days.index[flip] + pd.Timedelta("1D")


def test_analyse_drops_the_forming_candle_and_runs_end_to_end():
    t = np.arange(400)
    mid = 100 + 10 * np.sin(t / 9) + 0.05 * t
    df = _frame(_wave(mid))
    days = df.resample("1D").agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"})
    cx = pa.analyse(df, daily=days, ltf_step=pd.Timedelta("4h"))
    assert cx.n == len(df) - 1
    assert cx.swing and cx.internal and cx.liquidity
    assert {"PDH", "PDL"} <= set(cx.htf_levels)
    open_liq = [x for x in cx.liquidity if x.status == "open"]
    assert abs(sum(x.share for x in open_liq) - 1) < 1e-9
    assert pa.notes(cx, float(df["close"].iloc[-1]))


def _crt_rows(bin2):
    rows = [(100, 101, 99, 100)] * 4                                   # bin 0 (skipped)
    rows += [(100, 105, 80, 100)] + [(100, 102, 98, 100)] * 3          # bin 1: range 80..105
    rows += bin2                                                       # bin 2: the sweep
    rows += [(96, 96.5, 85, 86), (86, 87, 79, 80), (80, 81, 79, 80), (80, 81, 79, 80)]
    return _frame(rows, freq="1h")


def test_crt_sweep_confirmed_by_fvg_hits_target():
    df = _crt_rows([(100, 105.5, 99.5, 104),       # wick above 105, close back inside
                    (104, 104, 97, 97.5),
                    (97.5, 99, 96, 96.5),          # high 99 < 99.5: bearish gap
                    (96.5, 97, 95, 96)])
    r = pa.crt(df, "4h")
    assert r.ranges[0].high == 105 and r.ranges[0].low == 80
    s = next(s for s in r.setups if s.side == pa.BEAR)
    assert (s.sweep_i, s.confirm_i, s.trigger) == (8, 10, "FVG")
    assert (s.entry, s.stop, s.target) == (96.5, 105.5, 80)
    assert s.outcome == "won" and s.exit_i == 13
    assert r.stats()["won"] == 1


def test_crt_sweep_without_confirmation_stays_a_sweep():
    df = _crt_rows([(100, 105.5, 100, 104), (104, 105, 103, 104.5),
                    (104.5, 105.2, 104, 104.8), (104.8, 105, 104, 104.6)])
    r = pa.crt(df, "4h")
    s = next(s for s in r.setups if s.side == pa.BEAR)
    assert s.confirm_i == -1 and s.outcome == ""
    assert r.stats()["confirmed"] == 0
