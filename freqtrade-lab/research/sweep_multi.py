"""Multi-coin sweep driver with a HELD-OUT COIN set.

    python research/sweep_multi.py research/specs/p1_0.json research/results/p1_0.json

Phase 3 proved that a search fitted to one coin produces strategies that lose
money on every other coin, and that no amount of date-split out-of-sample
catches it. So this driver never reports a single number: every experiment is
scored on a FIT basket and on a HOLDOUT basket the search never sees.

A config is only interesting if it works on both. That is the whole point.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness        # noqa: E402
import strategies     # noqa: E402
import hf_strategies  # noqa: E402
import user_setup     # noqa: E402
import confluence     # noqa: E402
import pattern        # noqa: E402

FIT = ["BTC/USDT", "ETH/USDT", "ADA/USDT", "DOGE/USDT",
       "LINK/USDT", "DOT/USDT", "ATOM/USDT", "XLM/USDT"]
HOLDOUT = ["BNB/USDT", "XRP/USDT", "SOL/USDT", "AVAX/USDT",
           "LTC/USDT", "ETC/USDT", "NEAR/USDT", "UNI/USDT"]

DETAIL_FOR = {"15m": "5m", "1h": "5m", "4h": "1h", "1d": "1h"}
BAR = {"15m": pd.Timedelta("15min"), "1h": pd.Timedelta("1h"),
       "4h": pd.Timedelta("4h"), "1d": pd.Timedelta("1D")}

FAMILIES = {
    "vmc_divergence": strategies.vmc_divergence,
    "wt_cross": strategies.wt_cross,
    "bb_reversion": strategies.bb_reversion,
    "ema_pullback": hf_strategies.ema_pullback,
    "rsi_reversion": hf_strategies.rsi_reversion,
    "donchian_break": hf_strategies.donchian_break,
    "vol_spike_reversal": hf_strategies.vol_spike_reversal,
    "keltner_squeeze": hf_strategies.keltner_squeeze,
    "wt_oversold_cross": hf_strategies.wt_oversold_cross,
    "stoch_rsi_reset": user_setup.stoch_rsi_reset,
    "pullback_reset": confluence.pullback_reset,
    "impulse_double_bottom": pattern.impulse_double_bottom,
}

_cache: dict = {}


def _df(pair: str, tf: str) -> pd.DataFrame | None:
    key = (pair, tf)
    if key not in _cache:
        try:
            _cache[key] = harness.load(pair, tf)
        except FileNotFoundError:
            _cache[key] = None
    return _cache[key]


def _gate_for(spec: dict, base: pd.DataFrame, pair: str):
    g = spec.get("gate") or {"kind": "none"}
    kind = g.get("kind", "none")
    if kind == "none":
        return None, None
    allow = tuple(g.get("allow", ["bull", "neutral"]))
    src = {"own_1d": (pair, "1d", pd.Timedelta("1D")),
           "btc_1d": ("BTC/USDT", "1d", pd.Timedelta("1D")),
           "own_4h": (pair, "4h", pd.Timedelta("4h"))}[kind]
    high = _df(src[0], src[1])
    if high is None:
        return None, None
    return strategies.higher_tf_regime(base, high, src[1], src[2]), allow


def _run_pairs(spec: dict, pairs: list[str]) -> list:
    tf = spec["tf"]
    plan_cfg = spec.get("exit", {})
    plan = harness.ExitPlan(
        legs=[tuple(x) for x in plan_cfg.get("legs", [[3.0, 1.0]])],
        be_after_leg=plan_cfg.get("be_after_leg"),
        time_stop_bars=plan_cfg.get("time_stop_bars", 120),
        target_mode=plan_cfg.get("target_mode", "R"))

    trades = []
    for pair in pairs:
        base, detail = _df(pair, tf), _df(pair, DETAIL_FOR[tf])
        if base is None or detail is None or len(base) < 500:
            continue
        params = dict(spec.get("params", {}))
        params["side"] = spec.get("side", "long")
        gate, allow = _gate_for(spec, base, pair)
        if gate is not None:
            params["gate"], params["gate_allow"] = gate, allow
        signals = FAMILIES[spec["family"]](base, **params)
        if signals.empty:
            continue
        trades += harness.simulate(signals, base, detail, plan, base_bar=BAR[tf])
    return trades


def run_one(spec: dict) -> dict:
    fit = _run_pairs(spec, spec.get("fit_pairs", FIT))
    hold = _run_pairs(spec, spec.get("holdout_pairs", HOLDOUT))

    def scored(trades, pairs):
        m = harness.metrics(trades)
        if m.get("n"):
            base = _df(pairs[0], spec["tf"])
            years = (base.index[-1] - base.index[0]).days / 365.25
            # per-year across the whole basket, which is what you would trade
            m["trades_per_year"] = round(m["n"] / years, 1)
        return m

    return {"label": spec["label"], "tf": spec["tf"],
            "side": spec.get("side", "long"),
            "fit": scored(fit, spec.get("fit_pairs", FIT)),
            "holdout": scored(hold, spec.get("holdout_pairs", HOLDOUT))}


def table(results: list[dict]) -> str:
    head = ("| config | FIT n | /yr | win% | avgR | PF | maxDD_R | streak "
            "|| HOLD n | win% | avgR | PF | maxDD_R |")
    lines = [head, "|" + "---|" * 13]
    for r in results:
        f, h = r["fit"], r["holdout"]
        if not f.get("n"):
            lines.append(f"| {r['label']} | 0 |" + " — |" * 12)
            continue
        lines.append(
            f"| {r['label']} | {f['n']} | {f.get('trades_per_year','—')} | "
            f"**{f['win_net_pct']}** | {f['avg_r']} | {f['pf']} | "
            f"{f['max_dd_r']} | {f['worst_streak']} || "
            f"{h.get('n',0)} | **{h.get('win_net_pct','—')}** | "
            f"{h.get('avg_r','—')} | {h.get('pf','—')} | {h.get('max_dd_r','—')} |")
    return "\n".join(lines)


def main() -> None:
    spec_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    specs = json.loads(spec_path.read_text(encoding="utf-8"))
    results = []
    for s in specs:
        try:
            results.append(run_one(s))
        except Exception as exc:
            results.append({"label": s.get("label", "?"), "tf": s.get("tf", "?"),
                            "side": s.get("side", "?"), "fit": {"n": 0},
                            "holdout": {"n": 0},
                            "error": f"{type(exc).__name__}: {exc}"})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(table(results))
    for r in results:
        if "error" in r:
            print(f"\nERROR {r['label']}: {r['error']}", file=sys.stderr)


if __name__ == "__main__":
    main()
