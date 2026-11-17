"""A small CMA-ES (covariance matrix adaptation evolution strategy), batch-evaluated.

Written out in numpy so the project needs no new dependency. It searches the unit box and the
caller decodes points into real parameters, so a single step size suits parameters of very
different scale. Follows Hansen's "The CMA Evolution Strategy: A Tutorial".
"""
from __future__ import annotations

from typing import Callable

import numpy as np


def _minimize(batch_f: Callable[[np.ndarray], np.ndarray], x0: np.ndarray, sigma0: float = 0.25,
             popsize: int | None = None, max_gen: int = 200, seed: int = 0,
             stall_gen: int = 30, tol: float = 1e-9, log: Callable[[str], None] | None = None):
    """Minimise ``batch_f`` (rows of points in [0, 1]^n -> one loss per row).

    Returns (best_x, best_f, generations_run).
    """
    rng = np.random.default_rng(seed)
    n = len(x0)
    lam = popsize or (4 + int(3 * np.log(n))) * 2
    mu = lam // 2
    w = np.log(mu + 0.5) - np.log(np.arange(1, mu + 1))
    w /= w.sum()
    mueff = 1.0 / np.sum(w ** 2)
    cc = (4 + mueff / n) / (n + 4 + 2 * mueff / n)
    cs = (mueff + 2) / (n + mueff + 5)
    c1 = 2 / ((n + 1.3) ** 2 + mueff)
    cmu = min(1 - c1, 2 * (mueff - 2 + 1 / mueff) / ((n + 2) ** 2 + mueff))
    damps = 1 + 2 * max(0.0, np.sqrt((mueff - 1) / (n + 1)) - 1) + cs
    chi_n = np.sqrt(n) * (1 - 1 / (4 * n) + 1 / (21 * n * n))

    mean = np.clip(np.asarray(x0, dtype=float), 0, 1)
    sigma = sigma0
    pc = np.zeros(n)
    ps = np.zeros(n)
    B = np.eye(n)
    D = np.ones(n)
    C = np.eye(n)
    inv_sqrt_C = np.eye(n)

    best_x, best_f = mean.copy(), np.inf
    last_improve = 0

    def fitness(X):
        Xc = np.clip(X, 0, 1)
        return batch_f(Xc) + 1e-2 * np.sum((X - Xc) ** 2, axis=1)

    gen = 0
    for gen in range(1, max_gen + 1):
        Z = rng.standard_normal((lam, n))
        Y = (Z * D) @ B.T
        X = mean + sigma * Y
        f = fitness(X)
        order = np.argsort(f)
        if f[order[0]] < best_f - tol:
            best_f = float(f[order[0]])
            best_x = np.clip(X[order[0]], 0, 1)
            last_improve = gen
        sel = order[:mu]
        old_mean = mean
        mean = w @ X[sel]
        yw = (mean - old_mean) / sigma
        ps = (1 - cs) * ps + np.sqrt(cs * (2 - cs) * mueff) * (inv_sqrt_C @ yw)
        hsig = (np.linalg.norm(ps) / np.sqrt(1 - (1 - cs) ** (2 * gen)) / chi_n
                < 1.4 + 2 / (n + 1))
        pc = (1 - cc) * pc + hsig * np.sqrt(cc * (2 - cc) * mueff) * yw
        Ysel = (X[sel] - old_mean) / sigma
        C = ((1 - c1 - cmu) * C
             + c1 * (np.outer(pc, pc) + (1 - hsig) * cc * (2 - cc) * C)
             + cmu * (Ysel.T * w) @ Ysel)
        sigma *= np.exp((cs / damps) * (np.linalg.norm(ps) / chi_n - 1))
        sigma = min(sigma, 1.0)
        C = (C + C.T) / 2
        vals, B = np.linalg.eigh(C)
        if not np.all(np.isfinite(vals)) or vals.max() <= 0:
            break                                    # collapsed on a flat loss; keep the best
        D = np.sqrt(np.maximum(vals, 1e-12 * vals.max()))   # bound the conditioning
        inv_sqrt_C = (B / D) @ B.T
        if log and (gen == 1 or gen % 10 == 0):
            log(f"    gen {gen:3d}  best {best_f:.5f}  sigma {sigma:.4f}")
        if best_f < 1e-7 or gen - last_improve >= stall_gen or sigma < 1e-6:
            break
    return best_x, best_f, gen


def minimize(*args, **kwargs):
    """See ``_minimize``.

    numpy on Apple's Accelerate BLAS raises "divide by zero / overflow in matmul" for matrices
    that are entirely finite (verified), so floating-point warnings are muted inside the search.
    Real breakdowns are caught by the finiteness check on the covariance eigenvalues.
    """
    with np.errstate(all="ignore"):
        return _minimize(*args, **kwargs)
