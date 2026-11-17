"""Fit the sentiment indicator's parameters so it tracks a reference series.

    .venv/bin/python -m calibration.fit export.csv --ref-col "Sentiment" [--warm 500] [--restarts 4]

The CSV is a TradingView "Export chart data" file holding the candles and the reference
indicator's plot. ``--ref-col`` names that plot's column (``--list`` prints the columns).
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np

from . import cmaes
from .data import Candles, load_tv_csv
from .kernel import (DEFAULTS, IS_INT, LOWER, PARAM_NAMES, UPPER, as_dict, batch_loss,
                     loss_value, sentiment_kernel, snap)

DELTA, W_CORR, W_DIFF = 2.0, 10.0, 1.0      # Huber knee (index points), correlation, change terms


class Problem:
    """Candles + reference + the loss, with batch evaluation."""

    def __init__(self, candles: Candles, ref: np.ndarray, warm: int = 500):
        self.k = candles
        self.ref = np.ascontiguousarray(ref, dtype=np.float64)
        self.warm = int(warm)

    def score(self, theta: np.ndarray) -> np.ndarray:
        return sentiment_kernel(*self.k.args(), snap(theta))

    def loss(self, theta: np.ndarray) -> float:
        return float(loss_value(self.score(theta), self.ref, self.warm, DELTA, W_CORR, W_DIFF))

    def batch(self, thetas: np.ndarray) -> np.ndarray:
        P = np.ascontiguousarray(np.array([snap(t) for t in thetas]))
        return batch_loss(P, *self.k.args(), self.ref, self.warm, DELTA, W_CORR, W_DIFF)

    def metrics(self, theta: np.ndarray) -> dict:
        s = self.score(theta)
        m = ~np.isnan(s) & ~np.isnan(self.ref)
        m[: self.warm] = False
        if m.sum() < 3:
            return {"bars": int(m.sum())}
        e = s[m] - self.ref[m]
        rating = lambda x: np.digitize(x, [25.0, 40.0, 60.0, 75.0])  # five rating bands
        return {
            "bars": int(m.sum()),
            "mae": float(np.abs(e).mean()),
            "rmse": float(np.sqrt((e ** 2).mean())),
            "max_abs": float(np.abs(e).max()),
            "corr": float(np.corrcoef(s[m], self.ref[m])[0, 1]),
            "within_1pt": float((np.abs(e) <= 1.0).mean()),
            "rating_agreement": float((rating(s[m]) == rating(self.ref[m])).mean()),
        }


def decode(x: np.ndarray) -> np.ndarray:
    return snap(LOWER + np.clip(x, 0, 1) * (UPPER - LOWER))


def encode(theta: np.ndarray) -> np.ndarray:
    return (np.clip(theta, LOWER, UPPER) - LOWER) / (UPPER - LOWER)


def polish(problem: Problem, theta: np.ndarray, log=None) -> tuple[np.ndarray, float]:
    """Hill-climb on the exact loss: integers by +-1/+-2/+-4, decimals by shrinking steps.

    CMA-ES rounds integers, which leaves flat patches; this finishes the job on the true score.
    """
    theta = snap(theta)
    best = problem.loss(theta)
    steps = np.where(IS_INT, 1.0, 0.1 * (UPPER - LOWER) / 4)
    for _ in range(60):
        cands, tags = [], []
        for j in range(len(theta)):
            deltas = (-4, -2, -1, 1, 2, 4) if IS_INT[j] else (-1, -0.5, 0.5, 1)
            for d in deltas:
                t = theta.copy()
                t[j] += d * steps[j]
                cands.append(t)
                tags.append(j)
        losses = problem.batch(np.array(cands))
        i = int(np.argmin(losses))
        if losses[i] < best - 1e-9:
            theta, best = snap(cands[i]), float(losses[i])
            if log:
                log(f"    polish: {PARAM_NAMES[tags[i]]} -> {theta[tags[i]]:g}  loss {best:.5f}")
        else:
            decimals = ~IS_INT
            if steps[decimals].max() < 1e-3:
                break
            steps[decimals] *= 0.5
    return theta, best


def scan_coordinates(problem: Problem, theta: np.ndarray, cycles: int = 12, log=None
                     ) -> tuple[np.ndarray, float]:
    """Exhaustive one-parameter-at-a-time search.

    The score is an average of components that each read their own few parameters, so the loss
    is close to additive and a full scan of one parameter is reliable even when the landscape
    is jagged. Integers: every value in range, in one batch. Decimals: a grid, then two zooms.
    """
    theta = snap(theta)
    best = problem.loss(theta)
    for cycle in range(cycles):
        improved = False
        for j in range(len(theta)):
            if IS_INT[j]:
                values = np.arange(LOWER[j], UPPER[j] + 1)
            else:
                values = np.linspace(LOWER[j], UPPER[j], 48)
            for zoom in range(1 if IS_INT[j] else 3):
                cands = np.tile(theta, (len(values), 1))
                cands[:, j] = values
                losses = problem.batch(cands)
                i = int(np.argmin(losses))
                if losses[i] < best - 1e-9:
                    theta, best, improved = snap(cands[i]), float(losses[i]), True
                    if log:
                        log(f"    cycle {cycle + 1}: {PARAM_NAMES[j]} -> {theta[j]:g}  loss {best:.5f}")
                if not IS_INT[j]:       # zoom in around the current value
                    step = values[1] - values[0]
                    values = np.linspace(max(LOWER[j], theta[j] - step), min(UPPER[j], theta[j] + step), 24)
        if not improved:
            break
    return theta, best


def fit(problem: Problem, restarts: int = 4, max_gen: int = 150, seed: int = 0,
        log=print) -> tuple[np.ndarray, float]:
    """Scan from the defaults and from random starts, let CMA-ES make joint moves, scan again.

    The best result over all starts wins.
    """
    rng = np.random.default_rng(seed)
    f = lambda X: problem.batch(np.array([decode(x) for x in X]))
    results = []
    for r in range(restarts):
        start = DEFAULTS if r == 0 else snap(LOWER + rng.uniform(0, 1, len(LOWER)) * (UPPER - LOWER))
        t0 = time.time()
        log(f"  start {r + 1}/{restarts}" + (" (defaults)" if r == 0 else " (random)"))
        theta, loss = scan_coordinates(problem, start)
        log(f"    scan      -> loss {loss:.5f}  ({time.time() - t0:.1f}s)")
        x, fx, gens = cmaes.minimize(f, encode(theta), sigma0=0.08, max_gen=max_gen,
                                     seed=seed + r)
        if fx < loss:
            theta = decode(x)
        theta, loss = scan_coordinates(problem, theta)
        log(f"    + CMA-ES  -> loss {loss:.5f}  ({time.time() - t0:.1f}s)")
        results.append((loss, theta))
    results.sort(key=lambda r: r[0])
    return results[0][1], results[0][0]


def report(problem: Problem, theta: np.ndarray, title: str, log=print) -> dict:
    m = problem.metrics(theta)
    log(f"{title}: loss {problem.loss(theta):.4f}  " + "  ".join(
        f"{k} {v:.4f}" if isinstance(v, float) else f"{k} {v}" for k, v in m.items()))
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("csv", help="TradingView export holding the candles and the reference plot")
    ap.add_argument("--ref-col", help="the reference plot's column name")
    ap.add_argument("--list", action="store_true", help="list the CSV's columns and stop")
    ap.add_argument("--warm", type=int, default=500, help="bars to ignore at the start (default 500)")
    ap.add_argument("--restarts", type=int, default=4)
    ap.add_argument("--max-gen", type=int, default=150)
    ap.add_argument("--holdout", type=float, default=0.3,
                    help="share of the latest bars kept for checking (default 0.3)")
    ap.add_argument("--out", default="calibration/fitted.json", help="where to write the result")
    args = ap.parse_args(argv)

    candles, extras = load_tv_csv(args.csv)
    if args.list or not args.ref_col:
        print(f"{candles.n} bars, {candles.index[0]} .. {candles.index[-1]}, "
              f"session VWAP {'on' if candles.use_vwap else 'off'}")
        print("reference candidates:", list(extras.columns))
        return 0
    if args.ref_col not in extras.columns:
        print(f"no column '{args.ref_col}'; have {list(extras.columns)}", file=sys.stderr)
        return 2
    ref = extras[args.ref_col].to_numpy(dtype=np.float64)

    cut = int(candles.n * (1 - args.holdout))
    train = Problem(candles, ref.copy(), args.warm)
    train.ref[cut:] = np.nan            # the fit never sees the held-out tail
    test_ref = np.full(candles.n, np.nan)
    test_ref[cut:] = ref[cut:]
    test = Problem(candles, test_ref, cut)  # scored on the tail only; the indicator warms on the head

    print(f"{candles.n} bars; fitting on the first {cut}, checking on the last {candles.n - cut}")
    report(train, DEFAULTS, "defaults on fit window ")
    report(test, DEFAULTS, "defaults on held-out    ")
    theta, _ = fit(train, restarts=args.restarts, max_gen=args.max_gen)
    report(train, theta, "fitted on fit window   ")
    report(test, theta, "fitted on held-out      ")
    print(json.dumps(as_dict(theta), indent=2))
    with open(args.out, "w") as fh:
        json.dump({"params": as_dict(theta), "csv": args.csv, "ref_col": args.ref_col,
                   "train_metrics": train.metrics(theta), "holdout_metrics": test.metrics(theta)},
                  fh, indent=2)
    print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
