"""Signal-quality diagnostics: forward returns at fixed horizons, no exits.

If an entry has no positive drift at ANY horizon, exit engineering cannot save
it. Run:  python -m backend.research.diagnose
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from backend.config import load_config
from . import data as data_mod
from .run import COINS, DAYS, IS_FRACTION, build_preps
from . import strategy

HORIZONS = (6, 12, 24, 48, 96)


def forward_stats(preps: dict, params: dict, cutoff: pd.Timestamp) -> dict:
    rows_is, rows_oos = [], []
    for coin, prep in preps.items():
        closes = prep.df["close"].to_numpy()
        n = len(closes)
        for sig in strategy.gen_signals(prep, params):
            i = prep.df.index.get_loc(sig.ts)
            entry_i = i + 1
            if entry_i >= n:
                continue
            entry = closes[entry_i]
            rec = {}
            for h in HORIZONS:
                j = min(entry_i + h, n - 1)
                rec[h] = (closes[j] / entry - 1) * 100
            (rows_is if prep.df.index[entry_i] < cutoff else rows_oos).append(rec)
    out = {}
    for name, rows in (("IS", rows_is), ("OOS", rows_oos)):
        if not rows:
            out[name] = None
            continue
        df = pd.DataFrame(rows)
        out[name] = {
            "n": len(df),
            **{f"mean@{h}": round(df[h].mean(), 3) for h in HORIZONS},
            **{f"win@{h}": round((df[h] > 0).mean() * 100, 1) for h in (12, 24, 48)},
        }
    return out


VARIANTS = {
    "all_1h_divs":        {"div_tf": "1h", "sl": ("pivot", 0.5)},
    "oversold_-40":       {"div_tf": "1h", "sl": ("pivot", 0.5),
                           "oversold_only": True, "oversold_level": -40},
    "oversold_-53":       {"div_tf": "1h", "sl": ("pivot", 0.5),
                           "oversold_only": True, "oversold_level": -53},
    "div_4h":             {"div_tf": "4h", "sl": ("pivot", 0.5)},
    "multi_tf":           {"div_tf": "1h", "sl": ("pivot", 0.5),
                           "multi_tf_div": True},
    "multi_tf_oversold":  {"div_tf": "1h", "sl": ("pivot", 0.5),
                           "multi_tf_div": True,
                           "oversold_only": True, "oversold_level": -40},
    "multi_tf_btc_ok":    {"div_tf": "1h", "sl": ("pivot", 0.5),
                           "multi_tf_div": True, "btc_regime": "not_bear_1d"},
    "rs4h_bull_div1h":    {"div_tf": "1h", "sl": ("pivot", 0.5),
                           "rs_filter": "4h"},
}


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    config = load_config()
    dataset = data_mod.load_dataset(["BTC"] + COINS, DAYS)
    preps = build_preps(dataset, config)
    spans = [p.df.index for p in preps.values()]
    start = min(ix[0] for ix in spans)
    end = max(ix[-1] for ix in spans)
    cutoff = start + (end - start) * IS_FRACTION

    for name, params in VARIANTS.items():
        st = forward_stats(preps, params, cutoff)
        print(f"\n== {name} ==")
        for split in ("IS", "OOS"):
            print(f"  {split}: {st[split]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
