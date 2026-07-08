"""Robustness analysis of a candidate config: parameter nudges, per-coin and
per-year breakdown. A real edge degrades gracefully; an artifact collapses.

    python -m backend.research.analyze
"""
from __future__ import annotations

import logging

import pandas as pd

from backend.config import load_config
from . import data as data_mod
from . import engine, strategy
from .run import DAILY_COINS, IS_FRACTION, run_variant

BASE = {"div_tf": "1h", "oversold_only": True, "oversold_level": -45,
        "sl": ("pivot", 0.5), "rr": 1.5, "btc_regime": "not_bear_1d"}

NUDGES = {
    "base (os-45 buf0.5 tp1.5)": {},
    "os -40":            {"oversold_level": -40},
    "os -50":            {"oversold_level": -50},
    "os -53":            {"oversold_level": -53},
    "buffer 0.3 ATR":    {"sl": ("pivot", 0.3)},
    "buffer 0.7 ATR":    {"sl": ("pivot", 0.7)},
    "tp 1.25R":          {"rr": 1.25},
    "tp 1.75R":          {"rr": 1.75},
    "tp 1.0R":           {"rr": 1.0},
    "tp 2.0R":           {"rr": 2.0},
}


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    config = load_config()
    dataset = data_mod.load_daily_dataset(["BTC"] + DAILY_COINS, 1800)
    btc = dataset["BTC"]
    preps = {c: strategy.prepare_daily(c, df, btc, config)
             for c, df in dataset.items() if c != "BTC"}

    spans = [p.df.index for p in preps.values()]
    start = min(ix[0] for ix in spans)
    end = max(ix[-1] for ix in spans)
    cutoff = start + (end - start) * IS_FRACTION

    print("== parameter nudges (FULL period, gated config) ==")
    recs = []
    for name, delta in NUDGES.items():
        params = {**BASE, **delta}
        _, _, trades = run_variant(preps, params, cutoff)
        m = engine.metrics(trades)
        recs.append({"nudge": name, **m.row()})
    print(pd.DataFrame(recs).to_string(index=False))

    _, _, trades = run_variant(preps, BASE, cutoff)
    tdf = pd.DataFrame([{
        "coin": t.coin, "year": t.entry_ts.year, "r": t.r,
        "win": t.r > 0} for t in trades])

    print("\n== per-coin (base config, full period) ==")
    by_coin = (tdf.groupby("coin")
               .agg(n=("r", "size"), win_pct=("win", "mean"), sumR=("r", "sum"))
               .sort_values("sumR", ascending=False))
    by_coin["win_pct"] = (by_coin["win_pct"] * 100).round(0)
    by_coin["sumR"] = by_coin["sumR"].round(2)
    print(by_coin.to_string())

    print("\n== per-year ==")
    by_year = (tdf.groupby("year")
               .agg(n=("r", "size"), win_pct=("win", "mean"), sumR=("r", "sum")))
    by_year["win_pct"] = (by_year["win_pct"] * 100).round(0)
    by_year["sumR"] = by_year["sumR"].round(2)
    print(by_year.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
