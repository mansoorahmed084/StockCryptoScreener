"""The SMC research loop: run a round of configs, score them, keep notes.

    python research/smc_loop.py round1          # broad structural grid
    python research/smc_loop.py round2          # tune around round 1's best
    python research/smc_loop.py show <round>    # re-print a finished round

Each round is scored on FIT coins and HOLDOUT coins separately (the md5 split
from campaign.py). A config is only interesting if it is positive on BOTH, and
a dial is only believed if its marginal effect points the same way on both.
What each round taught goes into ../SMC_RESEARCH.md by hand, so the next round
starts from what is known instead of from scratch.

Memory: the box has ~1 GB free, so the loop is coin-major and single-process.
Each coin's frames are built, every config is run on it, its compact trade
arrays are kept, and its frames are dropped before the next coin loads.
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from dataclasses import replace, asdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402
import smc      # noqa: E402

RES = Path(__file__).resolve().parent / "results"
RES.mkdir(exist_ok=True)

TF_PAIRS = [("15m", "1h"), ("15m", "4h"), ("1h", "4h"), ("1h", "1d"), ("4h", "1d")]
# a pivot of k bars on 15m is a much smaller swing than on 4h; hold time is in
# LTF bars, so give each entry timeframe roughly 2-4 days to work
MAX_HOLD = {"15m": 288, "1h": 96, "4h": 42}


def _drop(coin: str, base: str) -> None:
    for f in (smc.bars, smc.structure, smc.htf_on_ltf, smc.extras):
        f.cache_clear()
    for tf in ("15m", "1h", "4h", "1d", base):
        harness._FRAMES.pop((f"{coin}/USDT", tf), None)


def evaluate(cfgs: list[smc.Cfg], coins: list[str], base: str = "15m",
             label: str = "") -> dict[int, pd.DataFrame]:
    """Every config on every coin; returns compact trade frames per config.

    Trades are held as small numpy columns (coin as an int code), because a
    round can produce millions of them and an object column of coin names
    alone would not fit in the memory this box has free.
    """
    acc: dict[int, list] = {i: [] for i in range(len(cfgs))}
    t0 = time.time()
    for ci, coin in enumerate(coins):
        for i, cfg in enumerate(cfgs):
            tr = smc.run(coin, cfg, base)
            if len(tr):
                acc[i].append((
                    np.full(len(tr), ci, np.int16),
                    tr["entry_time"].to_numpy("datetime64[ns]"),
                    tr["exit_time"].to_numpy("datetime64[ns]"),
                    tr["dir"].to_numpy(np.int8), tr["kind"].to_numpy(np.int8),
                    tr["r"].to_numpy(np.float32),
                    tr["why"].to_numpy(), tr["risk_pct"].to_numpy(np.float32)))
        _drop(coin, base)
        if (ci + 1) % 10 == 0 or ci + 1 == len(coins):
            print(f"  {label} {ci + 1}/{len(coins)} coins, {time.time() - t0:.0f}s",
                  file=sys.stderr, flush=True)
    names = np.array(coins)
    out = {}
    for i, parts in acc.items():
        if not parts:
            out[i] = pd.DataFrame()
            continue
        cols = [np.concatenate(x) for x in zip(*parts)]
        out[i] = pd.DataFrame({
            "coin": pd.Categorical.from_codes(cols[0], categories=names),
            "entry_time": pd.to_datetime(cols[1], utc=True),
            "exit_time": pd.to_datetime(cols[2], utc=True),
            "dir": cols[3], "kind": cols[4], "r": cols[5].astype(float),
            "why": cols[6], "risk_pct": cols[7].astype(float)})
        acc[i] = None
    return out


def score(cfgs, trades, fit, hold) -> pd.DataFrame:
    rows = []
    fit_s, hold_s = set(fit), set(hold)
    for i, cfg in enumerate(cfgs):
        tr = trades[i]
        row = {k: v for k, v in asdict(cfg).items()}
        if len(tr) == 0:
            row.update(f_n=0, h_n=0)
            rows.append(row)
            continue
        F = tr[tr.coin.astype(str).isin(fit_s)]
        Hd = tr[tr.coin.astype(str).isin(hold_s)]
        for pre, part in (("f_", F), ("h_", Hd)):
            m = smc.metrics(part)
            row.update({pre + k: v for k, v in m.items()})
        for pre, part in (("L_", tr[tr.dir > 0]), ("S_", tr[tr.dir < 0])):
            m = smc.metrics(part)
            row[pre + "avg_r"] = m.get("avg_r")
            row[pre + "n"] = m.get("n")
        rows.append(row)
    return pd.DataFrame(rows)


def marginals(df: pd.DataFrame, dials: list[str], min_n: int = 100) -> str:
    """Median FIT and HOLDOUT avg R for every value of every dial."""
    d = df[(df.f_n >= min_n) & (df.h_n >= min_n)]
    out = []
    for dial in dials:
        g = d.groupby(dial).agg(cells=("f_avg_r", "size"),
                                fit=("f_avg_r", "median"),
                                hold=("h_avg_r", "median"),
                                best_hold=("h_avg_r", "max"))
        out.append(f"\n{dial}\n{g.round(3).to_string()}")
    return "\n".join(out)


COLS = ["ltf", "htf", "mode", "entry", "choch_only", "need_swept", "discount",
        "min_risk", "tp_r", "f_n", "f_win", "f_avg_r", "f_pf", "f_ratio",
        "h_n", "h_win", "h_avg_r", "h_pf", "h_ratio", "h_coins_pos",
        "h_yrs_pos", "L_avg_r", "S_avg_r", "f_avg_risk"]


def save(name: str, df: pd.DataFrame) -> None:
    p = RES / f"smc_{name}.jsonl"
    with p.open("w") as f:
        for r in df.to_dict("records"):
            f.write(json.dumps(r, default=str) + "\n")
    print(f"saved {p}", file=sys.stderr)


def load_round(name: str) -> pd.DataFrame:
    return pd.read_json(RES / f"smc_{name}.jsonl", lines=True)


def report(df: pd.DataFrame, dials: list[str], top: int = 25) -> None:
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    ok = df[(df.f_n >= 100) & (df.h_n >= 100)].copy()
    ok["both"] = ok[["f_avg_r", "h_avg_r"]].min(axis=1)
    print(f"\n{len(df)} configs, {len(ok)} with n>=100 on both halves; "
          f"{int(((ok.f_avg_r > 0) & (ok.h_avg_r > 0)).sum())} positive on both")
    print("\nTop by the WORSE of fit/holdout avg R:")
    print(ok.sort_values("both", ascending=False)[[c for c in COLS if c in ok]]
          .head(top).to_string(index=False))
    print(marginals(df, dials))


# ------------------------------------------------------------------ rounds
def round1() -> pd.DataFrame:
    """Which SMC structure has any edge at all, before any tuning."""
    cfgs = []
    for (ltf, htf), entry, mr in itertools.product(
            TF_PAIRS, ["mkt", "ob", "fvg", "ote"], [0.005, 0.01]):
        base = smc.Cfg(ltf=ltf, htf=htf, entry=entry, min_risk=mr,
                       max_risk=0.08 if ltf == "4h" else 0.05,
                       max_hold=MAX_HOLD[ltf], tp_r=3.0)
        for choch, swept, disc in itertools.product([True, False], [False, True],
                                                    [False, True]):
            cfgs.append(replace(base, mode="cont", choch_only=choch,
                                need_swept=swept, discount=disc))
        for choch, swept in itertools.product([True, False], [False, True]):
            cfgs.append(replace(base, mode="rev", choch_only=choch,
                                need_swept=swept))
    return _run_round("round1", cfgs)


def _run_round(name: str, cfgs: list[smc.Cfg], base: str = "15m",
               coins: list[str] | None = None) -> pd.DataFrame:
    """Score a round one timeframe pair at a time, to bound memory."""
    coins = coins or [c for c in smc.UNIVERSE if smc.have(c, base)]
    fit, hold = smc.split(coins)
    print(f"{name}: {len(cfgs)} configs x {len(coins)} coins "
          f"(FIT {len(fit)} / HOLDOUT {len(hold)})", file=sys.stderr)
    parts = []
    for pair in sorted({(c.ltf, c.htf) for c in cfgs}):
        sub = [c for c in cfgs if (c.ltf, c.htf) == pair]
        trades = evaluate(sub, coins, base, f"{name} {pair[0]}/{pair[1]}")
        parts.append(score(sub, trades, fit, hold))
        del trades
    df = pd.concat(parts, ignore_index=True)
    save(name, df)
    return df


# one-dial-at-a-time sweeps: each base config, every alternative value of one
# dial with the rest held fixed. Cheap, and it shows the SHAPE of each dial
# (a plateau is believable, a spike is not) before any joint search.
OAT = {
    "k_ltf": [2, 3, 5, 8],
    "k_htf": [2, 3, 5],
    "sl_buf": [0.0, 0.1, 0.3, 0.6, 1.0],
    "tp_r": [2.0, 2.5, 3.0, 4.0, 5.0],
    "be_r": [0.0, 1.0, 1.5, 2.0],
    "exit_choch": [False, True],
    "expiry": [4, 12, 24, 48],
    "sweep_life": [2, 6, 12, 24],
    "min_risk": [0.003, 0.005, 0.01, 0.015, 0.02],
    "max_risk": [0.02, 0.03, 0.05, 0.08, 0.12],
    "side": [0, 1, -1],
    "part_r": [0.0, 1.0, 1.5, 2.0],
}


def oat(bases: list[smc.Cfg], dials: dict = OAT) -> list[smc.Cfg]:
    seen, out = set(), []
    for b in bases:
        for dial, vals in dials.items():
            for v in vals:
                c = replace(b, **{dial: v})
                if c not in seen:
                    seen.add(c)
                    out.append(c)
    return out


def round2() -> pd.DataFrame:
    """One-dial sweeps around round 1's six best cells (SMC_RESEARCH.md)."""
    B = dict(tp_r=3.0, min_risk=0.01)
    bases = [
        smc.Cfg(ltf="4h", htf="1d", mode="cont", entry="ote", choch_only=True,
                need_swept=True, max_risk=0.08, max_hold=42, **B),
        smc.Cfg(ltf="15m", htf="4h", mode="cont", entry="ote", choch_only=True,
                need_swept=True, discount=True, max_hold=288, **B),
        smc.Cfg(ltf="1h", htf="1d", mode="cont", entry="fvg", choch_only=True,
                discount=True, max_hold=96, **B),
        smc.Cfg(ltf="1h", htf="4h", mode="rev", entry="ob", choch_only=True,
                max_hold=96, **B),
        smc.Cfg(ltf="4h", htf="1d", mode="cont", entry="mkt", choch_only=False,
                need_swept=True, max_risk=0.08, max_hold=42,
                **{**B, "min_risk": 0.005}),
        smc.Cfg(ltf="1h", htf="1d", mode="cont", entry="ob", choch_only=True,
                need_swept=True, discount=True, max_hold=96, **B),
    ]
    return _run_round("round2", oat(bases))


