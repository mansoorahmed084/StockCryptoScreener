import numpy as np
import pandas as pd

from backend.research.engine import Signal, metrics, simulate
from .util import make_ohlcv


def _df(rows):
    """rows: list of (open, high, low, close)."""
    idx = pd.date_range("2025-01-01", periods=len(rows), freq="1h", tz="UTC",
                        name="ts")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1000.0
    return df


def test_entry_next_open_and_target_fill():
    df = _df([
        (100, 101, 99, 100),   # signal candle
        (100, 100.5, 99.5, 100),  # entry at open=100
        (100, 104, 99.8, 103),    # target 1.5R = 100+1.5*2=103 -> hit
    ])
    sig = Signal(ts=df.index[0], stop=98.0)
    trades = simulate("X", df, [sig], rr_target=1.5, fee_pct=0, slip_pct=0)
    assert len(trades) == 1
    t = trades[0]
    assert t.entry == 100.0
    assert t.reason == "target"
    assert abs(t.r - 1.5) < 1e-9


def test_stop_before_target_same_candle():
    df = _df([
        (100, 101, 99, 100),
        (100, 100.5, 99.5, 100),
        (100, 105, 97, 104),   # touches both stop (98) and target (103)
    ])
    sig = Signal(ts=df.index[0], stop=98.0)
    trades = simulate("X", df, [sig], rr_target=1.5, fee_pct=0, slip_pct=0)
    assert trades[0].reason == "stop"       # conservative ordering
    assert abs(trades[0].r - (-1.0)) < 1e-9


def test_gap_below_stop_fills_at_open():
    df = _df([
        (100, 101, 99, 100),
        (100, 100.5, 99.5, 100),
        (95, 96, 94, 95),      # gaps through the 98 stop
    ])
    sig = Signal(ts=df.index[0], stop=98.0)
    trades = simulate("X", df, [sig], rr_target=1.5, fee_pct=0, slip_pct=0)
    assert trades[0].reason == "stop"
    assert trades[0].exit == 95.0           # open, not the stop price
    assert trades[0].r < -1.0               # worse than -1R, as it should be


def test_no_overlapping_positions_per_coin():
    rows = [(100, 101, 99, 100)] * 10
    df = _df(rows)
    sigs = [Signal(ts=df.index[0], stop=95.0), Signal(ts=df.index[2], stop=95.0)]
    trades = simulate("X", df, sigs, rr_target=None, max_hold=5,
                      fee_pct=0, slip_pct=0)
    assert len(trades) == 1                 # second signal ignored while in trade


def test_exit_signal_exits_next_open():
    df = _df([
        (100, 101, 99, 100),
        (100, 101, 99.5, 100.5),
        (100.5, 101, 100, 100.8),   # exit signal at this close
        (101, 102, 100.5, 101.5),   # exit at open=101
    ])
    exit_sig = pd.Series([False, False, True, False], index=df.index)
    sig = Signal(ts=df.index[0], stop=97.0)
    trades = simulate("X", df, [sig], rr_target=None, exit_signal=exit_sig,
                      fee_pct=0, slip_pct=0)
    assert trades[0].reason == "signal_exit"
    assert trades[0].exit == 101.0


def test_fees_reduce_r():
    df = _df([
        (100, 101, 99, 100),
        (100, 100.5, 99.5, 100),
        (100, 104, 99.8, 103),
    ])
    sig = Signal(ts=df.index[0], stop=98.0)
    gross = simulate("X", df, [sig], rr_target=1.5, fee_pct=0, slip_pct=0)[0].r
    net = simulate("X", df, [sig], rr_target=1.5)[0].r
    assert net < gross


def test_limit_entry_fills_on_touch_and_expires():
    df = _df([
        (100, 101, 99, 100),      # signal
        (100, 101, 99.6, 100.5),  # low 99.6 > limit 99.5 -> no fill
        (100.5, 101, 99.4, 100),  # low 99.4 <= 99.5 -> fill at limit
        (100, 104, 99.8, 103),
    ])
    sig = Signal(ts=df.index[0], stop=97.0, limit=99.5, ttl=6)
    trades = simulate("X", df, [sig], rr_target=1.0, fee_pct=0, slip_pct=0)
    assert len(trades) == 1
    assert trades[0].entry == 99.5

    # never touched within ttl -> no trade
    df2 = _df([(100, 101, 99.9, 100)] + [(100, 101, 99.8, 100)] * 4)
    sig2 = Signal(ts=df2.index[0], stop=97.0, limit=99.0, ttl=3)
    assert simulate("X", df2, [sig2], rr_target=1.0) == []


