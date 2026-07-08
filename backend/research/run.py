"""Experiment runner: dataset -> preps -> variant grid -> IS/OOS metrics table.

    python -m backend.research.run                 # run the current VARIANTS grid
    python -m backend.research.run --refresh       # re-download candle history
"""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from backend.config import load_config
from . import data as data_mod
from . import engine, strategy

log = logging.getLogger(__name__)

COINS = ["SOL", "ETH", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "LTC"]
# Wider daily universe: liquid CoinDCX B-*_USDT markets. Newer listings simply
# contribute shorter histories (load_daily_dataset keeps >=300 daily candles).
DAILY_COINS = COINS + [
    "UNI", "ATOM", "NEAR", "FIL", "XLM", "ETC", "BCH", "TRX", "ALGO", "SAND",
    "MANA", "AAVE", "INJ", "APT", "ARB", "OP", "SUI", "RUNE", "GRT", "CRV",
]
DAYS = 540
IS_FRACTION = 0.70


def build_preps(dataset: dict[str, pd.DataFrame], config):
    btc = dataset["BTC"]
    preps = {}
    for coin, df in dataset.items():
        if coin == "BTC":
            continue
        preps[coin] = strategy.prepare(coin, df, btc, config)
        log.info("prepared %s: %d 1h-div, %d 4h-div events", coin,
                 len(preps[coin].div1h), len(preps[coin].div4h))
    return preps


def build_btc_prep(dataset: dict[str, pd.DataFrame], config):
    """BTC's own prep (for BTC-dip signals). RS states vs itself are unused."""
    btc = dataset["BTC"]
    return strategy.prepare("BTC", btc, btc, config)


def run_variant(preps: dict, params: dict, cutoff: pd.Timestamp,
                btc_prep=None):
    """Returns (is_metrics, oos_metrics, all_trades)."""
    all_trades = []
    for coin, prep in preps.items():
        if params.get("signal_source") == "btc_dip":
            sigs = strategy.gen_btc_dip_signals(btc_prep, prep, params)
        else:
            sigs = strategy.gen_signals(prep, params)
        exit_sig = None
        if params.get("exit") == "wt_bear_cross":
            exit_sig = strategy.wt_exit_series(
                prep, level=params.get("exit_level"))
        trades = engine.simulate(
            coin, prep.df, sigs,
            rr_target=params.get("rr", 1.5),
            exit_signal=exit_sig,
            max_hold=params.get("max_hold"))
        all_trades += trades
    is_t = [t for t in all_trades if t.entry_ts < cutoff]
    oos_t = [t for t in all_trades if t.entry_ts >= cutoff]
    return engine.metrics(is_t), engine.metrics(oos_t), all_trades


def table(rows: list[tuple[str, engine.Metrics, engine.Metrics]]) -> str:
    recs = []
    for name, m_is, m_oos in rows:
        r = {"variant": name}
        r.update({f"IS_{k}": v for k, v in m_is.row().items()})
        r.update({f"OOS_{k}": v for k, v in m_oos.row().items()})
        recs.append(r)
    return pd.DataFrame(recs).to_string(index=False)


# ---------------------------------------------------------------------------
# The grid under test — edited between iterations; results go to
# STRATEGY_RESEARCH.md.
# ---------------------------------------------------------------------------
_OS1H = {"div_tf": "1h", "oversold_only": True, "oversold_level": -53}
_DIP = {"signal_source": "btc_dip", "oversold_only": True,
        "oversold_level": -53, "sl": ("atr", 2.0)}

