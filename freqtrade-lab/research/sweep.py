"""Batch driver: read a JSON spec of experiments, run them, emit results.

    python research/sweep.py research/specs/batch1.json research/results/batch1.json

Each experiment in the spec:

    {
      "label":  "4h fade | wt2>=53 | 1:3",
      "family": "vmc_divergence" | "wt_cross" | "bb_reversion",
      "tf":     "1h" | "4h",
      "side":   "long" | "short",
      "params": {...},                       # passed to the family function
      "gate":   {"kind": "none|eth_1d|btc_1d|eth_4h", "allow": ["bull","neutral"]},
      "vol_min": 0.5,                        # optional ATR-percentile floor
      "exit":   {"legs": [[3.0, 1.0]], "be_after_leg": null, "time_stop_bars": 120}
    }
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

DETAIL_FOR = {"4h": "1h", "1h": "5m", "15m": "5m", "1d": "1h"}
BAR = {"15m": pd.Timedelta("15min"), "1h": pd.Timedelta("1h"),
       "4h": pd.Timedelta("4h"), "1d": pd.Timedelta("1D")}
OOS_START = "2026-01-27"
PAIR = "ETH/USDT"

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
}

_cache: dict = {}


def _df(pair: str, tf: str) -> pd.DataFrame:
    key = (pair, tf)
    if key not in _cache:
        _cache[key] = harness.load(pair, tf)
    return _cache[key]


def _gate(spec: dict, base: pd.DataFrame, tf: str):
    g = spec.get("gate") or {"kind": "none"}
    kind = g.get("kind", "none")
    if kind == "none":
        return None, None
    allow = tuple(g.get("allow", ["bull", "neutral"]))
    if kind == "eth_1d":
        series = strategies.higher_tf_regime(base, _df(PAIR, "1d"), "1d",
                                             pd.Timedelta("1D"))
    elif kind == "btc_1d":
        series = strategies.higher_tf_regime(base, _df("BTC/USDT", "1d"), "1d",
                                             pd.Timedelta("1D"))
    elif kind == "eth_1h":
        series = strategies.higher_tf_regime(base, _df(PAIR, "1h"), "1h",
                                             pd.Timedelta("1h"))
    elif kind == "eth_4h":
        series = strategies.higher_tf_regime(base, _df(PAIR, "4h"), "4h",
                                             pd.Timedelta("4h"))
    elif kind == "self":
        series = strategies.regime(base, tf)
    else:
        raise ValueError(f"unknown gate kind {kind!r}")
    return series, allow


def run_one(spec: dict) -> dict:
    tf = spec["tf"]
    base = _df(PAIR, tf)
    detail = _df(PAIR, DETAIL_FOR[tf])

    gate, allow = _gate(spec, base, tf)
    params = dict(spec.get("params", {}))
    params["side"] = spec.get("side", "long")
    if gate is not None:
        params["gate"] = gate
        params["gate_allow"] = allow

    if spec.get("vol_min") is not None:
        params["vol_min"] = spec["vol_min"]
        params["vol_series"] = strategies.atr_percentile(base)

    signals = FAMILIES[spec["family"]](base, **params)

    e = spec.get("exit", {})
    plan = harness.ExitPlan(
        legs=[tuple(x) for x in e.get("legs", [[3.0, 1.0]])],
        be_after_leg=e.get("be_after_leg"),
        time_stop_bars=e.get("time_stop_bars", 120),
        target_mode=e.get("target_mode", "R"),
    )
    trades = harness.simulate(signals, base, detail, plan, base_bar=BAR[tf])

    m = harness.metrics(trades)
    if m.get("n"):
        span_years = (base.index[-1] - base.index[0]).days / 365.25
        m["trades_per_year"] = round(m["n"] / span_years, 1)
    split = harness.split_metrics(trades, OOS_START)
    return {"label": spec["label"], "tf": tf, "side": spec.get("side", "long"),
            "exit": plan.label, "all": m, "is": split["is"], "oos": split["oos"]}


def table(results: list[dict]) -> str:
    head = ("| strategy | tf | exit | n | /yr | win_net% | win_3R% | avgR | PF "
            "| maxDD_R | R/DD | streak | OOS n | OOS win% |")
    sep = "|" + "---|" * 14
    lines = [head, sep]
    for r in results:
        a, i, o = r["all"], r["is"], r["oos"]
        if not a.get("n"):
            lines.append(f"| {r['label']} | {r['tf']} | {r['exit']} | 0 |" + " — |" * 10)
            continue
        lines.append(
            f"| {r['label']} | {r['tf']} | {r['exit']} | {a['n']} | "
            f"{a.get('trades_per_year','—')} | **{a['win_net_pct']}** | "
            f"{a['win_target_pct']} | {a['avg_r']} | {a['pf']} | {a['max_dd_r']} | "
            f"{a.get('r_per_dd','—')} | {a.get('worst_streak','—')} | "
            f"{o.get('n',0)} | {o.get('win_net_pct','—')} |")
    return "\n".join(lines)


def main() -> None:
    spec_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    specs = json.loads(spec_path.read_text(encoding="utf-8"))
    results = []
    for s in specs:
        try:
            results.append(run_one(s))
        except Exception as exc:                      # keep the batch going
            results.append({"label": s.get("label", "?"), "tf": s.get("tf", "?"),
                            "side": s.get("side", "?"), "exit": "ERROR",
                            "all": {"n": 0}, "is": {}, "oos": {},
                            "error": f"{type(exc).__name__}: {exc}"})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(table(results))
    for r in results:
        if "error" in r:
            print(f"\nERROR in {r['label']}: {r['error']}", file=sys.stderr)


if __name__ == "__main__":
    main()
