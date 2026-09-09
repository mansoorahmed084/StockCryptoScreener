"""Full-grid optimisation, scored on held-out coins, ranked by ANNUAL R.

    python research/optimize.py 1d 0 4        # timeframe, worker index, worker count

Why annual R and not avgR. At 1% risk per trade, the account's CAGR is roughly
the R earned per year expressed as a percent, because each R is 1% of equity. A
config with +0.35R over 20 trades a year earns ~7R/year and so ~7% CAGR; the
same +0.35R over 60 trades a year earns ~21R/year. Every earlier phase ranked on
avgR, which is the right measure of whether an edge exists and the wrong one for
how much money it makes.

    annual_R = trades_per_year * avg_r

The grid is deliberately large, which is exactly the machine that manufactures
fake edges, so the guard is non-negotiable: every configuration is scored
separately on a FIT basket and a HOLDOUT basket of coins, split by hashing the
coin name. Selection happens on FIT, the verdict is HOLDOUT, and a config only
counts if its neighbours in the grid agree.
"""
from __future__ import annotations

import json
import sys
import time
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness      # noqa: E402
import breakout     # noqa: E402
import strategies   # noqa: E402
import campaign     # noqa: E402

TFS = {"1d": ("1h", pd.Timedelta("1D"), 60),
       "4h": ("1h", pd.Timedelta("4h"), 120)}

GRID = {
    "side": ["long", "short"],
    "wt2_max": [-20.0, -30.0, -40.0, -50.0, -60.0],
    "trigger": ["none", "swing", "slope"],
    "wait_bars": [4, 8, 16],
    "atr_mult": [0.5, 1.0, 2.0],
    "mfi_min": [None, 0.0],
    "gate": ["none", "own_1d", "btc_1d"],
    "target": ["2R", "3R", "4R", "G1_3R"],
    "require_hold": [True, False],
}

PLANS = {
    "2R": ([(2.0, 1.0)], None),
    "3R": ([(3.0, 1.0)], None),
    "4R": ([(4.0, 1.0)], None),
    "G1_3R": ([(1.0, 0.5), (3.0, 0.5)], 0),
}


_GATES: dict = {}


def gate_for(kind: str, base: pd.DataFrame, pair: str, side: str):
    """Cached: the regime classifier is pure and was being recomputed per config."""
    if kind == "none":
        return None, None
    ck = (kind, pair, side)
    if ck in _GATES:
        return _GATES[ck]
    allow = (("bull", "neutral") if side == "long" else ("bear", "neutral"))
    src = pair if kind == "own_1d" else "BTC/USDT"
    try:
        high = harness.load(src, "1d")
    except FileNotFoundError:
        _GATES[ck] = (None, None)
        return None, None
    res = (strategies.higher_tf_regime(base, high, "1d", pd.Timedelta("1D")), allow)
    _GATES[ck] = res
    return res


def score(coins: list[str], tf: str, cfg: dict) -> dict:
    detail, bar, tstop = TFS[tf]
    legs, be = PLANS[cfg["target"]]
    plan = harness.ExitPlan(legs=[tuple(x) for x in legs], be_after_leg=be,
                            time_stop_bars=tstop)
    pooled, per, span = [], [], 0.0
    for c in coins:
        pair = f"{c}/USDT"
        try:
            base, det = harness.load(pair, tf), harness.load(pair, detail)
        except FileNotFoundError:
            continue
        gate, allow = gate_for(cfg["gate"], base, pair, cfg["side"])
        kw = dict(side=cfg["side"], wt2_max=cfg["wt2_max"],
                  trigger=cfg["trigger"], wait_bars=cfg["wait_bars"],
                  atr_mult=cfg["atr_mult"], mfi_min=cfg["mfi_min"],
                  require_hold=cfg["require_hold"], max_risk_pct=0.15)
        if gate is not None:
            kw["gate"], kw["gate_allow"] = gate, allow
        sig = breakout.divergence_breakout(base, **kw)
        if sig.empty:
            continue
        sig = sig[sig.index >= pd.Timestamp("2020-01-01", tz="UTC")]
        if sig.empty:
            continue
        tr = harness.simulate(sig, base, det, plan, base_bar=bar)
        if not tr:
            continue
        pooled += tr
        span = max(span, (base.index[-1] - max(base.index[0],
                   pd.Timestamp("2020-01-01", tz="UTC"))).days / 365.25)
        if len(tr) >= 5:
            per.append(harness.metrics(tr)["avg_r"])
    m = harness.metrics(pooled)
    if m.get("n") and span > 0:
        m["per_year"] = round(m["n"] / span, 1)
        m["annual_r"] = round(m["n"] * m["avg_r"] / span, 2)
    m["coins_pos"] = sum(1 for x in per if x > 0)
    m["coins_tested"] = len(per)
    return m


