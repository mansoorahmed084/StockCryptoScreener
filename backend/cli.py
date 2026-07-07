"""Command-line entry point.

    python -m backend.cli matrix --coins SOL,ETH --base BTC
    python -m backend.cli markets            # sanity-check the data source
"""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from backend.config import load_config
from backend.data.adapters import build_adapter
from backend.data.ohlcv import OHLCVService
from backend.data.pairs import RatioBuilder
from backend.screener import matrix as matrix_mod
from backend.screener import universe as universe_mod
from backend.screener import filters as filters_mod

def _fmt_cell(direction: str, strength: float) -> str:
    if direction == "bull" and pd.notna(strength):
        return f"+{abs(strength):.1f}"
    if direction == "bear" and pd.notna(strength):
        return f"-{abs(strength):.1f}"
    if direction == "neutral":
        return "."
    return "?"


def cmd_matrix(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    adapter = build_adapter(config)
    adapter.refresh_markets()
    service = OHLCVService(adapter, config)

    coins = ([c.strip().upper() for c in args.coins.split(",")]
             if args.coins else universe_mod.select_universe(adapter, config))
    bases = ([b.strip().upper() for b in args.base.split(",")]
             if args.base else config.bases)
    timeframes = ([t.strip() for t in args.timeframes.split(",")]
                  if args.timeframes else config.timeframes)

    builder = RatioBuilder(service, config, universe_coins=coins)
    df = matrix_mod.build_matrix(builder, config, coins, bases, timeframes,
                                 apply_liquidity_gate=not args.no_liquidity_gate)

    for base in bases:
        print(f"\n=== base: {base} ===")
        sub = df[df["base"] == base]
        if sub.empty:
            print("  (no data)")
            continue
        grid = sub.pivot(index="coin", columns="timeframe", values="direction")
        strength = sub.pivot(index="coin", columns="timeframe", values="strength")
        grid = grid.reindex(columns=[t for t in timeframes if t in grid.columns])
        out = grid.copy()
        for c in grid.index:
            for t in grid.columns:
                out.loc[c, t] = _fmt_cell(grid.loc[c, t], strength.loc[c, t])
        print(out.to_string())
    return 0


def cmd_markets(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    adapter = build_adapter(config)
    markets = adapter.refresh_markets()
    quotes: dict[str, int] = {}
    for (_coin, quote) in markets:
        quotes[quote] = quotes.get(quote, 0) + 1
    print(f"{adapter.name}: {len(markets)} markets")
    for quote, n in sorted(quotes.items(), key=lambda kv: -kv[1]):
        print(f"  {quote:6s} {n}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """Build the matrix, evaluate presets, and fire de-duped alerts."""
    from backend.service import ScreenerService
    from backend.alerts import AlertDispatcher, notifier_from_env
    from backend.signals.journal import SignalJournal

    config = load_config(args.config)
    svc = ScreenerService(config)
    df = svc.build_matrix(liquidity_gate=True)
    disp = AlertDispatcher(SignalJournal(), notifier_from_env(),
                           cooldown_s=args.cooldown)
    presets = ([p.strip() for p in args.presets.split(",")]
               if args.presets else list(filters_mod.PRESETS))
    fired = []
    for name in presets:
        flt = filters_mod.PRESETS[name]()
        fired += disp.dispatch_preset(df, name, flt)
    print(f"scan complete: {len(fired)} new alert(s)")
    for e in fired:
        print(f"  [{e.preset}] {e.coin} {e.direction} vs {e.base} @ {e.timeframe} "
              f"({e.strength:+.1f})")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    from backend import scheduler

    presets = [p.strip() for p in args.presets.split(",")] if args.presets else None
    scheduler.start(interval_minutes=args.interval, config_path=args.config,
                    presets=presets, cooldown_s=args.cooldown)
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    from backend.service import ScreenerService
    from backend.signals.backtest import backtest_signal

    config = load_config(args.config)
    svc = ScreenerService(config)
    svc.build_matrix([args.coin], [args.base], [args.timeframe],
                     liquidity_gate=False)
    frame = svc.ratio_frame(args.coin, args.base, args.timeframe)
    if frame.empty:
        print("no data for that pair/timeframe")
        return 1
    params = config.classifier_params(args.timeframe)
    stats = backtest_signal(frame["close"], params, direction=args.direction,
                            horizon=args.horizon)
    print(f"{args.coin}/{args.base} {args.timeframe} · {args.direction} "
          f"(horizon {args.horizon}):")
    print(f"  entries={stats.n}  hit_rate={stats.hit_rate:.0%}  "
          f"mean_fwd={stats.mean_fwd:+.2f}%  median_fwd={stats.median_fwd:+.2f}%")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crypto relative-strength screener")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    m = sub.add_parser("matrix", help="print the RS matrix")
    m.add_argument("--coins", default=None, help="comma list, default = universe")
    m.add_argument("--base", default=None, help="comma list of bases")
    m.add_argument("--timeframes", default=None, help="comma list of timeframes")
    m.add_argument("--no-liquidity-gate", action="store_true")
    m.set_defaults(func=cmd_matrix)

    k = sub.add_parser("markets", help="list markets on the data source")
    k.set_defaults(func=cmd_markets)

    s = sub.add_parser("scan", help="evaluate presets and fire alerts")
    s.add_argument("--presets", default=None, help="comma list, default = all")
    s.add_argument("--cooldown", type=float, default=3600.0,
                   help="per-signal cooldown seconds")
    s.set_defaults(func=cmd_scan)

    w = sub.add_parser("watch", help="run periodic alert scans (always-on)")
    w.add_argument("--interval", type=int, default=5, help="minutes between scans")
    w.add_argument("--presets", default=None, help="comma list, default = all")
    w.add_argument("--cooldown", type=float, default=3600.0)
    w.set_defaults(func=cmd_watch)

    b = sub.add_parser("backtest", help="forward-return stats for a signal")
    b.add_argument("--coin", required=True)
    b.add_argument("--base", default="BTC")
    b.add_argument("--timeframe", default="1d")
    b.add_argument("--direction", default="bull", choices=["bull", "bear"])
    b.add_argument("--horizon", type=int, default=10)
    b.set_defaults(func=cmd_backtest)

    args = parser.parse_args(argv)
    try:  # ensure non-ASCII output never crashes on Windows consoles
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
