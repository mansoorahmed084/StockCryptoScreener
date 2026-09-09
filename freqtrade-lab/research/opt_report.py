"""Read the optimisation grid and rank it without being fooled by it.

    python research/opt_report.py 1d [top_n]

A 12,960-cell grid guarantees an impressive-looking winner whether or not an
edge exists. Four guards, in increasing order of how much they matter:

  1. floors on sample size, on both baskets
  2. HOLDOUT is the verdict; FIT is only allowed to select
  3. per-dial marginals -- a real dial trends across its values, a noise dial is
     flat with one lucky spike
  4. NEIGHBOUR agreement -- a config is scored by the mean holdout result of
     every config differing from it in exactly one dial. Ridges die, plateaus
     survive. This is the guard that killed the phase-6 result.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

RESULTS = Path(__file__).resolve().parent / "results"
MIN_FIT_N, MIN_HOLD_N = 30, 20
DIALS = ["side", "wt2_max", "trigger", "wait_bars", "atr_mult", "mfi_min",
         "gate", "target", "require_hold"]


def load(tf: str) -> list[dict]:
    """Every scored cell, from the append logs and from any older whole-file run.

    Both shapes exist on disk: the grid was restarted after the first version of
    the optimiser was replaced. Cells are de-duplicated on the config itself.
    """
    seen, rows = set(), []
    for p in sorted(RESULTS.glob(f"opt_{tf}_*.json")):
        try:
            rows += json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
    for p in sorted(RESULTS.glob(f"opt_{tf}_*.jsonl")):
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    out = []
    for r in rows:
        k = key(r["cfg"])
        if k in seen:
            continue
        seen.add(k)
        if ("error" not in r and r.get("fit", {}).get("n", 0) >= MIN_FIT_N
                and r.get("hold", {}).get("n", 0) >= MIN_HOLD_N):
            out.append(r)
    return out


def key(cfg: dict) -> tuple:
    return tuple(str(cfg[d]) for d in DIALS)


def neighbour_scores(rows: list[dict], metric: str) -> dict:
    """Mean holdout metric of every config one dial away.

    Built by substituting each dial's other observed values and looking the
    result up, rather than comparing every pair. The full grid clears the
    sample floors in the thousands, and the pairwise form is 9*n^2 Python
    iterations -- minutes to hours. Same numbers, linear in the grid.
    """
    by = {key(r["cfg"]): r for r in rows}
    values: list[set] = [set() for _ in DIALS]
    for k in by:
        for i, v in enumerate(k):
            values[i].add(v)
    out = {}
    for k in by:
        vals = []
        for i in range(len(DIALS)):
            for v in values[i]:
                if v == k[i]:
                    continue
                other = by.get(k[:i] + (v,) + k[i + 1:])
                if other is not None:
                    vals.append(other["hold"].get(metric, 0.0))
        out[k] = float(np.mean(vals)) if len(vals) >= 3 else float("nan")
    return out


def table(rows: list[dict], nb: dict, n: int, metric: str) -> str:
    head = ("| # | side | wt2 | trigger | wait | atr | mfi | gate | target | hold "
            "| FIT annR | **HOLD annR** | nbr | HOLD n | /yr | avgR | PF | maxDD_R | coins+ |")
    lines = [head, "|" + "---|" * 19]
    for i, r in enumerate(rows[:n], 1):
        c, f, h = r["cfg"], r["fit"], r["hold"]
        lines.append(
            f"| {i} | {c['side']} | {c['wt2_max']:g} | {c['trigger']} | "
            f"{c['wait_bars']} | {c['atr_mult']:g} | "
            f"{'green' if c['mfi_min'] is not None else '-'} | {c['gate']} | "
            f"{c['target']} | {'Y' if c['require_hold'] else 'N'} | "
            f"{f.get('annual_r', 0):+.2f} | **{h.get(metric, 0):+.2f}** | "
            f"{nb.get(key(c), float('nan')):+.2f} | {h['n']} | "
            f"{h.get('per_year', 0)} | {h['avg_r']:+.3f} | {h['pf']} | "
            f"{h['max_dd_r']} | {h['coins_pos']}/{h['coins_tested']} |")
    return "\n".join(lines)


def marginals(rows: list[dict], metric: str) -> str:
    buckets = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for d in DIALS:
            buckets[d][str(r["cfg"][d])].append(r["hold"].get(metric, 0.0))
    out = [f"\n## Marginal HOLDOUT {metric} per dial\n"]
    for d in DIALS:
        parts = [f"{v}: {np.mean(x):+.2f} ({len(x)})"
                 for v, x in sorted(buckets[d].items())]
        out.append(f"- **{d}** — " + " · ".join(parts))
    return "\n".join(out)


def main() -> None:
    tf = sys.argv[1] if len(sys.argv) > 1 else "1d"
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    rows = load(tf)
    if not rows:
        print("nothing cleared the sample floors")
        return
    print(f"# {tf}: {len(rows)} configs clear FIT n>={MIN_FIT_N} and "
          f"HOLD n>={MIN_HOLD_N}\n")

    nb = neighbour_scores(rows, "annual_r")
    pos_both = [r for r in rows
                if r["fit"].get("annual_r", 0) > 0 and r["hold"].get("annual_r", 0) > 0]
    print(f"positive annual R on FIT: {sum(1 for r in rows if r['fit'].get('annual_r',0)>0)}"
          f" · on HOLDOUT: {sum(1 for r in rows if r['hold'].get('annual_r',0)>0)}"
          f" · on BOTH: {len(pos_both)}")
    fa = np.array([r["fit"].get("annual_r", 0) for r in rows])
    ha = np.array([r["hold"].get("annual_r", 0) for r in rows])
    print(f"correlation FIT vs HOLDOUT annual R: {np.corrcoef(fa, ha)[0,1]:+.3f}\n")

    print("## Ranked by HOLDOUT annual R\n")
    print(table(sorted(rows, key=lambda r: -r["hold"].get("annual_r", 0)),
                nb, top, "annual_r"))

    robust = [r for r in rows if not np.isnan(nb.get(key(r["cfg"]), float("nan")))]
    print("\n## Ranked by NEIGHBOUR annual R (plateaus, not ridges)\n")
    print(table(sorted(robust, key=lambda r: -nb[key(r["cfg"])]), nb, top, "annual_r"))

    print(marginals(rows, "annual_r"))


if __name__ == "__main__":
    main()
