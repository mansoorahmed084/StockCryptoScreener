"""Replay scan_smc.py's own code on backtest data and check it agrees with
the backtest, trade for trade.

    python research/scan_smc_check.py [n_coins]

For every backtest trade of B_final on a sample of coins, the scanner is run
as if it were that moment:
  * at the trade's entry candle  -> it must report the trade as NEW
  * a few candles into the trade -> it must report it as OPEN, same stop
  * one candle after the exit    -> it must report it as CLOSED, same reason
plus random moments, where it must report exactly what the backtest holds.

The scanner only ever sees the last 1000 4h and 400 daily CLOSED candles and
the open of the forming candle, the same windows it gets live. So this also
tests that the structure state settles inside those windows.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smc        # noqa: E402
import smc_oos    # noqa: E402
import scan_smc   # noqa: E402

BASE = "1h"
BAR = scan_smc.BAR


def frames_at(coin: str, cut: pd.Timestamp):
    """What the live scanner would have at time `cut` (a 4h boundary)."""
    L = smc.bars(coin, "4h", BASE)
    D = smc.bars(coin, "1d", BASE)
    closed = scan_smc.closed_only(L, "4h", cut).iloc[-scan_smc.N_LTF:]
    daily = scan_smc.closed_only(D, "1d", cut).iloc[-scan_smc.N_HTF:]
    if cut not in L.index:
        return None
    ltf = scan_smc.with_open_bar(closed, cut, float(L.loc[cut, "open"]))
    return ltf, daily


def expected(tr: pd.DataFrame, cut: pd.Timestamp) -> dict:
    last = cut - BAR
    new = tr[tr.sig == last]
    held = tr[(tr.entry_time <= last) & (tr.exit_time > last)]
    ended = tr[tr.exit_time == last]
    return {"new": new.iloc[-1] if len(new) else None,
            "open": held.iloc[-1] if len(held) else None,
            "closed": ended.iloc[-1] if len(ended) else None}


def same(a, b, keys) -> bool:
    if a is None or b is None:
        return a is None and b is None
    for k in keys:
        x, y = a[k], b[k]
        if isinstance(x, float):
            if abs(x - y) > 1e-9 * max(1.0, abs(x)):
                return False
        elif x != y:
            return False
    return True


def main(n_coins: int = 40) -> None:
    random.seed(7)
    old = [c for c in smc.UNIVERSE if smc.have(c, BASE)]
    coins = random.sample(old + smc_oos.new_coins(), n_coins)
    cfg = scan_smc.CFG
    checks = fails = 0
    kinds = {"new": 0, "open": 0, "closed": 0, "none": 0}
    for coin in coins:
        tr = smc.run(coin, cfg, BASE)
        L = smc.bars(coin, "4h", BASE)
        start = L.index[min(len(L) - 1, scan_smc.N_LTF + 10)]
        cuts = set()
        for t in tr.itertuples():
            if t.entry_time >= start:
                cuts.add(t.entry_time)                       # NEW
                cuts.add(t.entry_time + 3 * BAR)             # OPEN
            if t.exit_time >= start and t.why != "data_end":
                cuts.add(t.exit_time + BAR)                  # CLOSED
        pool = L.index[L.index >= start]
        cuts.update(random.sample(list(pool), min(20, len(pool))))
        for cut in sorted(cuts):
            fr = frames_at(coin, cut)
            if fr is None:
                continue
            got = scan_smc.evaluate(coin, fr[0], fr[1], cut)
            exp = expected(tr, cut)
            for k, keys in (("new", ["entry_time", "dir", "entry", "stop"]),
                            ("open", ["entry_time", "dir", "entry", "stop"]),
                            ("closed", ["entry_time", "exit_time", "why", "r"])):
                checks += 1
                if exp[k] is not None:
                    kinds[k] += 1
                ok = same(got[k], exp[k], keys)
                if not ok:
                    fails += 1
                    print(f"MISMATCH {coin} {cut} {k}: scanner "
                          f"{None if got[k] is None else {x: got[k][x] for x in keys}} "
                          f"backtest {None if exp[k] is None else {x: exp[k][x] for x in keys}}")
        for f in (smc.bars, smc.structure, smc.htf_on_ltf, smc.extras):
            f.cache_clear()
    print(f"\n{checks} checks on {len(coins)} coins: {fails} mismatches. "
          f"Backtest events covered: {kinds['new']} NEW, {kinds['open']} OPEN, "
          f"{kinds['closed']} CLOSED.")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