VARIANTS: dict[str, dict] = {
    # A: simultaneous multi-TF stretch — 1h div while last closed 4h WT2 oversold
    "A_htf45_tp0.5":     {**_OS1H, "htf_oversold": -45,
                          "rr": 0.5, "sl": ("atr", 2.5)},
    "A_htf45_tp1.0":     {**_OS1H, "htf_oversold": -45,
                          "rr": 1.0, "sl": ("atr", 2.0)},
    "A_htf53_tp0.5":     {**_OS1H, "htf_oversold": -53,
                          "rr": 0.5, "sl": ("atr", 2.5)},
    "A_htf45_lim":       {**_OS1H, "htf_oversold": -45,
                          "rr": 0.5, "sl": ("atr", 2.5),
                          "entry": ("limit_atr", 0.5, 6)},
    # B: BTC deep-oversold dip -> buy RS-strong alts (beta snap)
    "B_dip_rs4h_tp0.5":  {**_DIP, "rs_filter": "4h", "rr": 0.5},
    "B_dip_rs4h_tp1.0":  {**_DIP, "rs_filter": "4h", "rr": 1.0},
    "B_dip_rs1d_tp1.0":  {**_DIP, "rs_filter": "1d", "rr": 1.0},
    "B_dip_rs4h_hold":   {**_DIP, "rs_filter": "4h", "rr": None,
                          "exit": "wt_bear_cross", "max_hold": 48},
    "B_dip_rs4h_lim":    {**_DIP, "rs_filter": "4h", "rr": 1.0,
                          "entry": ("limit_atr", 0.5, 6)},
}


# Daily-native grid ("div_tf 1h" = the prep's native TF = 1d here;
# "htf_oversold"/"rs_filter 4h" refer to the WEEKLY mappings in prepare_daily).
# Iteration 6: candidates PRE-REGISTERED before seeing the 25-coin data.
_D = {"div_tf": "1h", "oversold_only": True, "oversold_level": -45,
      "sl": ("pivot", 0.5)}
DAILY_VARIANTS: dict[str, dict] = {
    "D1_os45_tp1.5":     {**_D, "rr": 1.5},
    "D2_os45_tp1.5_btc": {**_D, "rr": 1.5, "btc_regime": "not_bear_1d"},
    "D3_os45_wtexit":    {**_D, "rr": None, "exit": "wt_bear_cross",
                          "exit_level": 0, "max_hold": 40},
    "D4_os45_tp1":       {**_D, "rr": 1.0},
    "D5_os53_tp1.5":     {**_D, "oversold_level": -53, "rr": 1.5},
    "D6_os45_tp1_btc":   {**_D, "rr": 1.0, "btc_regime": "not_bear_1d"},
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--days", type=int, default=DAYS)
    parser.add_argument("--tf", choices=["1h", "daily"], default="1h")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    config = load_config()
    if args.tf == "daily":
        days = args.days if args.days != DAYS else 1800
        dataset = data_mod.load_daily_dataset(["BTC"] + DAILY_COINS, days,
                                              refresh=args.refresh)
        if "BTC" not in dataset:
            print("no BTC data; aborting")
            return 1
        btc = dataset["BTC"]
        preps = {}
        for coin, df in dataset.items():
            if coin == "BTC":
                continue
            preps[coin] = strategy.prepare_daily(coin, df, btc, config)
            log.info("prepared %s: %d 1d-div, %d 1w-div events", coin,
                     len(preps[coin].div1h), len(preps[coin].div4h))
        btc_prep = None
        variants = DAILY_VARIANTS
    else:
        dataset = data_mod.load_dataset(["BTC"] + COINS, args.days,
                                        refresh=args.refresh)
        if "BTC" not in dataset:
            print("no BTC data; aborting")
            return 1
        preps = build_preps(dataset, config)
        btc_prep = build_btc_prep(dataset, config)
        variants = VARIANTS

    spans = [p.df.index for p in preps.values()]
    start = min(ix[0] for ix in spans)
    end = max(ix[-1] for ix in spans)
    cutoff = start + (end - start) * IS_FRACTION
    print(f"\ndata {start.date()} .. {end.date()}  |  IS < {cutoff.date()} <= OOS\n")

    rows = []
    for name, params in variants.items():
        m_is, m_oos, _ = run_variant(preps, params, cutoff, btc_prep=btc_prep)
        rows.append((name, m_is, m_oos))
        print(f"done: {name}")
    print()
    print(table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