def cfg_key(cfg: dict) -> str:
    """Stable identity for a grid cell, so a resumed worker can skip what it did."""
    return "|".join(f"{k}={cfg[k]}" for k in GRID)


def read_done(jl: Path, legacy: Path) -> tuple[set, int]:
    """Cells already on disk, from the append log and from any older whole-file run."""
    done, n = set(), 0
    if legacy.exists():
        try:
            for r in json.loads(legacy.read_text(encoding="utf-8")):
                done.add(cfg_key(r["cfg"]))
                n += 1
        except (json.JSONDecodeError, KeyError):
            pass
    if jl.exists():
        with jl.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue        # a torn last line from a killed worker
                if cfg_key(r["cfg"]) not in done:
                    done.add(cfg_key(r["cfg"]))
                    n += 1
    return done, n


def main() -> None:
    tf = sys.argv[1] if len(sys.argv) > 1 else "1d"
    widx = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    wcnt = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    coins = [c for c in campaign.UNIVERSE
             if (harness.DATA_DIR / f"{c}_USDT-{tf}.feather").exists()
             and (harness.DATA_DIR / f"{c}_USDT-1h.feather").exists()]
    fit, hold = campaign.split(coins)

    keys = list(GRID)
    combos = [dict(zip(keys, v)) for v in product(*(GRID[k] for k in keys))]
    mine = combos[widx::wcnt]

    res = Path(__file__).resolve().parent / "results"
    res.mkdir(parents=True, exist_ok=True)
    legacy = res / f"opt_{tf}_{widx}.json"
    jl = res / f"opt_{tf}_{widx}.jsonl"

    # One appended line per scored cell. The first version of this held every
    # result in a list and re-serialised the whole list on each checkpoint; six
    # of those in parallel exhausted a 7 GB box and killed five of six workers
    # mid-grid. Appending costs one row of memory and cannot truncate the file.
    done, have = read_done(jl, legacy)
    todo = [c for c in mine if cfg_key(c) not in done]
    print(f"worker {widx}: {have} on disk, {len(todo)} to go",
          file=sys.stderr, flush=True)

    with jl.open("a", encoding="utf-8") as fh:
        for i, cfg in enumerate(todo):
            try:
                f = score(fit, tf, cfg)
                if not f.get("n") or f["n"] < 30:
                    row = {"cfg": cfg, "thin": f.get("n", 0)}
                else:
                    row = {"cfg": cfg, "fit": f, "hold": score(hold, tf, cfg)}
            except Exception as exc:
                row = {"cfg": cfg, "error": f"{type(exc).__name__}: {exc}"}
            print(json.dumps(row, default=str), file=fh)
            if (i + 1) % 25 == 0:
                fh.flush()
                print(f"worker {widx}: {i + 1}/{len(todo)}",
                      file=sys.stderr, flush=True)

    print(f"worker {widx}: finished, {have + len(todo)} cells of {len(mine)}")


if __name__ == "__main__":
    main()