def test_limit_fill_bar_cannot_hit_target_same_bar():
    # fill bar's high exceeds the target, but intrabar sequence is unknowable:
    # the target must NOT fill on the fill bar; next bar hits it legitimately.
    df = _df([
        (100, 101, 99, 100),        # signal
        (100.5, 102, 99.4, 101),    # fills limit 99.5 AND high 102 > target
        (101, 102, 100.2, 101.5),   # target (100.25) legitimately hit here
    ])
    sig = Signal(ts=df.index[0], stop=98.0, limit=99.5, ttl=6)
    trades = simulate("X", df, [sig], rr_target=0.5, fee_pct=0, slip_pct=0)
    t = trades[0]
    assert t.entry == 99.5
    assert t.reason == "target"
    assert t.exit_ts == df.index[2]     # NOT the fill bar
    assert t.bars == 2


def test_limit_fill_bar_can_still_stop_out():
    df = _df([
        (100, 101, 99, 100),
        (100.5, 101, 97.5, 98),     # fills limit 99.5, keeps falling through 98
    ])
    sig = Signal(ts=df.index[0], stop=98.0, limit=99.5, ttl=6)
    trades = simulate("X", df, [sig], rr_target=0.5, fee_pct=0, slip_pct=0)
    assert trades[0].reason == "stop"
    assert trades[0].exit_ts == df.index[1]


def test_trailing_stop_ratchets_up_and_exits():
    df = _df([
        (100, 101, 99, 100),        # signal
        (100, 106, 99.9, 105),      # entry 100; trail raises stop to 103
        (105, 107, 104, 106),       # trail -> 104
        (106, 106.5, 103.5, 104),   # low 103.5 <= stop 104 -> stopped at 104
    ])
    trail = pd.Series([float("nan"), 103.0, 104.0, 101.0], index=df.index)
    sig = Signal(ts=df.index[0], stop=95.0)
    trades = simulate("X", df, [sig], rr_target=None, trail_stop=trail,
                      fee_pct=0, slip_pct=0)
    t = trades[0]
    assert t.reason == "stop"
    assert t.exit == 104.0          # ratcheted stop, never lowered by the 101
    assert t.r > 0                  # trailed into profit


def test_scale_out_then_breakeven_stop_is_small_win():
    # risk = 2 (entry 100, stop 98); scale half at +1R (102), stop -> entry;
    # price then returns and stops the rest at breakeven -> +0.5R net (ex costs)
    df = _df([
        (100, 101, 99, 100),
        (100, 100.5, 99.5, 100),   # entry at 100
        (100, 102.5, 99.9, 102),   # hits 102 -> scale, stop moves to 100
        (102, 102.5, 99.5, 99.8),  # low <= 100 -> remaining stopped at 100
    ])
    sig = Signal(ts=df.index[0], stop=98.0)
    trades = simulate("X", df, [sig], rr_target=3.0, scale_out=(0.5, 1.0),
                      fee_pct=0, slip_pct=0)
    t = trades[0]
    assert t.reason == "stop+scaled"
    assert abs(t.r - 0.5) < 1e-9
    assert t.r > 0                          # counted as a win, legitimately


def test_scale_out_then_runner_target():
    df = _df([
        (100, 101, 99, 100),
        (100, 100.5, 99.5, 100),
        (100, 102.5, 99.9, 102),   # scale at 102 (+1R)
        (102, 106.5, 101.5, 106),  # runner target 3R = 106
    ])
    sig = Signal(ts=df.index[0], stop=98.0)
    trades = simulate("X", df, [sig], rr_target=3.0, scale_out=(0.5, 1.0),
                      fee_pct=0, slip_pct=0)
    t = trades[0]
    assert t.reason == "target+scaled"
    assert abs(t.r - 2.0) < 1e-9            # 0.5*1R + 0.5*3R


def test_stop_before_scale_is_full_loss():
    df = _df([
        (100, 101, 99, 100),
        (100, 100.5, 99.5, 100),
        (100, 102.5, 97.5, 98),    # touches both 102 and 98 -> stop first
    ])
    sig = Signal(ts=df.index[0], stop=98.0)
    trades = simulate("X", df, [sig], rr_target=3.0, scale_out=(0.5, 1.0),
                      fee_pct=0, slip_pct=0)
    assert trades[0].reason == "stop"
    assert abs(trades[0].r - (-1.0)) < 1e-9


def test_metrics_drawdown():
    from backend.research.engine import Trade
    ts = pd.Timestamp("2025-01-01", tz="UTC")
    mk = lambda r, i: Trade("X", ts, ts + pd.Timedelta(hours=i), 100, 100, 95,
                            None, r, r, "target", 1)
    m = metrics([mk(-1, 1), mk(-1, 2), mk(2, 3)], risk_per_trade=0.01)
    assert m.n == 3
    assert abs(m.win_rate - 1 / 3) < 1e-9
    assert m.max_dd_pct > 1.9  # two consecutive -1R at 1% risk ≈ 1.99% DD
