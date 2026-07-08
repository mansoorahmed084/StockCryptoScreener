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
        if params.get("signal_source") == "pullback":
            sig_list = strategy.gen_pullback_signals(prep, params)
        else:
            sig_list = strategy.gen_signals(prep, params)
        for sig in sig_list:
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


_PB = {"signal_source": "pullback", "sl": ("swing", 10, 0.5)}

VARIANTS = {
    "pb_raw":            {**_PB},
    "pb_thrust":         {**_PB, "recent_htf_thrust": (120, 53)},
    "pb_dip30":          {**_PB, "dip_depth": (12, -30)},
    "pb_dip40":          {**_PB, "dip_depth": (12, -40)},
    "pb_ema_rising":     {**_PB, "ema200_up": True, "ema200_rising": 24},
    "pb_thrust_dip":     {**_PB, "recent_htf_thrust": (120, 53),
                          "dip_depth": (12, -30)},
    "pb_thrust_ema":     {**_PB, "recent_htf_thrust": (120, 53),
                          "ema200_up": True, "ema200_rising": 24},
    "pb_all3":           {**_PB, "recent_htf_thrust": (120, 53),
                          "dip_depth": (12, -30),
                          "ema200_up": True, "ema200_rising": 24},
    "pb_all3_wt4h":      {**_PB, "recent_htf_thrust": (120, 53),
                          "dip_depth": (12, -30),
                          "ema200_up": True, "ema200_rising": 24,
                          "htf_wt_min": -20},
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
