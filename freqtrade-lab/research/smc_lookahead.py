"""Lookahead test for smc.py: truncate the data at several points; every
trade that closed before the cut must be identical with and without the
future attached.

    python research/smc_lookahead.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smc, harness  # noqa: E402
import pandas as pd

cfgs = [smc.Cfg(), smc.Cfg(entry="ob"), smc.Cfg(entry="fvg", discount=True),
        smc.Cfg(entry="ote", ltf="1h", htf="1d"), smc.Cfg(mode="rev", need_swept=True),
        smc.Cfg(mode="both", ltf="15m", htf="1h", exit_choch=True, be_r=1),
        smc.Cfg(ltf="1h", htf="4h", mode="rev", entry="ob", hour_from=12, min_volx=0.9, with_d50=True, max_leg_atr=3.5),
        smc.Cfg(ltf="4h", htf="1d", entry="mkt", choch_only=False, need_swept=True, k_ltf=5, k_htf=2,
                sl_buf=0.5, tp_r=6.0, max_hold=168, exit_choch=True, trail_r=1.5, max_risk=0.08)]
coin = "SOL"
full = harness.load(f"{coin}/USDT", "15m")
bad = 0
for cut in [50000, 120000, 190000]:
    for cfg in cfgs:
        harness._FRAMES[(f"{coin}/USDT", "15m")] = full
        for f in (smc.bars, smc.structure, smc.htf_on_ltf, smc.extras):
            f.cache_clear()
        A = smc.run(coin, cfg)
        harness._FRAMES[(f"{coin}/USDT", "15m")] = full.iloc[:cut]
        for f in (smc.bars, smc.structure, smc.htf_on_ltf, smc.extras):
            f.cache_clear()
        B = smc.run(coin, cfg)
        end = full.index[cut - 1] - pd.Timedelta("2D")
        a = A[A.exit_time < end][["sig", "entry_time", "exit_time", "entry", "stop", "r"]].reset_index(drop=True)
        b = B[B.exit_time < end][["sig", "entry_time", "exit_time", "entry", "stop", "r"]].reset_index(drop=True)
        same = a.equals(b)
        bad += not same
        print(cut, cfg.ltf, cfg.htf, cfg.entry, cfg.mode, len(a), len(b), "OK" if same else "MISMATCH")
        if not same:
            m = a.merge(b, how="outer", indicator=True)
            print(m[m._merge != "both"].head())
harness._FRAMES[(f"{coin}/USDT", "15m")] = full
print("mismatches:", bad)
