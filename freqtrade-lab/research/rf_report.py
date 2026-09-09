"""Rank the refined-entry grid, with the control shown first.

    python research/rf_report.py [top_n]

The question is narrow: does timing the entry on 1h candles, and placing the
stop from 1h structure, beat taking the next daily open with the daily stop?
So the control (`next_open` + `daily`) is printed first and every table is read
against it. Selection on FIT, verdict on HOLDOUT, neighbour agreement to tell a
plateau from a ridge -- the same guards as every other grid here.

The entry x stop table is the one that answers the question, because each cell
averages over every wait, ATR and exit setting and so cannot be a lucky corner.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rf_grid import GRID  # noqa: E402

RES = Path(__file__).resolve().parent / "results"
CONTROL = {"entry_mode": "next_open", "stop_mode": "daily"}


def load() -> list[dict]:
    rows = []
    for p in sorted(RES.glob("rfgrid_*.jsonl")):
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
    good = total = 0
    for dial, values in GRID.items():
        try:
            i = values.index(cfg[dial])
        except ValueError:
            continue
        for j in (i - 1, i + 1):
            if not 0 <= j < len(values):
                continue
            r = by_key.get(key(dict(cfg, **{dial: values[j]})))
            if r is None:
                continue
            total += 1
            good += r["hold"]["avg_r"] > 0
    return good / total if total else 0.0


def stat(sel: list[dict]) -> dict:
    return {
        "cells": len(sel),
        "n": np.mean([r["hold"]["n"] for r in sel]),
        "avg": np.mean([r["hold"]["avg_r"] for r in sel]),
        "ann": np.mean([r["hold"].get("annual_r", 0) for r in sel]),
        "dd": np.mean([r["hold"]["max_dd_r"] for r in sel]),
        "rat": np.mean([r["hold"].get("ratio") or 0 for r in sel]),
        "pos": sum(1 for r in sel if r["hold"]["avg_r"] > 0),
    }


def main() -> None:
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    rows = load()
    if not rows:
        print("no scored cells yet")
        return
    by_key = {key(r["cfg"]): r for r in rows}
    ctl = [r for r in rows
           if all(r["cfg"][k] == v for k, v in CONTROL.items())]
    print(f"# {len(rows)} scored cells\n")

    if ctl:
        c = stat(ctl)
        print("## The CONTROL: next daily open, daily stop")
        print(f"Averaged over its {c['cells']} exit settings — holdout "
              f"trades {c['n']:.0f}, avgR {c['avg']:+.3f}, annual_R {c['ann']:.1f}, "
              f"maxDD_R {c['dd']:.1f}, **ratio {c['rat']:.2f}**")
        best = max(ctl, key=lambda r: r["hold"].get("ratio") or 0)
        print(f"Its best exit: {best['cfg']['exit']} -> holdout ratio "
              f"{best['hold'].get('ratio', 0):.2f}, avgR "
              f"{best['hold']['avg_r']:+.3f}, {best['hold']['n']} trades\n")
        ctl_rat = c["rat"]
    else:
        ctl_rat = 0.0

    print("## Entry x stop — each cell averaged over every wait, ATR and exit")
    print("| entry | stop | cells | H trades | H avgR | H annR | H maxDD_R | "
          "**H ratio** | vs control | cells +ve |")
    print("|" + "---|" * 10)
    for em in GRID["entry_mode"]:
        for sm in GRID["stop_mode"]:
            sel = [r for r in rows if r["cfg"]["entry_mode"] == em
                   and r["cfg"]["stop_mode"] == sm]
            if not sel:
                continue
            s = stat(sel)
            tag = "  <- CONTROL" if (em, sm) == ("next_open", "daily") else ""
            delta = f"{s['rat'] - ctl_rat:+.2f}" if ctl_rat else "-"
            print(f"| {em} | {sm} | {s['cells']} | {s['n']:.0f} | "
                  f"{s['avg']:+.3f} | {s['ann']:.1f} | {s['dd']:.1f} | "
                  f"**{s['rat']:.2f}** | {delta}{tag} | {s['pos']}/{s['cells']} |")

    print("\n## Marginals — mean HOLDOUT over every other setting")
    print("| dial | value | cells | H avgR | H annR | H maxDD_R | H ratio | +ve |")
    print("|" + "---|" * 8)
    for dial, values in GRID.items():
        for v in values:
            sel = [r for r in rows if r["cfg"][dial] == v]
            if not sel:
                continue
            s = stat(sel)
            print(f"| {dial} | {v} | {s['cells']} | {s['avg']:+.3f} | "
                  f"{s['ann']:.1f} | {s['dd']:.1f} | {s['rat']:.2f} | "
                  f"{s['pos']}/{s['cells']} |")
        print("|" + "---|" * 8)

    print("\n## Ranked by FIT ratio — HOLDOUT is the verdict")
    print(f"| {' | '.join(GRID)} | FIT ratio || H n | H win% | H avgR | H PF | "
          "H annR | H maxDD_R | **H ratio** | +coins | nbr |")
    print("|" + "---|" * (len(GRID) + 10))
    for r in sorted(rows, key=lambda r: -(r["fit"].get("ratio") or -99))[:top_n]:
        c, f, h = r["cfg"], r["fit"], r["hold"]
        cells = " | ".join(str(c[k]) for k in GRID)
        print(f"| {cells} | {f.get('ratio', 0):.2f} || {h['n']} | "
              f"{h['win_net_pct']} | {h['avg_r']:+.3f} | {h['pf']} | "
              f"{h.get('annual_r', 0):.1f} | {h['max_dd_r']} | "
              f"**{h.get('ratio') or 0:.2f}** | "
              f"{h['coins_pos']}/{h['coins_tested']} | "
              f"{neighbours(c, by_key):.0%} |")

    hs = [r["hold"] for r in rows]
    print(f"\n## Overall: {sum(1 for h in hs if h['avg_r'] > 0)}/{len(hs)} cells "
          f"positive on holdout, median holdout ratio "
          f"{np.median([h.get('ratio') or 0 for h in hs]):.2f}")


if __name__ == "__main__":
    main()
