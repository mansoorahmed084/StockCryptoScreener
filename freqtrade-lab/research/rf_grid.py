"""Grid over 1h-timed entries and 1h-placed stops for the trendline break.

    python research/rf_grid.py 0 6          # worker index, worker count
    python research/rf_report.py 15

The daily signal is held FIXED at the config validated in
STRATEGY_TrendlineBreakout.md. Only the timing of the entry and the placement
of the stop vary, so any difference is attributable to the refinement and not
to a different set of breakouts.

`entry_mode="next_open"` with `stop_mode="daily"` is the CONTROL: it reproduces
the daily entry price exactly (verified) and the daily stop, run through the
same engine as everything else. If nothing beats it, the refinement is dead and
that is a real answer.

Dedupe: `next_open` ignores wait_hours and `stop_mode="daily"` ignores
atr_mult, so those combinations are collapsed to one representative rather than
scored repeatedly -- otherwise the marginals would be weighted by a dial that
does nothing.

Exits are walked on the 1h frame itself, stop-first inside the bar. That is the
conservative reading when a bar contains both the stop and a target. The
winners are re-run on 15m detail afterwards.
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
import refine       # noqa: E402
import campaign     # noqa: E402
from tl_final import FINAL  # noqa: E402

START = pd.Timestamp("2020-01-01", tz="UTC")
HOUR = pd.Timedelta("1h")
TIME_STOP_H = 365 * 24          # the same 365-day backstop, counted in hours

GRID = {
    "entry_mode": list(refine.ENTRY_MODES),
    "stop_mode": list(refine.STOP_MODES),
    "wait_hours": [24, 72, 168],
    "atr_mult": [0.5, 1.0, 2.0],
    # The exit is a dial, not a constant. An R-based trail scales with the entry
    # stop, so tightening the stop tightens the exit and the refinement buys
    # nothing; a PERCENT trail is scale-free and is the only way to pair a tight
    # entry stop with an exit wide enough to let a 100% move run. Both are here
    # so the grid decides rather than the author.
    "exit": ["3R", "6R", "9R", "15%", "25%", "35%"],
}

EXITS = {"3R": dict(trail_r=3.0), "6R": dict(trail_r=6.0), "9R": dict(trail_r=9.0),
         "15%": dict(trail_pct=0.15), "25%": dict(trail_pct=0.25),
         "35%": dict(trail_pct=0.35)}
FIXED = dict(swing_hours=24, atr_len=14, retest_tol=0.02, ema_len=20,
             min_risk_pct=0.02, max_risk_pct=0.25)


def combos() -> list[dict]:
    keys = list(GRID)
    out, seen = [], set()
    for v in product(*(GRID[k] for k in keys)):
        c = dict(zip(keys, v))
        # collapse the dials that the chosen mode does not read
        if c["entry_mode"] == "next_open":
            c["wait_hours"] = 72
        if c["stop_mode"] == "daily":
            c["atr_mult"] = 1.0
        k = tuple(c[x] for x in keys)
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


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


_DSIG: dict = {}


def daily_signals(coin: str) -> pd.DataFrame:
    """The daily trendline signals, computed once and shared by every config."""
    if coin not in _DSIG:
        d = harness.load(f"{coin}/USDT", "1d")
        s = trendline.trendline_breakout(d, **FINAL)
        _DSIG[coin] = s[s.index >= START] if not s.empty else s
    return _DSIG[coin]


def score(coins: list[str], cfg: dict) -> dict:
    plan = harness.ExitPlan(legs=[(100.0, 1.0)], time_stop_bars=TIME_STOP_H,
                            **EXITS[cfg["exit"]])
    kw = dict(FIXED, entry_mode=cfg["entry_mode"], stop_mode=cfg["stop_mode"],
              wait_hours=cfg["wait_hours"], atr_mult=cfg["atr_mult"])
    pooled, per, span = [], [], 0.0
    for c in coins:
        ds = daily_signals(c)
        if ds.empty:
            continue
        h = harness.load(f"{c}/USDT", "1h")
        sig = refine.refined_signals(ds, h, **kw)
        if sig.empty:
            continue
        tr = harness.simulate(sig, h, h, plan, base_bar=HOUR)
        if not tr:
            continue
        pooled += tr
        d = harness.load(f"{c}/USDT", "1d")
        span = max(span, (d.index[-1] - max(d.index[0], START)).days / 365.25)
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
             if (harness.DATA_DIR / f"{c}_USDT-1d.feather").exists()
             and (harness.DATA_DIR / f"{c}_USDT-1h.feather").exists()]
    fit, hold = campaign.split(coins)
    mine = combos()[widx::wcnt]

    res = Path(__file__).resolve().parent / "results"
    res.mkdir(parents=True, exist_ok=True)
    jl = res / f"rfgrid_{widx}.jsonl"
    done = read_done(jl)
    todo = [c for c in mine if cfg_key(c) not in done]
    print(f"worker {widx}: {len(done)} on disk, {len(todo)} to go",
          file=sys.stderr, flush=True)

    with jl.open("a", encoding="utf-8") as fh:
        for i, cfg in enumerate(todo):
            try:
                f = score(fit, cfg)
                if not f.get("n") or f["n"] < 25:
                    row = {"cfg": cfg, "thin": f.get("n", 0)}
                else:
                    row = {"cfg": cfg, "fit": f, "hold": score(hold, cfg)}
            except Exception as exc:
                row = {"cfg": cfg, "error": f"{type(exc).__name__}: {exc}"}
            print(json.dumps(row, default=str), file=fh)
            fh.flush()
            if (i + 1) % 5 == 0:
                print(f"worker {widx}: {i + 1}/{len(todo)}",
                      file=sys.stderr, flush=True)

    print(f"worker {widx}: finished")


if __name__ == "__main__":
    main()