def _grid(base: smc.Cfg, **dials) -> list[smc.Cfg]:
    keys = list(dials)
    return [replace(base, **dict(zip(keys, vals)))
            for vals in itertools.product(*(dials[k] for k in keys))]


def round3() -> pd.DataFrame:
    """Joint grids on the four families that survived round 2, on 1h data.

    1h is the base so every coin's history reaches back to 2020 and the 2021
    bull market is in the sample -- the short-side result needs that test.
    """
    cfgs = []
    f1 = smc.Cfg(ltf="4h", htf="1d", mode="cont", entry="ote", choch_only=True,
                 need_swept=True, min_risk=0.01, max_risk=0.08, max_hold=42)
    cfgs += _grid(f1, k_ltf=[3, 5], k_htf=[3, 5], sl_buf=[0.1, 0.5, 1.0],
                  tp_r=[3.0, 4.0, 5.0], side=[0, -1], exit_choch=[False, True])
    f2 = smc.Cfg(ltf="4h", htf="1d", mode="cont", entry="mkt", choch_only=False,
                 need_swept=True, min_risk=0.005, max_risk=0.08, max_hold=42)
    cfgs += _grid(f2, k_ltf=[3, 5, 8], k_htf=[2, 3], sl_buf=[0.1, 1.0],
                  tp_r=[3.0, 4.0, 5.0], side=[0, -1], max_risk=[0.08, 0.12])
    f3 = smc.Cfg(ltf="1h", htf="1d", mode="cont", entry="fvg", choch_only=True,
                 discount=True, min_risk=0.01, max_hold=96)
    cfgs += _grid(f3, k_htf=[3, 5], min_risk=[0.01, 0.015, 0.02],
                  tp_r=[3.0, 4.0], side=[0, -1], sl_buf=[0.0, 0.1])
    f4 = smc.Cfg(ltf="1h", htf="4h", mode="rev", entry="ob", choch_only=True,
                 min_risk=0.01, max_hold=96)
    cfgs += _grid(f4, k_ltf=[2, 3], sweep_life=[2, 6], tp_r=[3.0, 4.0, 5.0],
                  side=[0, -1], expiry=[12, 48], max_risk=[0.02, 0.05])
    return _run_round("round3", cfgs, base="1h")


