"""Market Desk command line.

  python -m market_desk night            backtest the rules + read the news
  python -m market_desk morning          screen + write trade plans
  python -m market_desk tick             paper trades + price alerts, once
  python -m market_desk watch            all of the above, on the schedule
  python -m market_desk status           paper account, plans, trades
  python -m market_desk backtest         only the backtest
  python -m market_desk screen           only the screen (saves nothing)
  python -m market_desk news             only the news research
  python -m market_desk screener-snap    save screener results for the cloud page
  python -m market_desk alert add NSE:RELIANCE above 1500 --note "breakout"
  python -m market_desk alert list | alert rm 3

Paper only: nothing here sends a real order.
"""
from __future__ import annotations

import argparse
import logging
import math
import sys

from backend.trading.tgfmt import px

from .settings import MARKET_NAMES, short


def _f(x, fmt="+.2f", unit=""):
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:{fmt}}{unit}"


def print_verdicts(verdicts: list[dict]) -> None:
    print(f"{'market':7} {'rule':11} {'keep':5} {'trades':>6} {'win%':>5} {'avg R':>6} "
          f"{'PF':>5} {'DD R':>5} | {'ctl n':>5} {'ctl R':>6} | {'1y R':>6}  why")
    for v in verdicts:
        print(f"{MARKET_NAMES[v['market']]:7} {v['rule']:11} {'KEEP' if v['keep'] else 'kill':5} "
              f"{v['w_trades']:>6} {v['w_win']:>5.0f} {v['w_exp']:>+6.2f} {v['w_pf']:>5.2f} "
              f"{v['w_dd']:>5.1f} | {v['c_trades']:>5} {v['c_exp']:>+6.2f} | "
              f"{_f(v['recent_exp']):>6}  {v['why']}")


def print_screen(rows: list[dict], n: int = 30) -> None:
    print(f"{'symbol':22} {'score':>5} {'trend':6} {'RSI':>4} {'1d%':>6} {'1w%':>6} {'1m%':>6} "
          f"{'vol':>4}  setups / notes")
    for r in rows[:n]:
        extra = "; ".join(x for x in (r["setups"], r["notes"]) if x)
        print(f"{r['symbol']:22} {r['score']:>5.0f} {r['trend']:6} {_f(r['rsi'], '.0f'):>4} "
              f"{_f(r['chg_1d'], '+.1f'):>6} {_f(r['chg_1w'], '+.1f'):>6} "
              f"{_f(r['chg_1m'], '+.1f'):>6} {_f(r['vol_ratio'], '.1f'):>4}  {extra}")


