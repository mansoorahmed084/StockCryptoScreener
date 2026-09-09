"""Grid over the long-term trendline breakout, scored on held-out coins.

    python research/tl_grid.py 0 4          # worker index, worker count
    python research/tl_report.py 15         # rank + marginals + neighbours

The single-dial sweeps in tl_campaign.py disagreed with themselves: the ratio
dipped at lookback 260 and rose again either side of it, which is the shape of
noise, not of an effect. A dial sweep holds everything else at one arbitrary
point, so it cannot tell those apart. This grid varies them together, which
makes the MARGINALS meaningful -- the average over every other setting -- and
lets a winner be checked against its neighbours.

Same guards as optimize.py: select on FIT, verdict on HOLDOUT, coins split by
hashing the name. Results are appended one line at a time so a killed worker
loses at most one cell.
"""
from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness      # noqa: E402
import trendline    # noqa: E402
import campaign     # noqa: E402

TF, DETAIL, BAR = "1d", "1h", pd.Timedelta("1D")
START = pd.Timestamp("2020-01-01", tz="UTC")

# Dials that shape the ENTRY. Signals are computed once per combination of
# these and reused across every exit, which is most of the grid's speed.
ENTRY = {
    "lookback": [130, 200, 260, 400],
    "min_span": [30, 60, 120, 200],
    "vol_mult": [None, 1.25, 1.5, 2.0],
    "atr_mult": [0.5, 1.0, 1.5],
}
# Dials that shape the EXIT.
EXIT = {"trail_r": [2.5, 3.0, 4.0]}
GRID = {**ENTRY, **EXIT}

FIXED = dict(min_touches=3, touch_tol=0.03, min_drop_pct=0.25,
             stop_lookback=20, max_risk_pct=0.25, cooldown=20)


def cfg_key(cfg: dict) -> str:
    return "|".join(f"{k}={cfg[k]}" for k in GRID)


def read_done(jl: Path) -> set:
    done = set()
    if jl.exists():
        with jl.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(cfg_key(json.loads(line)["cfg"]))
                except (json.JSONDecodeError, KeyError):
                    continue        # a torn last line from a killed worker
    return done


def signals_for(coins: list[str], ent: dict) -> dict:
    """{coin: signal frame} for one entry configuration."""
    out = {}
    for c in coins:
        base = harness.load(f"{c}/USDT", TF)
        if len(base) < ent["lookback"] + 5:
            continue
        sig = trendline.trendline_breakout(base, **ent, **FIXED)
        if sig.empty:
            continue
        sig = sig[sig.index >= START]
        if not sig.empty:
            out[c] = sig
    return out


def score(sigs: dict, trail_r: float) -> dict:
    plan = harness.ExitPlan(legs=[(100.0, 1.0)], trail_r=trail_r,
                            time_stop_bars=365)
    pooled, per, span = [], [], 0.0
    for c, sig in sigs.items():
        base, det = harness.load(f"{c}/USDT", TF), harness.load(f"{c}/USDT", DETAIL)
        tr = harness.simulate(sig, base, det, plan, base_bar=BAR)
        if not tr:
            continue
        pooled += tr
        span = max(span, (base.index[-1] - max(base.index[0], START)).days / 365.25)
        if len(tr) >= 4:
            per.append(harness.metrics(tr)["avg_r"])
    m = harness.metrics(pooled)
    if m.get("n") and span > 0:
        m["annual_r"] = round(m["n"] * m["avg_r"] / span, 2)
        dd = m["max_dd_r"]
        m["ratio"] = round(m["annual_r"] / dd, 2) if dd > 0 else None
    m["coins_pos"] = sum(1 for x in per if x > 0)
    m["coins_tested"] = len(per)
    return m


def main() -> None:
    widx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    wcnt = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    coins = [c for c in campaign.UNIVERSE
             if (harness.DATA_DIR / f"{c}_USDT-{TF}.feather").exists()
             and (harness.DATA_DIR / f"{c}_USDT-{DETAIL}.feather").exists()]
    fit, hold = campaign.split(coins)

    ekeys = list(ENTRY)
    ents = [dict(zip(ekeys, v)) for v in product(*(ENTRY[k] for k in ekeys))]
    # a line must have room to fall: the span cannot fill the whole lookback
    ents = [e for e in ents if e["min_span"] <= e["lookback"] - 40]
    mine = ents[widx::wcnt]

    res = Path(__file__).resolve().parent / "results"
    res.mkdir(parents=True, exist_ok=True)
    jl = res / f"tlgrid_{widx}.jsonl"
    done = read_done(jl)
    print(f"worker {widx}: {len(done)} cells on disk, {len(mine)} entry configs",
          file=sys.stderr, flush=True)

    with jl.open("a", encoding="utf-8") as fh:
        for i, ent in enumerate(mine):
            todo = [t for t in EXIT["trail_r"]
                    if cfg_key({**ent, "trail_r": t}) not in done]
            if not todo:
                continue
            sf, sh = signals_for(fit, ent), signals_for(hold, ent)
            for t in todo:
                cfg = {**ent, "trail_r": t}
                try:
                    f = score(sf, t)
                    if not f.get("n") or f["n"] < 40:
                        row = {"cfg": cfg, "thin": f.get("n", 0)}
                    else:
                        row = {"cfg": cfg, "fit": f, "hold": score(sh, t)}
                except Exception as exc:
                    row = {"cfg": cfg, "error": f"{type(exc).__name__}: {exc}"}
                print(json.dumps(row, default=str), file=fh)
            fh.flush()
            print(f"worker {widx}: {i + 1}/{len(mine)}", file=sys.stderr, flush=True)

    print(f"worker {widx}: finished")


if __name__ == "__main__":
    main()
