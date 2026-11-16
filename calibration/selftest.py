"""Can the fitter find a hidden parameter set? Run before trusting it on a real reference.

    .venv/bin/python -m calibration.selftest [--noise 0.0] [--seed 1]

A "reference" is made by running the indicator with hidden parameters on synthetic candles
(optionally with noise added, as screenshots or rounding would). The fit then starts from the
defaults and tries to get back to it; the held-out stretch shows whether it generalises.
"""
from __future__ import annotations

import argparse

import numpy as np

from .data import synthetic_candles
from .fit import Problem, fit, report
from .kernel import DEFAULTS, LOWER, PARAM_NAMES, UPPER, as_dict, sentiment_kernel, snap


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--noise", type=float, default=0.0, help="std-dev of noise on the reference (points)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--bars", type=int, default=6000)
    ap.add_argument("--restarts", type=int, default=3)
    ap.add_argument("--max-gen", type=int, default=120)
    ap.add_argument("--n-changed", type=int, default=6, help="how many parameters differ from default")
    args = ap.parse_args(argv)

    rng = np.random.default_rng(args.seed)
    candles = synthetic_candles(args.bars, seed=args.seed)
    hidden = DEFAULTS.copy()
    for j in rng.choice(len(hidden), size=args.n_changed, replace=False):
        hidden[j] = LOWER[j] + rng.uniform(0.1, 0.6) * (UPPER[j] - LOWER[j])
    hidden = snap(hidden)

    ref = sentiment_kernel(*candles.args(), hidden)
    if args.noise:
        ref = ref + rng.normal(0, args.noise, len(ref))
    cut = int(candles.n * 0.7)
    train = Problem(candles, ref.copy(), 500)
    train.ref[cut:] = np.nan
    test_ref = np.full(candles.n, np.nan)
    test_ref[cut:] = ref[cut:]
    test = Problem(candles, test_ref, cut)

    print(f"hidden parameters that differ from the defaults:")
    for j, name in enumerate(PARAM_NAMES):
        if hidden[j] != DEFAULTS[j]:
            print(f"  {name:14s} default {DEFAULTS[j]:g}  hidden {hidden[j]:g}")
    report(test, DEFAULTS, "defaults on held-out")
    theta, _ = fit(train, restarts=args.restarts, max_gen=args.max_gen, seed=args.seed)
    report(train, theta, "fit on fit window   ")
    report(test, theta, "fit on held-out      ")
    found = as_dict(theta)
    print("\nparameter      hidden   found")
    for j, name in enumerate(PARAM_NAMES):
        mark = "" if abs(found[name] - hidden[j]) < 1e-6 else "   <- differs"
        print(f"  {name:14s} {hidden[j]:7g} {found[name]:7g}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