def print_plans(plans: list[dict]) -> None:
    for p in plans:
        rr = (p["target"] - p["entry"]) / (p["entry"] - p["stop"])
        print(f"  #{p.get('id', '?'):<4} {short(p['symbol']):12} {p['rule']:11} buy above "
              f"{px(p['entry'])}  stop {px(p['stop'])}  target {px(p['target'])}  ({rr:.1f}R)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m market_desk",
                                 description="Market Desk: research + paper trading "
                                             "(separate from the screener).")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("night", "morning"):
        p = sub.add_parser(name)
        p.add_argument("--quiet", action="store_true", help="no Telegram card")
    sub.add_parser("tick")
    w = sub.add_parser("watch")
    w.add_argument("--interval", type=float, help="minutes between ticks")
    sub.add_parser("status")
    sub.add_parser("backtest")
    sub.add_parser("screen")
    sub.add_parser("news")
    snap = sub.add_parser("screener-snap", help="save screener results for the cloud page")
    snap.add_argument("--parts", default="rs,btc,patterns,liq")
    al = sub.add_parser("alert")
    alsub = al.add_subparsers(dest="alert_cmd", required=True)
    a_add = alsub.add_parser("add")
    a_add.add_argument("symbol")
    a_add.add_argument("op", choices=["above", "below"])
    a_add.add_argument("price", type=float)
    a_add.add_argument("--note", default="")
    alsub.add_parser("list")
    a_rm = alsub.add_parser("rm")
    a_rm.add_argument("id", type=int)
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from .routines import Desk
    desk = Desk()

    if args.cmd == "night":
        out = desk.night(notify=not args.quiet)
        print_verdicts(out["verdicts"])
        fng = out["fear_greed"]
        if fng:
            print(f"\nCrypto Fear & Greed: {fng['value']} ({fng['label']})")
        print("News spikes:", ", ".join(out["spikes"]) or "none")
    elif args.cmd == "morning":
        out = desk.morning(notify=not args.quiet)
        print_screen(out["screen"])
        print(f"\nNew plans: {len(out['plans'])}")
        print_plans(out["plans"])
    elif args.cmd == "tick":
        events = desk.tick()
        for ev in events:
            print(ev.kind, ev.symbol)
        print(f"{len(events)} event(s)")
    elif args.cmd == "watch":
        logging.getLogger().setLevel(logging.INFO)
        desk.watch(args.interval)
    elif args.cmd == "status":
        from .paper import account
        acc = account(desk.settings, desk.store)
        print(f"Paper equity {acc['equity']:,.0f} ({acc['return_pct']:+.2f}%) · "
              f"{acc['closed']} closed, win {acc['win_rate']:.0f}%, avg {acc['avg_r']:+.2f}R, "
              f"total {acc['total_r']:+.2f}R · {acc['open']} open "
              f"({acc['open_risk_pct']:.1f}% at risk)")
        print("\nPending plans:")
        print_plans(desk.store.plans("pending"))
        print("\nOpen trades:")
        for t in desk.store.trades("open"):
            print(f"  #{t['id']:<4} {short(t['symbol']):12} {t['rule']:11} in {px(t['entry'])}  "
                  f"stop {px(t['stop'])}  target {px(t['target'])}")
        for key in ("night", "morning", "tick"):
            ts = desk.store.get_meta(f"last_{key}")
            if ts:
                import datetime as dt
                when = dt.datetime.fromtimestamp(int(ts)).strftime("%d %b %H:%M")
                print(f"last {key}: {when}")
    elif args.cmd == "backtest":
        print_verdicts(desk.backtest())
    elif args.cmd == "screen":
        from .screen import run_screen
        print_screen(run_screen(desk.settings, desk.data))
    elif args.cmd == "news":
        out = desk.research()
        for r in sorted(out["rows"], key=lambda r: -(r["buzz"] or 0)):
            fund = f" funding {r['funding']:+.4f}%" if r.get("funding") is not None else ""
            buzz = f"{r['buzz']:>4.1f}" if r["buzz"] is not None else "  — "
            print(f"{short(r['symbol']):12} 24h {r['headlines_24h']:>3}  7d {r['headlines_7d']:>3}"
                  f"  buzz {buzz}  tone {r['tone']:+.2f} {r['label']:8}"
                  f"{' SPIKE' if r['spike'] else ''}{fund}")
    elif args.cmd == "screener-snap":
        from .screener_snap import run
        out = run(desk.store, parts=tuple(p.strip() for p in args.parts.split(",") if p.strip()))
        for part, state in out.items():
            print(f"{part:9} {state}")
        if any(s.startswith("failed") for s in out.values()):
            return 1
    elif args.cmd == "alert":
        from . import alerts
        if args.alert_cmd == "add":
            aid = alerts.add(desk.store, args.symbol, args.op, args.price, args.note)
            print(f"alert #{aid} set")
        elif args.alert_cmd == "list":
            for a in desk.store.alerts():
                state = f"fired at {px(a['fired_px'])}" if a["fired_ts"] else "active"
                print(f"#{a['id']:<4} {a['symbol']:22} {a['op']:5} {px(a['price']):>10}  "
                      f"{state}  {a['note'] or ''}")
        else:
            desk.store.delete_alert(args.id)
            print(f"alert #{args.id} removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
