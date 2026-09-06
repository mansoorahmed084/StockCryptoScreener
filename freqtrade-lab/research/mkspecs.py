"""Generate the parameter grid for a sweep and split it into N worker files.

    python research/mkspecs.py batch2 4

Writes research/specs/batch2_0.json .. batch2_3.json so several processes can
chew through the grid at once.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SPECS_DIR = Path(__file__).resolve().parent / "specs"

GATES = [
    ("nogate", {"kind": "none"}),
    ("btc1d", {"kind": "btc_1d", "allow": ["bull", "neutral"]}),
    ("eth1d", {"kind": "eth_1d", "allow": ["bull", "neutral"]}),
    ("eth4h", {"kind": "eth_4h", "allow": ["bull", "neutral"]}),
]

EXITS = [
    ("fix3R", {"legs": [[3.0, 1.0]], "time_stop_bars": 120}),
    ("G3", {"legs": [[1.0, 0.5], [3.0, 0.5]], "be_after_leg": 0,
            "time_stop_bars": 120}),
    ("G3b", {"legs": [[1.0, 0.34], [2.0, 0.33], [3.0, 0.33]], "be_after_leg": 0,
             "time_stop_bars": 120}),
]


def batch2() -> list[dict]:
    """4h capitulation long — the only arm with a real edge in batch 1.

    Sweeps how deep the oversold has to be, how far the stop sits, how wide the
    pivot is (which sets both sensitivity and the confirmation lag), the regime
    gate, and the exit shape.
    """
    out = []
    for wt2 in (-30.0, -35.0, -40.0, -45.0, -50.0, -55.0, -60.0):
        for amult in (0.25, 0.5, 1.0, 1.5):
            for piv in (2, 3, 4):
                for gname, gate in GATES:
                    for ename, exit_ in EXITS:
                        out.append({
                            "label": f"4hcap wt2<={wt2:g} atr{amult:g} piv{piv} {gname} {ename}",
                            "family": "vmc_divergence", "tf": "4h", "side": "long",
                            "params": {"wt2_extreme": wt2, "atr_mult": amult,
                                       "pivot_lookback": piv},
                            "gate": gate, "exit": exit_,
                        })
    return out


def batch3() -> list[dict]:
    """1h capitulation long — same grid, coarser, plus a volatility floor.

    Batch 1 put raw 1h at 30.9% / +0.10R. The question is whether a regime gate
    or a volatility floor can lift it, or whether 1h is simply too noisy.
    """
    out = []
    for wt2 in (-45.0, -50.0, -55.0, -60.0):
        for amult in (0.5, 1.0, 1.5):
            for piv in (3, 4, 5):
                for gname, gate in GATES:
                    for vol in (None, 0.5, 0.7):
                        for ename, exit_ in EXITS[:2]:
                            out.append({
                                "label": f"1hcap wt2<={wt2:g} atr{amult:g} piv{piv} "
                                         f"{gname} vol{vol} {ename}",
                                "family": "vmc_divergence", "tf": "1h", "side": "long",
                                "params": {"wt2_extreme": wt2, "atr_mult": amult,
                                           "pivot_lookback": piv},
                                "gate": gate, "vol_min": vol,
                                "exit": {**exit_, "time_stop_bars": 240},
                            })
    return out


WIDE_EXITS = [
    ("fix3R", {"legs": [[3.0, 1.0]]}),
    ("G3", {"legs": [[1.0, 0.5], [3.0, 0.5]], "be_after_leg": 0}),
    ("G075", {"legs": [[0.75, 0.5], [3.0, 0.5]], "be_after_leg": 0}),
    ("G15", {"legs": [[1.5, 0.5], [3.0, 0.5]], "be_after_leg": 0}),
    ("Gthird", {"legs": [[1.0, 0.34], [2.0, 0.33], [3.0, 0.33]], "be_after_leg": 0}),
    ("Grunner", {"legs": [[1.0, 0.3], [3.0, 0.7]], "be_after_leg": 0}),
    ("Gbank", {"legs": [[1.0, 0.7], [3.0, 0.3]], "be_after_leg": 0}),
]


def batch4() -> list[dict]:
    """4h capitulation, second pass.

    Batch 2 said three things: every regime gate starves ETH of signals, the
    stop wants to be WIDE (avgR rose monotonically to the 1.5 grid edge), and
    exit shape trades win rate against expectancy exactly as the repo's
    Iteration F predicted. So: push atr_mult past the edge, raise the risk cap
    so wide stops are not silently filtered out, and test seven exit shapes.
    """
    out = []
    for wt2 in (-35.0, -40.0, -45.0, -50.0):
        for amult in (1.5, 2.0, 2.5, 3.0, 4.0):
            for maxrisk in (0.10, 0.15, 0.20):
                for piv in (2, 3):
                    for ename, exit_ in WIDE_EXITS:
                        out.append({
                            "label": f"4hcap wt2<={wt2:g} atr{amult:g} risk{maxrisk:g} "
                                     f"piv{piv} nogate {ename}",
                            "family": "vmc_divergence", "tf": "4h", "side": "long",
                            "params": {"wt2_extreme": wt2, "atr_mult": amult,
                                       "pivot_lookback": piv,
                                       "max_risk_pct": maxrisk},
                            "gate": {"kind": "none"},
                            "exit": {**exit_, "time_stop_bars": 120},
                        })
    return out


def batch5() -> list[dict]:
    """1h capitulation, refined — batch 3's surprise.

    On 4h every regime gate starved the signal. On 1h the opposite: the ETH
    daily gate was the single strongest dial (+0.115 avgR vs -0.170 ungated),
    because 1h produces enough signals to afford a filter. The volatility floor
    hurt everywhere, so it is dropped. Wider pivots (4-5) beat 3, so the pivot
    range moves up. Exits now include the G075 shape that topped batch 4.
    """
    out = []
    for gname, gate in (("eth1d", {"kind": "eth_1d", "allow": ["bull", "neutral"]}),
                        ("btc1d", {"kind": "btc_1d", "allow": ["bull", "neutral"]})):
        for wt2 in (-40.0, -45.0, -50.0, -55.0):
            for amult in (0.75, 1.0, 1.25, 1.5, 2.0):
                for piv in (4, 5, 6, 7):
                    for ename, exit_ in WIDE_EXITS:
                        out.append({
                            "label": f"1hcap wt2<={wt2:g} atr{amult:g} piv{piv} "
                                     f"{gname} volNone {ename}",
                            "family": "vmc_divergence", "tf": "1h", "side": "long",
                            "params": {"wt2_extreme": wt2, "atr_mult": amult,
                                       "pivot_lookback": piv},
                            "gate": gate,
                            "exit": {**exit_, "time_stop_bars": 240},
                        })
    return out


HF_FAMILIES = ["ema_pullback", "rsi_reversion", "donchian_break",
               "vol_spike_reversal", "keltner_squeeze", "wt_oversold_cross"]

LOWDD_EXITS = [
    ("fix3R", {"legs": [[3.0, 1.0]]}),
    ("G05", {"legs": [[0.5, 0.5], [3.0, 0.5]], "be_after_leg": 0}),
    ("G075", {"legs": [[0.75, 0.5], [3.0, 0.5]], "be_after_leg": 0}),
    ("G3", {"legs": [[1.0, 0.5], [3.0, 0.5]], "be_after_leg": 0}),
]


def batch6() -> list[dict]:
    """Discovery pass over six high-frequency families.

    Divergence entries cap at 12-18 trades/year, which is not tradeable. These
    fire on single-bar conditions. Coarse grid on purpose: the job here is to
    find which families produce BOTH frequency and edge, not to tune any of them.
    """
    out = []
    for fam in HF_FAMILIES:
        for tf, tstop in (("1h", 240), ("4h", 120)):
            for gname, gate in (("nogate", {"kind": "none"}),
                                ("eth1d", {"kind": "eth_1d",
                                           "allow": ["bull", "neutral"]})):
                for amult in (1.0, 2.0):
                    for ename, exit_ in LOWDD_EXITS:
                        out.append({
                            "label": f"{fam} {tf} atr{amult:g} {gname} {ename}",
                            "family": fam, "tf": tf, "side": "long",
                            "params": {"atr_mult": amult},
                            "gate": gate,
                            "exit": {**exit_, "time_stop_bars": tstop},
                        })
    return out


# The trader described a 2-3% move, not an R multiple, so both target styles
# are tested side by side.
USER_EXITS = [
    ("pct2", {"legs": [[0.02, 1.0]], "target_mode": "pct"}),
    ("pct3", {"legs": [[0.03, 1.0]], "target_mode": "pct"}),
    ("pctScale", {"legs": [[0.015, 0.5], [0.03, 0.5]], "be_after_leg": 0,
                  "target_mode": "pct"}),
    ("fix3R", {"legs": [[3.0, 1.0]]}),
    ("G075", {"legs": [[0.75, 0.5], [3.0, 0.5]], "be_after_leg": 0}),
]

# Switch exactly one condition off at a time. That is what makes it an ablation
# rather than a beauty contest between bundles.
CONDITION_SETS = [
    ("full", {}),
    ("noTrend", {"use_trend": False}),
    ("noReset", {"use_reset": False}),
    ("noCross", {"use_cross": False}),
    ("noRsi", {"use_rsi": False}),
    ("withDiv", {"require_div": True}),
]


def batch7() -> list[dict]:
    """Ablation of the trader's own setup, long and short, 4h and 1h.

    "Overall trend is up" is applied as the DAILY regime gate, not a same-chart
    EMA: a first pass with a same-timeframe EMA200 filter produced n=1 in six
    years, because 4h RSI under 30 and 4h price above its own EMA200 almost
    never coincide. The gate is the honest reading and it is the dial that
    batch 5 already proved carries weight.

    Question 1: does the bundle work?
    Question 2: which condition carries it? Each is switched off in turn.
    Question 3: is the trader's 2-3% target better than a risk-multiple target?
    """
    conds = [("full", {}), ("noCross", {"use_cross": False}),
             ("noRsi", {"use_rsi": False}), ("withDiv", {"require_div": True})]
    exits = [("pct2", {"legs": [[0.02, 1.0]], "target_mode": "pct"}),
             ("pct3", {"legs": [[0.03, 1.0]], "target_mode": "pct"}),
             ("pctScale", {"legs": [[0.015, 0.5], [0.03, 0.5]],
                           "be_after_leg": 0, "target_mode": "pct"}),
             ("fix3R", {"legs": [[3.0, 1.0]]})]
    out = []
    for tf, tstop in (("4h", 120), ("1h", 240)):
        for side in ("long", "short"):
            allow = ["bull", "neutral"] if side == "long" else ["bear", "neutral"]
            for gname, gate in (("nogate", {"kind": "none"}),
                                ("eth1d", {"kind": "eth_1d", "allow": allow})):
                for rsi_x in (30.0, 35.0, 40.0):
                    for stoch_r in (20.0, 30.0):
                        for cname, cparams in conds:
                            for ename, exit_ in exits:
                                out.append({
                                    "label": f"stochRsi {tf} {side} {cname} "
                                             f"rsi{rsi_x:g} st{stoch_r:g} "
                                             f"{gname} {ename}",
                                    "family": "stoch_rsi_reset", "tf": tf,
                                    "side": side,
                                    "params": {**cparams, "atr_mult": 1.0,
                                               "rsi_extreme": rsi_x,
                                               "stoch_reset": stoch_r},
                                    "gate": gate,
                                    "exit": {**exit_, "time_stop_bars": tstop},
                                })
    return out


def batch8() -> list[dict]:
    """The trader's reset filters bolted onto the high-frequency pullback.

    Batch 6 found the EMA pullback runs 83 trades/year at 68.7% net-win behind
    the daily gate, but earns only +0.078R per trade with a 21.8R drawdown.
    Frequency is solved; quality is not. The trader's own rule says a pullback
    is only worth taking once the oscillators have RESET. This measures exactly
    that: does demanding stochastic-oversold-and-crossing, and RSI low and
    turning up, raise expectancy enough to be worth the trades it removes?

    stoch_max=None / rsi_max=None / stoch_cross=False are the control arms.
    """
    out = []
    exits = [("G05", {"legs": [[0.5, 0.5], [3.0, 0.5]], "be_after_leg": 0}),
             ("G075", {"legs": [[0.75, 0.5], [3.0, 0.5]], "be_after_leg": 0}),
             ("fix3R", {"legs": [[3.0, 1.0]]}),
             ("pct2", {"legs": [[0.02, 1.0]], "target_mode": "pct"}),
             ("pct3", {"legs": [[0.03, 1.0]], "target_mode": "pct"})]
    for tf, tstop in (("4h", 120), ("1h", 240)):
        for side in ("long", "short"):
            allow = ["bull", "neutral"] if side == "long" else ["bear", "neutral"]
            gate = {"kind": "eth_1d", "allow": allow}
            for ema_len in (20, 50):
                for stoch_max in (None, 30.0, 20.0):
                    for cross in (True, False):
                        for rsi_max in (None, 45.0, 35.0):
                            for ename, exit_ in exits:
                                sm = "None" if stoch_max is None else f"{stoch_max:g}"
                                rm = "None" if rsi_max is None else f"{rsi_max:g}"
                                out.append({
                                    "label": f"pbReset {tf} {side} ema{ema_len} "
                                             f"sto{sm} x{int(cross)} rsi{rm} "
                                             f"eth1d {ename}",
                                    "family": "pullback_reset", "tf": tf,
                                    "side": side,
                                    "params": {"ema_len": ema_len,
                                               "stoch_max": stoch_max,
                                               "stoch_cross": cross,
                                               "rsi_max": rsi_max,
                                               "atr_mult": 1.0},
                                    "gate": gate,
                                    "exit": {**exit_, "time_stop_bars": tstop},
                                })
    return out


def batch9() -> list[dict]:
    """Drawdown refinement of the batch-8 leader.

    Batch 8 found 4h EMA20 pullback + stochastic cross + daily gate + fixed 3R:
    49 trades/year at +0.285R, four times the expectancy of the plain pullback.
    The stochastic cross is doing real work. What it does NOT have is an
    acceptable drawdown: 40.5R, with a 15-trade losing streak.

    Scale-out did not help this entry (batch 8 rows 9-10: drawdown fell to 21.8R
    but expectancy collapsed to +0.01R), so drawdown has to come from the entry
    and the stop instead. Sweeps stop width, swing lookback, how many bars the
    reset may lag, EMA length, gate choice, and lower fixed targets - a 2R
    target should convert more trades and shorten losing runs.
    """
    out = []
    exits = [("t2R", {"legs": [[2.0, 1.0]]}),
             ("t2.5R", {"legs": [[2.5, 1.0]]}),
             ("fix3R", {"legs": [[3.0, 1.0]]}),
             ("G1", {"legs": [[1.0, 0.5], [3.0, 0.5]], "be_after_leg": 0}),
             ("G15", {"legs": [[1.5, 0.5], [3.0, 0.5]], "be_after_leg": 0})]
    for side in ("long", "short"):
        allow = ["bull", "neutral"] if side == "long" else ["bear", "neutral"]
        for gname, gate in (("eth1d", {"kind": "eth_1d", "allow": allow}),
                            ("btc1d", {"kind": "btc_1d", "allow": allow})):
            for ema_len in (20, 34):
                for amult in (0.5, 1.0, 1.5, 2.0):
                    for swing in (5, 10):
                        for within in (2, 5):
                            for ename, exit_ in exits:
                                out.append({
                                    "label": f"pb9 4h {side} ema{ema_len} "
                                             f"atr{amult:g} sw{swing} w{within} "
                                             f"{gname} {ename}",
                                    "family": "pullback_reset", "tf": "4h",
                                    "side": side,
                                    "params": {"ema_len": ema_len,
                                               "stoch_max": None,
                                               "stoch_cross": True,
                                               "rsi_max": None,
                                               "rsi_turning": False,
                                               "swing_len": swing,
                                               "within": within,
                                               "atr_mult": amult},
                                    "gate": gate,
                                    "exit": {**exit_, "time_stop_bars": 120},
                                })
    return out





BATCHES = {"batch2": batch2, "batch3": batch3, "batch4": batch4,
           "batch5": batch5, "batch6": batch6, "batch7": batch7,
           "batch8": batch8, "batch9": batch9}


def main() -> None:
    name, workers = sys.argv[1], int(sys.argv[2])
    specs = BATCHES[name]()
    SPECS_DIR.mkdir(parents=True, exist_ok=True)
    for w in range(workers):
        chunk = specs[w::workers]
        path = SPECS_DIR / f"{name}_{w}.json"
        path.write_text(json.dumps(chunk, indent=1), encoding="utf-8")
        print(f"{path.name}: {len(chunk)} runs")
    print(f"total {len(specs)} runs")


if __name__ == "__main__":
    main()