LEADERS = {
    # round 3 leaders (SMC_RESEARCH.md), both sides; shorts-only variants
    # are built from these with side=-1
    "A_ote4h": smc.Cfg(ltf="4h", htf="1d", mode="cont", entry="ote",
                       choch_only=True, need_swept=True, k_ltf=3, k_htf=5,
                       sl_buf=0.1, tp_r=4.0, exit_choch=True, min_risk=0.01,
                       max_risk=0.08, max_hold=42),
    "B_mkt4h": smc.Cfg(ltf="4h", htf="1d", mode="cont", entry="mkt",
                       choch_only=False, need_swept=True, k_ltf=5, k_htf=2,
                       sl_buf=0.1, tp_r=4.0, min_risk=0.005, max_risk=0.08,
                       max_hold=42),
    "C_rev1h": smc.Cfg(ltf="1h", htf="4h", mode="rev", entry="ob",
                       choch_only=True, k_ltf=2, k_htf=3, sl_buf=0.1, tp_r=4.0,
                       min_risk=0.01, max_risk=0.02, sweep_life=2, max_hold=96),
    "D_fvg1h": smc.Cfg(ltf="1h", htf="1d", mode="cont", entry="fvg",
                       choch_only=True, discount=True, k_ltf=3, k_htf=3,
                       sl_buf=0.0, tp_r=3.0, min_risk=0.015, max_risk=0.05,
                       max_hold=96),
}


