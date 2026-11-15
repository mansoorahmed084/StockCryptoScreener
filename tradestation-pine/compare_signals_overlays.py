"""Check the Python twin (freqtrade-lab/research/signals_overlays.py) against the Pine file.

    python compare_signals_overlays.py <bars.csv> <dir written by dump_signals_overlays.ts>

Every plot of every dumped setting is compared bar by bar. Exit code 1 on a mismatch.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "freqtrade-lab" / "research"))

import signals_overlays as so  # noqa: E402

bars = pd.read_csv(sys.argv[1])
bars.index = pd.to_datetime(bars["time"], unit="ms", utc=True)
dump_dir = Path(sys.argv[2])
book = so.Book(bars)
n = len(bars)

# what each dumped setting means in the Python twin
CONFIGS = {
    "conf": {}, "cont": {"mode": "cont"},
    "conf_auto_short": {"auto": "short"}, "conf_auto_medium": {"auto": "medium"},
    "conf_auto_long": {"auto": "long"},
    "cont_auto_short": {"mode": "cont", "auto": "short"},
    "cont_auto_medium": {"mode": "cont", "auto": "medium"},
    "cont_auto_long": {"mode": "cont", "auto": "long"},
    "conf_ml34": {"ml": "34"}, "conf_ml12": {"ml": "12"},
    "cont_ml34": {"mode": "cont", "ml": "34"}, "cont_ml12": {"mode": "cont", "ml": "12"},
    "conf_filt_trail": {"filt": "trail"}, "conf_filt_tracer": {"filt": "tracer"},
    "conf_filt_catcher": {"filt": "catcher"}, "conf_filt_neo": {"filt": "neo"},
    "conf_filt_strength": {"filt": "strength"},
    "conf_sens8": {"sens": 8}, "conf_sens20": {"sens": 20},
    "cont_sens8": {"mode": "cont", "sens": 8}, "cont_sens20": {"mode": "cont", "sens": 20},
}
TPSL = {"conf": "signals", "cont": "trail"}


def python_plots(name: str) -> dict:
    kw = {"mode": "conf", "sens": 12, "auto": "off", "filt": "none", "ml": ""} | CONFIGS[name]
    sig, ex, cls = book.signals(**kw)
    conf_auto = kw["auto"] if kw["mode"] == "conf" else "off"
    flip = book.trail_dir != np.concatenate([[1], book.trail_dir[:-1]])
    out = {
        "sig": sig, "exit": ex, "ml_class": cls,
        "Bar Color Value": book.bar_value(kw["sens"], conf_auto),
        "Optimal Sensitivity": book.optimal(kw["mode"], kw["auto"]),
        "Trend Strength": book.trend_str,
        "trail": book.trail, "trail_dir": book.trail_dir,
        "tracer_dir": book.tracer_dir, "catcher_dir": book.catcher_dir, "neo_dir": book.neo_dir,
    }
    if name in TPSL:        # these two were dumped with every overlay and TP/SL on
        out |= {
            "Smart Trail": np.where(flip, np.nan, book.trail),
            "Trend Tracer": book.tracer, "Trend Catcher": book.catcher,
            "Neo Cloud Lead": book.lead, "Neo Cloud Lag": book.lag,
        }
        out |= {k.upper(): v for k, v in book.rz.items()}
        if TPSL[name] == "signals":
            t_bull, t_bear = sig > 0, sig < 0
        else:
            prev = np.concatenate([[1], book.trail_dir[:-1]])
            t_bull = (book.trail_dir == 1) & (prev == -1)
            t_bear = (book.trail_dir == -1) & (prev == 1)
        lv, _ = book.tpsl(t_bull, t_bear, 5.0)
        out |= {"TP 1": lv[0], "TP 2": lv[1], "SL 1": lv[2], "SL 2": lv[3],
                "Take Profit": lv[0], "Stop Loss": lv[2]}
    return out


bad = 0
for name in CONFIGS:
    pine = pd.read_csv(dump_dir / f"{name}.csv")
    py = python_plots(name)
    worst = []
    for col, want in py.items():
        if col not in pine:
            print(f"{name}: plot '{col}' is not in the Pine dump")
            bad += 1
            continue
        got = pine[col].to_numpy(float)
        want = np.asarray(want, float)
        both_nan = np.isnan(got) & np.isnan(want)
        with np.errstate(invalid="ignore"):
            close = np.abs(got - want) <= 1e-6 * np.maximum(1.0, np.abs(want))
        miss = ~(both_nan | close)
        if miss.any():
            i = int(np.argmax(miss))
            worst.append(f"{col}: {int(miss.sum())} bars differ, first #{i} pine={got[i]} py={want[i]}")
    unchecked = [c for c in pine.columns if c not in py and pine[c].notna().any()]
    if worst:
        bad += 1
        print(f"{name}: MISMATCH\n  " + "\n  ".join(worst))
    else:
        print(f"{name}: {len(py)} plots match on {n} bars"
              + (f" (not compared: {', '.join(unchecked)})" if unchecked else ""))
sys.exit(1 if bad else 0)
