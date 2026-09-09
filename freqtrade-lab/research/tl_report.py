"""Rank the trendline grid with the four overfit guards.

    python research/tl_report.py [top_n]

1. MARGINALS first. The average holdout result for each value of a dial,
   taken over every setting of every other dial. A single-dial sweep can dip
   and rise by luck; a marginal cannot, because it averages hundreds of cells.
   This is the part to trust.
2. Selection on FIT, verdict on HOLDOUT. A table sorted by fit ratio, showing
   what the same cell did on coins it never saw.
3. NEIGHBOUR agreement. A real effect is a plateau. For each ranked cell,
   `nbr` is the fraction of its immediate grid neighbours (one dial moved one
   step) whose holdout avg_r is also positive. A winner with negative
   neighbours is a ridge, and a ridge is noise.
4. Per-coin spread, so one coin cannot carry the result.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tl_grid import GRID  # noqa: E402

RES = Path(__file__).resolve().parent / "results"


def load() -> list[dict]:
    rows = []
    for p in sorted(RES.glob("tlgrid_*.jsonl")):
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "fit" in r and "hold" in r and r["hold"].get("n"):
                    rows.append(r)
    return rows


def key(cfg: dict) -> tuple:
    return tuple(cfg[k] for k in GRID)


def neighbours(cfg: dict, by_key: dict) -> float:
    """Fraction of one-step grid neighbours with positive holdout avgR."""
    good = total = 0
    for dial, values in GRID.items():
        try:
            i = values.index(cfg[dial])
        except ValueError:
            continue
        for j in (i - 1, i + 1):
            if not 0 <= j < len(values):
                continue
            nb = dict(cfg, **{dial: values[j]})
            r = by_key.get(key(nb))
            if r is None:
                continue
            total += 1
            good += r["hold"]["avg_r"] > 0
    return good / total if total else 0.0


def main() -> None:
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    rows = load()
    if not rows:
        print("no scored cells yet")
        return
    by_key = {key(r["cfg"]): r for r in rows}
    print(f"# {len(rows)} scored cells\n")

    print("## Marginals - mean HOLDOUT over every other setting")
    print("| dial | value | cells | mean holdout avgR | mean annR | "
          "mean maxDD_R | mean ratio | cells with avgR>0 |")
    print("|" + "---|" * 8)
    for dial, values in GRID.items():
        for v in values:
            sel = [r for r in rows if r["cfg"][dial] == v]
            if not sel:
                continue
            avg = np.mean([r["hold"]["avg_r"] for r in sel])
            ann = np.mean([r["hold"].get("annual_r", 0) for r in sel])
            dd = np.mean([r["hold"]["max_dd_r"] for r in sel])
            rat = np.mean([r["hold"].get("ratio") or 0 for r in sel])
            pos = sum(1 for r in sel if r["hold"]["avg_r"] > 0)
            print(f"| {dial} | {v} | {len(sel)} | {avg:+.3f} | {ann:.1f} | "
                  f"{dd:.1f} | {rat:.2f} | {pos}/{len(sel)} |")
        print("|" + "---|" * 8)

    print("\n## Ranked by FIT ratio - HOLDOUT is the verdict")
    hdr = " | ".join(GRID)
    print(f"| {hdr} | FIT ratio | FIT annR || H n | H avgR | H PF | H annR | "
          "H maxDD_R | **H ratio** | +coins | nbr |")
    print("|" + "---|" * (len(GRID) + 10))
    ranked = sorted(rows, key=lambda r: -(r["fit"].get("ratio") or -99))
    for r in ranked[:top_n]:
        c, f, h = r["cfg"], r["fit"], r["hold"]
        cells = " | ".join(str(c[k]) for k in GRID)
        print(f"| {cells} | {f.get('ratio', 0):.2f} | {f.get('annual_r', 0):.1f} "
              f"|| {h['n']} | {h['avg_r']:+.3f} | {h['pf']} | "
              f"{h.get('annual_r', 0):.1f} | {h['max_dd_r']} | "
              f"**{h.get('ratio') or 0:.2f}** | "
              f"{h['coins_pos']}/{h['coins_tested']} | "
              f"{neighbours(c, by_key):.0%} |")

    hs = [r["hold"] for r in rows]
    print(f"\n## Overall: {sum(1 for h in hs if h['avg_r'] > 0)}/{len(hs)} cells "
          f"positive on holdout, median holdout ratio "
          f"{np.median([h.get('ratio') or 0 for h in hs]):.2f}")
    print("A strategy whose holdout is positive almost everywhere in the grid "
          "does not depend on the settings, which is the strongest evidence "
          "available here. One that is positive in a few cells does.")


if __name__ == "__main__":
    main()
