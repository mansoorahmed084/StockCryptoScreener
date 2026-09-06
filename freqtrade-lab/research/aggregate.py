"""Read every sweep result and rank them without fooling ourselves.

    python research/aggregate.py batch2

A 1000-run grid guarantees some config scores 80% on 12 trades. Three guards:

  1. a hard floor on n, and on out-of-sample n
  2. marginal analysis — the average score for each value of each dial. A dial
     that matters shows a trend across its values; a dial that is noise shows a
     flat line with a lucky spike
  3. neighbour scoring — a config is only interesting if the configs adjacent to
     it in parameter space also score well. Isolated peaks are overfit
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

RESULTS = Path(__file__).resolve().parent / "results"
MIN_N = 40
MIN_OOS_N = 4
# The new brief: 12 trades/year is not tradeable. Roughly weekly is.
MIN_PER_YEAR = 40.0


def load(prefix: str) -> list[dict]:
    rows = []
    for path in sorted(RESULTS.glob(f"{prefix}_*.json")):
        rows.extend(json.loads(path.read_text(encoding="utf-8")))
    return [r for r in rows if r.get("all", {}).get("n")]


def parse_label(label: str) -> dict:
    """Pull the dial values back out of the generated label."""
    d = {}
    if (m := re.search(r"wt2<=(-?[\d.]+)", label)):
        d["wt2"] = float(m.group(1))
    if (m := re.search(r"atr([\d.]+)", label)):
        d["atr_mult"] = float(m.group(1))
    if (m := re.search(r"piv(\d+)", label)):
        d["pivot"] = int(m.group(1))
    if (m := re.search(r"\b(nogate|btc1d|eth1d|eth4h)\b", label)):
        d["gate"] = m.group(1)
    if (m := re.search(r"vol(None|[\d.]+)", label)):
        d["vol"] = m.group(1)
    if (m := re.search(r"\b(fix3R|G3b|G3)\b", label)):
        d["exit"] = m.group(1)
    return d


def marginals(rows: list[dict], metric: str) -> str:
    """Average metric per dial value — separates real dials from noise."""
    buckets: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        dials = parse_label(r["label"])
        val = r["all"].get(metric)
        if val is None:
            continue
        for k, v in dials.items():
            buckets[k][v].append(val)

    out = [f"\n### Marginal {metric} per dial (n>={MIN_N} runs only)\n"]
    for dial in sorted(buckets):
        parts = []
        for value in sorted(buckets[dial], key=lambda x: (isinstance(x, str), x)):
            vals = buckets[dial][value]
            parts.append(f"{value}: {np.mean(vals):+.3f} ({len(vals)})")
        out.append(f"- **{dial}** — " + " · ".join(parts))
    return "\n".join(out)


def neighbour_score(rows: list[dict], metric: str) -> dict[str, float]:
    """Average the metric over configs that differ in exactly one numeric dial."""
    parsed = [(parse_label(r["label"]), r) for r in rows]
    scores = {}
    for dials, r in parsed:
        vals = [r["all"][metric]]
        for other_d, other_r in parsed:
            if other_r is r or other_d.keys() != dials.keys():
                continue
            diffs = sum(1 for k in dials if dials[k] != other_d[k])
            if diffs == 1:
                vals.append(other_r["all"][metric])
        scores[r["label"]] = float(np.mean(vals)) if len(vals) > 2 else float("nan")
    return scores


def table(rows: list[dict], nb: dict, limit: int) -> str:
    head = ("| # | config | n | /yr | win_net% | win_3R% | avgR | nbr avgR | PF "
            "| maxDD_R | IS win% | OOS n | OOS win% |")
    lines = [head, "|" + "---|" * 13]
    for i, r in enumerate(rows[:limit], 1):
        a, isx, o = r["all"], r["is"], r["oos"]
        n_score = nb.get(r["label"], float("nan"))
        lines.append(
            f"| {i} | {r['label']} | {a['n']} | {a.get('trades_per_year','—')} | "
            f"**{a['win_net_pct']}** | {a['win_target_pct']} | {a['avg_r']} | "
            f"{n_score:+.3f} | {a['pf']} | {a['max_dd_r']} | "
            f"{isx.get('win_net_pct','—')} | {o.get('n',0)} | "
            f"{o.get('win_net_pct','—')} |")
    return "\n".join(lines)


def main() -> None:
    prefix = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    every = load(prefix)
    kept = [r for r in every
            if r["all"]["n"] >= MIN_N and r["oos"].get("n", 0) >= MIN_OOS_N
            and (r["all"].get("trades_per_year") or 0) >= MIN_PER_YEAR]

    print(f"# {prefix}: {len(every)} runs, {len(kept)} pass n>={MIN_N}, "
          f"OOS n>={MIN_OOS_N} and >={MIN_PER_YEAR:g} trades/year")
    if not kept:
        print("\nNothing clears the sample-size floor. That is the finding.")
        best = sorted(every, key=lambda r: -r["all"]["n"])[:10]
        print("\n### Largest samples available\n")
        print(table(best, {}, 10))
        return

    nb = neighbour_score(kept, "avg_r")

    print("\n## Ranked by expectancy (avgR)\n")
    print(table(sorted(kept, key=lambda r: -r["all"]["avg_r"]), nb, limit))

    print("\n## Ranked by net-win rate\n")
    print(table(sorted(kept, key=lambda r: -r["all"]["win_net_pct"]), nb, limit))

    print("\n## Ranked by NEIGHBOUR expectancy (overfit-resistant)\n")
    robust = [r for r in kept if not np.isnan(nb.get(r["label"], float("nan")))]
    print(table(sorted(robust, key=lambda r: -nb[r["label"]]), nb, limit))

    print(marginals(kept, "avg_r"))
    print(marginals(kept, "win_net_pct"))


if __name__ == "__main__":
    main()
