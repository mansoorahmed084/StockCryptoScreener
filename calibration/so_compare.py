"""Score our Signals & Overlays build against LuxAlgo's, as read off Vela captures (see so_vision)."""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RESEARCH = Path(__file__).resolve().parents[1] / "freqtrade-lab" / "research"
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))

import signals_overlays as so  # noqa: E402


def frame(candles: pd.DataFrame) -> pd.DataFrame:
    df = candles.copy()
    df.index = pd.to_datetime(df["time"], unit="s", utc=True)
    return df


def score_signals(ref, sig: np.ndarray, tol: int = 1) -> dict:
    """Recall and precision of our signals against the reference's, on the bars the captures show.

    ``sig``: +-1 normal, +-2 strong per bar. A match is the same side within ``tol`` bars.
    """
    ours = [(i, 1 if s > 0 else -1, abs(int(s)) == 2) for i, s in enumerate(sig) if s != 0 and ref.covered[i]]
    used, hit, strong_ok = set(), 0, 0
    for i, (side, kind) in sorted(ref.signals.items()):
        best = None
        for j, (k, s2, _) in enumerate(ours):
            if j not in used and s2 == side and abs(k - i) <= tol and (best is None or abs(k - i) < abs(ours[best][0] - i)):
                best = j
        if best is None:
            continue
        used.add(best)
        hit += 1
        strong_ok += ours[best][2] == (kind == "strong")
    n_ref = len(ref.signals)
    return {"ref": n_ref, "ours": len(ours), "matched": hit, "recall": hit / max(n_ref, 1),
            "precision": hit / max(len(ours), 1), "strong": strong_ok / max(hit, 1)}


def score_trail(ref, trail: np.ndarray, direction: np.ndarray, atr: np.ndarray, which: str = "trail") -> dict:
    """How closely a price series follows the band line the reference draws, in ATRs."""
    r = ref.trail if which == "trail" else ref.inner
    m = (ref.direction != 0) & ~np.isnan(r) & ~np.isnan(trail) & ~np.isnan(atr) & ref.covered
    if m.sum() < 10:
        return {"bars": int(m.sum()), "mae_atr": float("nan"), "dir": float("nan")}
    err = np.abs(trail[m] - r[m]) / atr[m]
    dm = (ref.direction != 0) & ref.covered
    return {"bars": int(m.sum()), "mae_atr": float(err.mean()), "median_atr": float(np.median(err)),
            "within_0.25": float((err <= 0.25).mean()), "dir": float((direction[dm] == ref.direction[dm]).mean())}


def score_x(ref, marks: dict, tol: int = 1) -> dict:
    """``marks``: bar -> side (+1 blue, -1 orange)."""
    ours = {i: s for i, s in marks.items() if ref.covered[i]}
    used, hit = set(), 0
    for i, side in ref.xmarks.items():
        j = next((k for k, s in ours.items() if k not in used and s == side and abs(k - i) <= tol), None)
        if j is not None:
            used.add(j)
            hit += 1
    return {"ref": len(ref.xmarks), "ours": len(ours), "matched": hit,
            "recall": hit / max(len(ref.xmarks), 1), "precision": hit / max(len(ours), 1)}


def load_reference(path: str):
    return pickle.load(open(path, "rb"))