def round4() -> pd.DataFrame:
    """Round 3's feature study turned into filters, on every leader."""
    cfgs = []
    for name, b in LEADERS.items():
        for side in (0, -1):
            cfgs += _grid(replace(b, side=side),
                          hour_from=[0, 8, 12], min_volx=[0.0, 0.9, 1.2],
                          with_d50=[False, True], max_leg_atr=[99.0, 3.5])
        cfgs += [replace(b, hour_to=12)]           # the mirror: early hours only
    return _run_round("round4", cfgs, base="1h")


def round5() -> pd.DataFrame:
    """The exit of the one config that survived the exam (B_mkt4h_raw).

    Picked on the 76 old coins only; the new coins are looked at once, after.
    """
    b = LEADERS["B_mkt4h"]
    cfgs = _grid(b, tp_r=[3.0, 4.0, 6.0, 10.0], max_hold=[21, 42, 84, 168],
                 trail_r=[0.0, 1.5, 2.5], exit_choch=[False, True],
                 sl_buf=[0.1, 0.5])
    return _run_round("round5", cfgs, base="1h")


DIALS1 = ["ltf", "htf", "mode", "entry", "choch_only", "need_swept",
          "discount", "min_risk"]


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "round1"
    if what == "round1":
        report(round1(), DIALS1)
    elif what == "round2":
        report(round2(), DIALS1)
    elif what == "round3":
        report(round3(), DIALS1 + ["k_ltf", "k_htf", "sl_buf", "tp_r", "side",
                                   "exit_choch", "max_risk", "expiry",
                                   "sweep_life"])
    elif what == "round4":
        report(round4(), ["ltf", "mode", "entry", "side", "hour_from",
                          "min_volx", "with_d50", "max_leg_atr"])
    elif what == "round5":
        report(round5(), ["tp_r", "max_hold", "trail_r", "exit_choch", "sl_buf"])
    elif what == "show":
        report(load_round(sys.argv[2]), DIALS1)
