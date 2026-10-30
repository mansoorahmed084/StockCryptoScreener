"""Replay the paper journal over past data and check it against the backtest.

    python research/smc_paper_check.py [days] [skip_fraction]

Walks every 4h candle of the last `days` days of the backtest data, runs the
scanner's evaluate() as if live at each one, and feeds the result to
smc_paper.update() -- writing to a scratch copy of the journal, never the
real one. A fraction of runs is skipped at random, as if the PC were asleep.

Passes when:
  * every journal trade, on time or late, is a real backtest trade with the
    same entry, stop and (once closed) the same R
  * every backtest trade inside the window is in the journal, unless every
    run during its whole life was skipped
  * a trade is late exactly when the run at its entry candle was skipped
"""
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smc            # noqa: E402
import scan_smc       # noqa: E402
import scan_smc_check  # noqa: E402
import smc_paper      # noqa: E402

COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT",
         "NEAR", "APT", "ARB", "OP", "SUI", "INJ", "TIA", "FET", "AAVE", "UNI",
         "LDO", "PENDLE", "WLD", "SEI", "HBAR", "ICP", "FIL", "ATOM", "ETC",
         "CRV", "RUNE"]


def main(days: int = 120, skip: float = 0.3) -> None:
    random.seed(11)
    tmp = Path(tempfile.mkdtemp())
    smc_paper.CSV, smc_paper.MD = tmp / "smc_paper.csv", tmp / "SMC_PAPER.md"
    smc_paper.TRADE_MD = tmp / "TRADE_JOURNAL.md"   # absent: the real one is never touched
    scan_smc.scan = lambda **kw: ([], None)      # never reach the live API
    coins = [c for c in COINS if smc.have(c, "1h")]
    end = min(smc.bars(c, "4h", "1h").index[-1] for c in coins)
    cuts = pd.date_range(end - pd.Timedelta(days=days), end, freq="4h")
    bt = pd.concat([smc.run(c, scan_smc.CFG, "1h") for c in coins])
    ran = []
    for cut in cuts:
        if random.random() < skip:
            continue
        ran.append(cut)
        results = []
        for c in coins:
            fr = scan_smc_check.frames_at(c, cut)
            if fr is None:
                continue
            ltf, daily = fr
            live = scan_smc.Live(c, f"{c}USDT", ltf, daily,
                                 float(ltf["open"].iloc[-1]), True)
            results.append((live, 0.0, scan_smc.evaluate(c, ltf, daily, cut)))
        smc_paper.update(results, cut, "replay")
    ran = pd.DatetimeIndex(ran)

    j = smc_paper.load()
    fails = 0
    bt_key = {(c, "long" if d > 0 else "short", smc_paper._ts(t)): row
              for c, d, t, row in zip(bt.coin, bt.dir, bt.entry_time,
                                      bt.itertuples())}
    for r in j.itertuples():
        b = bt_key.get((r.coin, r.side, r.entry_utc))
        if b is None:
            fails += 1
            print("NOT A BACKTEST TRADE", r.coin, r.side, r.entry_utc)
            continue
        if abs(float(r.stop) - b.stop) > 1e-8 * b.stop or abs(float(r.entry) - b.entry) > 1e-8 * b.entry:
            fails += 1
            print("PRICE DIFF", r.coin, r.entry_utc, r.entry, b.entry, r.stop, b.stop)
        if r.status == "closed" and abs(float(r.r) - b.r) > 1e-3:
            fails += 1
            print("R DIFF", r.coin, r.entry_utc, r.r, b.r)
        if r.status == "closed" and r.exit_utc != smc_paper._ts(b.exit_time):
            fails += 1
            print("EXIT DIFF", r.coin, r.entry_utc, r.exit_utc, b.exit_time)
        late_expected = b.entry_time not in ran
        if (r.late == "yes") != late_expected:
            fails += 1
            print("LATE FLAG", r.coin, r.entry_utc, r.late, late_expected)
    window = bt[(bt.entry_time > cuts[0]) & (bt.entry_time <= cuts[-1])]
    missed = 0
    for b in window.itertuples():
        key = (b.coin, "long" if b.dir > 0 else "short", smc_paper._ts(b.entry_time))
        if key in {(r.coin, r.side, r.entry_utc) for r in j.itertuples()}:
            continue
        # catchable if any run saw it open: entry <= cut - 4h < exit
        seen = ((ran - scan_smc.BAR >= b.entry_time) & (ran - scan_smc.BAR < b.exit_time)).any() \
            or (ran == b.entry_time).any()
        if seen:
            fails += 1
            print("MISSING", key)
        else:
            missed += 1
    closed = j[j.status == "closed"]
    print(f"\n{len(ran)}/{len(cuts)} runs over {days} days, {len(coins)} coins. "
          f"Journal: {len(j)} trades ({int((j.late == 'no').sum())} on time, "
          f"{int((j.late == 'yes').sum())} late), {len(closed)} closed. "
          f"Backtest trades in window: {len(window)}; {missed} fell wholly "
          f"inside skipped runs. Failures: {fails}.")
    print(f"scratch journal: {smc_paper.MD}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120,
         float(sys.argv[2]) if len(sys.argv) > 2 else 0.3)
