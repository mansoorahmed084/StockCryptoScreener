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
    from backend.scheduler import run_scan

    config = load_config(args.config)
    presets = ([p.strip() for p in args.presets.split(",")]
               if args.presets else None)
    fired = run_scan(config, presets=presets, cooldown_s=args.cooldown)
    print(f"scan complete: {len(fired)} new alert(s)")
    for e in fired:
        print(f"  [{e.preset}] {e.coin} {e.direction} vs {e.base} @ {e.timeframe} "
              f"({e.strength:+.1f})")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Multi-TF bullish confluence + VuManChu divergence report."""
    from backend.service import ScreenerService

    config = load_config(args.config)
    svc = ScreenerService(config)
    coins = ([c.strip().upper() for c in args.coins.split(",")]
             if args.coins else None)
    timeframes = ([t.strip() for t in args.timeframes.split(",")]
                  if args.timeframes else None)
    df = svc.report(coins, args.base, timeframes,
                    div_lookback=args.div_lookback,
                    require_all_bull=args.all_bull)
    if df.empty:
        print("no coins matched")
        return 0

    tfs = timeframes or ["15m", "4h", "1d", "1w"]
    out = pd.DataFrame(index=df["coin"])
    for tf in tfs:
        cells = []
        for _, r in df.iterrows():
            cell = _fmt_cell(r[f"dir_{tf}"],
                             r[f"strength_{tf}"] if r[f"strength_{tf}"] is not None
                             else float("nan"))
            div = r[f"div_{tf}"]
            if div:
                cell += f" [div:{div}]"
            cells.append(cell)
        out[tf] = cells
    out["score"] = df["score"].values
    out["all_bull"] = ["YES" if x else "" for x in df["all_bull"]]
    out["multi_div"] = ["YES" if x else "" for x in df["multi_tf_bull_div"]]
    print(f"\n=== bullish confluence vs {args.base.upper()} "
          f"(divs within last {args.div_lookback} candles) ===")
    print(out.to_string())
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    from backend import scheduler

    presets = [p.strip() for p in args.presets.split(",")] if args.presets else None
    scheduler.start(interval_minutes=args.interval, config_path=args.config,
                    presets=presets, cooldown_s=args.cooldown)
    return 0


def cmd_alerts(args: argparse.Namespace) -> int:
    """Check price / trendline / zone alerts on a loop, dashboard or not."""
    import time as _time

    from backend.alerts.price_alerts import ACTIVE, message
    from backend.service import ScreenerService

    svc = ScreenerService(load_config(args.config), refresh=False)
    print(f"checking {len(svc.alerts().list(ACTIVE))} active alert(s) every "
          f"{args.every}s — Ctrl+C to stop", flush=True)
    while True:
        try:
            for a in svc.check_alerts():
                print(message(a), flush=True)
        except Exception as exc:              # keep watching through a bad round
            print(f"check failed: {exc}", flush=True)
        if args.once:
            return 0
        _time.sleep(args.every)


def cmd_journal(args: argparse.Namespace) -> int:
    """Replay the paper trades in journal/trades.csv and refresh the journal."""
    import time as _time

    from backend import trade_journal as tj
    from backend.service import ScreenerService

    svc = ScreenerService(load_config(args.config), refresh=False)
    fut = svc.futures()
    trades = tj.load(args.csv)
    now = int(_time.time() * 1000)
    outcomes = tj.run(trades, fut.klines, fut.perpetuals(), now)
    blocks = tj.render(trades, outcomes, now)
    tj.write_markdown(args.md, blocks)
    print(blocks["SUMMARY"])
    print(f"\nupdated {args.md}")
    return 0


def cmd_setups(args: argparse.Namespace) -> int:
    """Scan the top coins, rank the buy setups, and optionally journal the picks."""
    from backend.screener import buy_setups as bs
    from backend.screener import pattern_scan as ps
    from backend.service import ScreenerService

    svc = ScreenerService(load_config(args.config), refresh=False)
    fut = svc.futures()
    coins = svc.liquidation_coins(args.top)
    scan = ps.scan(fut.klines, coins, ["15m", "1h", "4h", "1d"],
                   patterns=ps.BULLISH + ps.BEARISH)
    trends = {}
    for sym in scan["symbol"].unique():
        try:
            trends[sym] = (bs.trend(fut.klines(sym, "1d", 300)["close"]),
                           bs.trend(fut.klines(sym, "4h", 300)["close"]))
        except Exception:
            trends[sym] = ("?", "?")
    ranked = bs.rank(scan, trends)

    taken: set[tuple[str, str, str]] = set()
    trades = None
    if args.journal:
        trades = pd.read_csv(args.csv)
        recent = pd.to_datetime(trades["day"]) >= pd.Timestamp.now() - pd.Timedelta(days=args.skip_days)
        taken = set(zip(trades.loc[recent, "coin"], trades.loc[recent, "tf"],
                        trades.loc[recent, "setup"]))
    picks = bs.pick(ranked, args.n, taken)
    cols = ["kind", "score", "coin", "timeframe", "pattern", "status", "price", "up_level",
            "down_level", "target_up", "rr", "zone_above_pct", "setup"]
    print(f"{len(scan)} patterns on {scan['coin'].nunique()} coins; "
          f"{len(ranked)} live buy setups; {len(picks)} pass every rule:\n")
    print(picks[cols].to_string(index=False, float_format=lambda v: f"{v:.5g}"))
    if args.journal and len(picks):
        now = pd.Timestamp.now(tz="UTC").floor("min")
        rows = bs.journal_rows(picks, fut.klines, first_id=int(trades["id"].max()) + 1,
                               day=now.strftime("%Y-%m-%d"),
                               when_utc=now.strftime("%Y-%m-%d %H:%M"),
                               list_name=now.strftime("%d %b %H:%M"))
        pd.concat([trades, pd.DataFrame(rows)], ignore_index=True) \
            .to_csv(args.csv, index=False, lineterminator="\n")
        print(f"\nadded {len(rows)} trade(s) to {args.csv}")
    return 0


def cmd_scalp(args: argparse.Namespace) -> int:
    """Exhaustion scalps: big movers whose momentum is fading (see SCALP.md)."""
    from backend.screener import scalp as sc
    from backend.service import ScreenerService

    svc = ScreenerService(load_config(args.config), refresh=False)
    fut = svc.futures()
    coins = svc.liquidation_coins(args.top)
    try:
        funding = fut.funding_rates()
    except Exception:
        funding = {}

    def oi_24h(sym: str) -> float:
        oi = fut.open_interest(sym, "1h", 25)["oi_value"]
        return (float(oi.iloc[-1]) / float(oi.iloc[0]) - 1) * 100

    p = sc.Params(min_move_pct=args.min_move, min_score=args.min_score)
    found = sc.scan(fut.klines, coins, tf=args.tf, funding=funding, open_interest=oi_24h, p=p)
    print(f"{len(coins)} coins on {args.tf}: {len(found)} exhaustion scalp(s), "
          f"score >= {args.min_score} of {len(sc.CHECKS)}\n")
    if not found:
        return 0
    rows = [{"coin": s.coin, "side": s.side, "status": s.status, "score": s.score,
             "price": s.price, "move24h%": s.move_pct, "vwapATR": s.ext_atr,
             "trigger": s.trigger, "stop": s.stop, "T1": s.t1, "T2": s.t2, "rr1": s.rr1,
             "rr2": s.rr2, "rsi": s.rsi, "fund%": s.funding_pct, "oi24h%": s.oi_24h_pct,
             "checks": " ".join(s.checks)} for s in found]
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:.5g}"))
    if args.journal:
        from pathlib import Path

        from backend import scalp_journal as sj

        path = Path(args.csv)
        old = pd.read_csv(path) if path.exists() and path.stat().st_size else \
            pd.DataFrame(columns=sj.COLUMNS)
        now = pd.Timestamp.now(tz="UTC").floor("min")
        recent = old[pd.to_datetime(old["time_utc"], utc=True)
                     >= now - pd.Timedelta(hours=args.skip_hours)] if len(old) else old
        taken = set(zip(recent["coin"], recent["side"])) if len(recent) else set()
        new = [s for s in found if (s.coin, s.side) not in taken]
        rows = sj.rows_from_setups(new, first_id=int(old["id"].max()) + 1 if len(old) else 1,
                                   when_utc=now.strftime("%Y-%m-%d %H:%M"), tf=args.tf)
        if rows:
            pd.concat([old, pd.DataFrame(rows)], ignore_index=True)[sj.COLUMNS] \
                .to_csv(path, index=False, lineterminator="\n")
        print(f"\njournaled {len(rows)} call(s) in {path}"
              + (f" ({len(found) - len(rows)} already there)" if len(found) > len(rows) else ""))
    return 0


def cmd_scalp_journal(args: argparse.Namespace) -> int:
    """Replay the scalp calls in journal/scalps.csv and refresh the journal."""
    import time as _time

    from backend import scalp_journal as sj
    from backend.service import ScreenerService

    fut = ScreenerService(load_config(args.config), refresh=False).futures()
    calls = sj.load(args.csv)
    now = int(_time.time() * 1000)
    blocks = sj.render(calls, sj.run(calls, fut.klines, now), now)
    sj.write_markdown(args.md, blocks)
    print(blocks["SUMMARY"])
    print(f"\nupdated {args.md}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    from backend.service import ScreenerService
    from backend.signals.backtest import backtest_signal

    config = load_config(args.config)
    svc = ScreenerService(config)
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


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def _yes(pair: str, question: str) -> str:
    """Show the pair and ask y/n. Returns the pair (the manager's confirm token) on yes."""
    answer = _ask(f"{question} {pair}? [y/N]: ").strip().lower()
    return pair if answer in ("y", "yes") else ""


def _request(args: argparse.Namespace):
    from backend.trading import risk

    return risk.TradeRequest(
        pair=args.pair, side=args.side, stop_loss=args.sl, take_profit=args.tp,
        risk_inr=args.risk, leverage=args.lev,
        entry_type=risk.LIMIT if args.limit else risk.MARKET, limit_price=args.limit,
        margin_inr=args.margin, override=args.override)


def _ledger_coins(config, account: str) -> list[str]:
    """The active coins of an account's recovery ledger ([] when it has none)."""
    from pathlib import Path

    from backend.trading import recovery

    path = recovery.ledger_path(
        str(Path(config.trading.get("db", "data_cache/trading.db")).parent), account)
    return [r.coin for r in recovery.load(path) if r.status == recovery.ACTIVE]


def _run_bot(config, mgrs, scan_accounts, args) -> int:
    """Watch every account, scan the given ones every ``--every-min`` minutes and
    handle Telegram button taps until Ctrl+C. Places nothing by itself."""
    import threading
    import time as _time

    from backend.service import ScreenerService
    from backend.trading import ideas, tgbot, trailing

    trail = trailing.Settings.from_config(config.trading.get("trailing"))
    settings = ideas.Settings.from_config(config.trading.get("setups"))
    by_name = {m.account: m for m in mgrs}
    every_min = args.every_min or 15
    listener = tgbot.Listener(by_name, settings) if tgbot.telegram_from_env() else None
    print(f"[{'LIVE' if mgrs[0].live else 'DRY RUN (nothing is sent)'}] bot: watching "
          f"{', '.join(by_name)} every {args.every}s; scanning "
          f"{', '.join(scan_accounts) or 'nothing'} every {every_min} min; Telegram buttons "
          f"{'on' if listener else 'OFF (set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)'}"
          " - Ctrl+C to stop", flush=True)

    def taps() -> None:
        while True:
            try:
                for line in listener.poll(timeout=20):
                    print(f"telegram: {line}", flush=True)
            except Exception as exc:                 # keep listening through a bad round
                print(f"telegram: listen failed: {exc}", flush=True)
                _time.sleep(5)

    if listener:
        threading.Thread(target=taps, name="telegram-taps", daemon=True).start()
    svc, next_scan = None, 0.0
    while True:
        for one in mgrs:
            tag = "" if len(mgrs) == 1 else f"[{one.account}] "
            try:
                with one.lock:
                    for m in one.reconcile() + trailing.run(one, trail):
                        print(tag + m, flush=True)
            except Exception as exc:
                print(f"{tag}check failed: {exc}", flush=True)
        if scan_accounts and _time.time() >= next_scan:
            next_scan = _time.time() + every_min * 60
            svc = svc or ScreenerService(config, refresh=False)
            for name in scan_accounts:
                one = by_name[name]
                coins = _ledger_coins(config, name) or None
                try:
                    with one.lock:
                        new = ideas.scan(one, ideas.find_setups(svc, settings.top, coins),
                                         settings)
                    ready = [i for i in new if i["status"] == ideas.READY]
                    print(f"[{name}] scan: {len(new)} new setup(s), {len(ready)} ready"
                          + (" - sent to Telegram" if ready and listener else ""), flush=True)
                except Exception as exc:
                    print(f"[{name}] scan failed: {exc}", flush=True)
        _time.sleep(args.every)


def _print_ledger(lines, path) -> None:
    """The spot-loss recovery ledger, one coin a line, closest to breakeven first."""
    active = sorted((x for x in lines if x.status == "active"), key=lambda x: x.to_go_inr)
    print(f"{'coin':8} {'paid':>9} {'spot now':>9} {'spot P&L':>9} {'futures':>9} "
          f"{'ledger':>9} {'to go':>8}  (Rs; futures = closed + open since start)")
    for x in active:
        flag = ("  << BREAKEVEN: close futures and sell spot" if x.ready
                else "" if x.has_futures else "  (no INR futures pair)")
        print(f"{x.coin:8} {x.paid_inr:9,.0f} {x.spot_now_inr:9,.0f} {x.spot_pnl_inr:9,.0f} "
              f"{x.futures_closed_inr + x.futures_open_inr:9,.0f} {x.total_inr:9,.0f} "
              f"{x.to_go_inr:8,.0f}{flag}")
        if x.note:
            print(f"{'':9}note: {x.note}")
    if active:
        print(f"{'TOTAL':8} {sum(x.paid_inr for x in active):9,.0f} "
              f"{sum(x.spot_now_inr for x in active):9,.0f} "
              f"{sum(x.spot_pnl_inr for x in active):9,.0f} "
              f"{sum(x.futures_closed_inr + x.futures_open_inr for x in active):9,.0f} "
              f"{sum(x.total_inr for x in active):9,.0f} {sum(x.to_go_inr for x in active):8,.0f}")
    for st in ("done", "skip"):
        names = [x.coin for x in lines if x.status == st]
        if names:
            print(f"{st}: {', '.join(names)}")
    print(f"ledger file: {path}")


def cmd_trade(args: argparse.Namespace) -> int:
    """CoinDCX INR futures: status, preview, open, move SL/TP, close, panic."""
    import time as _time

    from backend.trading import risk
    from backend.trading.client import MAIN, accounts, env_names
    from backend.trading.manager import TradeError, TradeManager

    config = load_config(args.config)
    act = args.action
    known = accounts()
    account = (args.account or MAIN).lower()
    if account not in known:
        try:
            key, secret = env_names(account)
            print(f"no account {account!r}: put {key} and {secret} in .env "
                  f"(accounts found: {', '.join(known)})")
        except ValueError as exc:
            print(exc)
        return 1
    mgr = TradeManager.from_config(config, force_dry_run=args.dry_run, account=account)
    banner = (("LIVE" if mgr.live else "DRY RUN (nothing is sent)")
              + ("" if len(known) == 1 else f" · account {account}"))
    try:
        if act == "status":
            s = mgr.status()
            print(f"mode: {banner}   keys: {'set' if s['keys'] else 'MISSING'}"
                  f"   halted: {s['halted']}")
            if not s["keys"]:
                return 0
            for w in s["wallets"]:
                print(f"wallet {w.get('currency_short_name')}: balance {w.get('balance')}"
                      f"  locked {w.get('locked_balance')}")
            print(f"loss today: Rs {s['loss_today_inr']:,.0f}")
            for p in s["positions"]:
                print(f"{p['pair']}: {p['active_pos']:+g} @ {p['avg_price']}  "
                      f"SL {p.get('stop_loss_trigger') or 'NONE'}  "
                      f"TP {p.get('take_profit_trigger') or 'none'}  "
                      f"{p.get('leverage')}x  liq {p.get('liquidation_price')}")
            for o in s["orders"]:
                print(f"order {o['id']}: {o['pair']} {o['side']} {o['order_type']} "
                      f"{o.get('total_quantity')} @ {o.get('stop_price') or o.get('price')} "
                      f"[{o['status']}]")
            if not (s["positions"] or s["orders"]):
                print("no open positions or orders")
        elif act in ("preview", "open"):
            plan = mgr.preview(_request(args))
            print(f"[{banner}]\n{plan.summary()}")
            if act == "preview" or not plan.ok:
                return 0 if plan.ok else 1
            typed = _yes(plan.request.pair, f"\nPlace this {banner} trade on")
            plan, trade_id = mgr.open(_request(args), confirm=typed)
            print(f"done: trade #{trade_id}. Check it with: python -m backend.cli trade status")
        elif act == "tpsl":
            pair = risk.to_pair(args.pair)
            typed = _yes(pair, f"Set SL {args.sl or '-'} / TP {args.tp or '-'} on")
            if typed.strip().upper() != pair:
                raise TradeError("not confirmed")
            pos = mgr.set_tpsl(pair, stop_loss=args.sl, take_profit=args.tp)
            print(f"done. SL {pos.get('stop_loss_trigger')}  TP {pos.get('take_profit_trigger')}")
        elif act == "close":
            pair = risk.to_pair(args.pair)
            mgr.close(pair, confirm=_yes(pair, "Close at market"))
            print("exit sent")
        elif act == "cancel":
            if not _yes(args.pair, "Cancel order"):
                raise TradeError("not confirmed")
            mgr.cancel_order(args.pair)
            print("cancel sent")
        elif act == "panic":
            for line in mgr.panic(_ask("Type PANIC to cancel all orders, close all "
                                       "positions and block new trades: ")):
                print(line)
        elif act == "scan":
            from backend.service import ScreenerService
            from backend.trading import ideas

            settings = ideas.Settings.from_config(config.trading.get("setups"))
            svc = ScreenerService(config, refresh=False)
            coins = _ledger_coins(config, account) or None
            what = (f"the {len(coins)} recovery-ledger coins" if coins
                    else f"the top {settings.top} coins")
            while True:
                print(f"scanning {what} (places no orders)...", flush=True)
                try:
                    new = ideas.scan(mgr, ideas.find_setups(svc, settings.top, coins), settings)
                    for i in new:
                        print(f"#{i['id']} {i['coin']} {i['timeframe']} {i['pattern']}: "
                              f"{i['status'].upper()} - {i['reason']}", flush=True)
                    print(f"{len(new)} new setup(s). Ready ones: tap Place on the Trade page, "
                          "or `trade take ID`.", flush=True)
                except Exception as exc:         # keep scanning through a bad round
                    print(f"scan failed: {exc}", flush=True)
                if not args.every_min:
                    return 0
                _time.sleep(args.every_min * 60)
        elif act == "ideas":
            for i in reversed(mgr.store.ideas(args.n)):
                when = _time.strftime("%m-%d %H:%M", _time.localtime(i["ts_ms"] / 1000))
                print(f"#{i['id']} {when} {i['coin']} {i['timeframe']} {i['pattern']} "
                      f"SL {i['stop']:g} TP {i['target']:g}: {i['status'].upper()} "
                      f"- {i['reason']}")
        elif act == "take":
            from backend.trading import ideas

            settings = ideas.Settings.from_config(config.trading.get("setups"))
            idea = mgr.store.idea(int(args.pair))
            if idea is None:
                raise TradeError(f"no setup #{args.pair}")
            free = mgr.free_inr()
            if free is None:
                raise TradeError("no API keys")
            req = ideas.request_for(idea, free, settings)
            if args.margin:
                req.margin_inr = args.margin
            req.override = args.override
            plan = mgr.preview(req)
            print(f"[{banner}] setup #{idea['id']}: {idea['coin']} {idea['timeframe']} "
                  f"{idea['pattern']} ({idea['status']})\n{plan.summary()}")
            rr = ideas.rr_error(plan)
            if rr:
                print(f"  BLOCKED: {rr}")
            if not plan.ok or rr:
                return 1
            if not _yes(idea["pair"], f"Place this {banner} trade on"):
                raise TradeError("not confirmed")
            trade_id = ideas.place(mgr, idea["id"], settings, margin_inr=args.margin or None,
                                   override=args.override)
            print(f"done: trade #{trade_id}. Check it with: python -m backend.cli trade status")
        elif act == "propose":
            from backend.trading import ideas

            settings = ideas.Settings.from_config(config.trading.get("setups"))
            idea = ideas.propose(mgr, _request(args), timeframe=args.tf,
                                 why=args.why or "given by hand", settings=settings)
            print(f"[{banner}] setup #{idea['id']} {idea['coin']} {idea['side']}: "
                  f"{idea['status'].upper()} - {idea['reason']}")
            if idea["status"] == ideas.READY:
                print("sent to Telegram with a Place button (needs `trade bot` running), "
                      f"or: python -m backend.cli trade take {idea['id']} --account {account}")
            return 0 if idea["status"] == ideas.READY else 1
        elif act == "bot":
            known_ledgers = [a for a in known if _ledger_coins(config, a)]
            mgrs = ([mgr] if args.account else
                    [TradeManager.from_config(config, force_dry_run=args.dry_run, account=a)
                     for a in known])
            return _run_bot(config, mgrs, [account] if args.account else known_ledgers, args)
        elif act == "add":
            pair = risk.to_pair(args.pair)
            plan, trade, _ = mgr.preview_add(pair, risk_inr=args.risk, margin_inr=args.margin,
                                             override=args.override)
            print(f"[{banner}] add {(trade['adds'] or 0) + 1} to trade #{trade['id']}\n"
                  f"{plan.summary()}")
            if not plan.ok:
                return 1
            mgr.add(pair, _yes(pair, f"\nAdd this {banner} size to"), risk_inr=args.risk,
                    margin_inr=args.margin, override=args.override)
            print("done. Check it with: python -m backend.cli trade status")
        elif act in ("recovery", "recovery-init"):
            from pathlib import Path

            from backend.trading import recovery

            rc = config.trading.get("recovery") or {}
            path = recovery.ledger_path(
                str(Path(config.trading.get("db", "data_cache/trading.db")).parent), account)
            if act == "recovery-init":
                if path.exists():
                    raise TradeError(f"{path} already exists; edit it, or delete it to start over")
                print("reading the full spot trade history (reads only)...", flush=True)
                rows = recovery.seed(mgr.client, min_paid_usd=float(rc.get("min_paid_usd", 50)))
                recovery.save(path, rows)
                print(f"wrote {path}: {sum(r.status == 'active' for r in rows)} coins active, "
                      f"{sum(r.status == 'skip' for r in rows)} skipped (no buy found). "
                      "Edit paid_inr for coins bought elsewhere.")
            rows = recovery.load(path)
            if not rows:
                raise TradeError(f"no ledger yet: run `trade recovery-init --account {account}`")
            _print_ledger(recovery.ledger(mgr.client, rows,
                                          float(rc.get("cushion_pct", 1.5))), path)
        elif act == "resume":
            mgr.resume()
            print("new trades allowed again")
        elif act == "log":
            for e in reversed(mgr.store.events(args.n)):
                when = _time.strftime("%m-%d %H:%M:%S", _time.localtime(e["ts_ms"] / 1000))
                print(f"{when} {'ok ' if e['ok'] else 'ERR'} {e['action']}: "
                      f"{e['request']} -> {e['response'][:200]}")
        elif act in ("adopt", "trail-set"):
            from backend.trading import trailing
            from backend.trading.manager import check_trail

            check_trail(args.trail_pct, args.trail_candle)
            pair = risk.to_pair(args.pair)
            pos = mgr.position(pair)
            if pos is None:
                raise TradeError(f"no open {pair} position")
            s = trailing.Settings.from_config(config.trading.get("trailing"))
            side = "long" if float(pos["active_pos"]) > 0 else "short"
            px = mgr.last_price(pair)
            entry = float(pos["avg_price"])
            if args.trail_candle:
                minutes = trailing.CANDLE_MINUTES[args.trail_candle]
                c = trailing.last_closed(mgr.client.candles(pair, minutes, 6 * minutes * 60),
                                         minutes, int(_time.time() * 1000))
                first = c and trailing.next_stop_candle(side, candle=c, price=px,
                                                        current_stop=None, s=s)
                how = (f"a notch ({s.candle_buffer_pct:g}%) {'under' if side == 'long' else 'over'}"
                       f" the last closed CoinDCX {args.trail_candle} candle")
            else:
                first = trailing.next_stop_pct(side, pct=args.trail_pct, best=max(entry, px)
                                               if side == "long" else min(entry, px), price=px,
                                               current_stop=None, s=s)
                how = f"{args.trail_pct:g}% behind the best price"
            now_sl = float(pos.get("stop_loss_trigger") or 0)
            if first and now_sl and (first <= now_sl if side == "long" else first >= now_sl):
                nxt = f"the stop stays at {now_sl:g} until this rule gives a better one"
            elif first:
                vs = (first / entry - 1) * 100 * (1 if side == "long" else -1)
                nxt = f"the watcher's next stop: about {first:.6g} ({vs:+.2f}% vs entry)"
            else:
                nxt = "no closed candle yet"
            print(f"[{banner}] {pair} {side} {pos['active_pos']} @ {entry:g}, now {px:g}, "
                  f"SL {pos.get('stop_loss_trigger') or 'none'}, "
                  f"TP {pos.get('take_profit_trigger') or 'none'}\n"
                  f"  trail: {how}; it only moves in your favour. The target stays.\n"
                  f"  {nxt}")
            typed = _yes(pair, "Let the watcher trail it this way:")
            if act == "adopt":
                trade_id = mgr.adopt(pair, args.trail_pct, confirm=typed,
                                     trail_candle=args.trail_candle)
                print(f"done: trade #{trade_id}.", end=" ")
            else:
                if typed.strip().upper() != pair:
                    raise TradeError("not confirmed")
                mgr.set_trail(pair, trail_pct=args.trail_pct, trail_candle=args.trail_candle)
                print("done.", end=" ")
            print("Keep `trade watch` running; it moves the stop on its next round.")
        elif act in ("trail-on", "trail-off"):
            pair = risk.to_pair(args.pair)
            trade = mgr.store.latest_for_pair(pair)
            if trade is None:
                raise TradeError(f"no open {pair} trade opened by this tool")
            mgr.store.update_trade(trade["id"], trail=int(act == "trail-on"))
            print(f"{pair}: trailing stop {'on' if act == 'trail-on' else 'off'}")
        elif act in ("reconcile", "watch"):
            from backend.trading import trailing

            trail = trailing.Settings.from_config(config.trading.get("trailing"))
            # With no --account the watcher looks after every account in .env.
            mgrs = ([mgr] if args.account else
                    [TradeManager.from_config(config, force_dry_run=args.dry_run, account=a)
                     for a in known])
            print(f"[{'LIVE' if mgr.live else 'DRY RUN (nothing is sent)'}] watching "
                  f"{', '.join(m.account for m in mgrs)} every {args.every}s; trailing stop "
                  f"{'on' if trail.enabled else 'off'} - Ctrl+C to stop", flush=True)
            while True:
                for one in mgrs:
                    tag = "" if len(mgrs) == 1 else f"[{one.account}] "
                    try:                         # one account failing never stops the others
                        for m in one.reconcile() + trailing.run(one, trail):
                            print(tag + m, flush=True)
                    except Exception as exc:     # keep watching through a bad round
                        print(f"{tag}check failed: {exc}", flush=True)
                if act == "reconcile":
                    return 0
                _time.sleep(args.every)
    except TradeError as exc:
        print(f"refused: {exc}")
        return 1
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

    r = sub.add_parser("report",
                       help="multi-TF bullish confluence + VMC divergence report")
    r.add_argument("--coins", default=None, help="comma list, default = universe")
    r.add_argument("--base", default="USDT")
    r.add_argument("--timeframes", default=None,
                   help="comma list, default = 15m,4h,1d,1w")
    r.add_argument("--div-lookback", type=int, default=10,
                   help="divergence counts if within last N closed candles")
    r.add_argument("--all-bull", action="store_true",
                   help="only coins bullish on every selected timeframe")
    r.set_defaults(func=cmd_report)

    w = sub.add_parser("watch", help="run periodic alert scans (always-on)")
    w.add_argument("--interval", type=int, default=5, help="minutes between scans")
    w.add_argument("--presets", default=None, help="comma list, default = all")
    w.add_argument("--cooldown", type=float, default=3600.0)
    w.set_defaults(func=cmd_watch)

    a = sub.add_parser("alerts", help="check price / trendline / zone alerts on a loop")
    a.add_argument("--every", type=int, default=60, help="seconds between checks")
    a.add_argument("--once", action="store_true", help="check once and exit")
    a.set_defaults(func=cmd_alerts)

    j = sub.add_parser("journal", help="replay the paper trades and refresh the journal")
    j.add_argument("--csv", default="journal/trades.csv")
    j.add_argument("--md", default="journal/TRADE_JOURNAL.md")
    j.set_defaults(func=cmd_journal)

    u = sub.add_parser("setups", help="rank today's buy setups; --journal adds the picks")
    u.add_argument("--top", type=int, default=100, help="coins by market cap")
    u.add_argument("--n", type=int, default=5, help="picks of each kind")
    u.add_argument("--journal", action="store_true", help="append the picks to --csv")
    u.add_argument("--csv", default="journal/trades.csv")
    u.add_argument("--skip-days", type=int, default=3,
                   help="skip a coin/timeframe/pattern journaled this many days back")
    u.set_defaults(func=cmd_setups)

    sp = sub.add_parser("scalp", help="exhaustion scalps: big movers with fading momentum")
    sp.add_argument("--top", type=int, default=100, help="coins by market cap")
    sp.add_argument("--tf", default="15m", choices=["5m", "15m", "1h"])
    sp.add_argument("--min-move", type=float, default=8.0, help="24h move in %%")
    sp.add_argument("--min-score", type=int, default=3, help="confluence points needed")
    sp.add_argument("--journal", action="store_true", help="add the calls to --csv")
    sp.add_argument("--csv", default="journal/scalps.csv")
    sp.add_argument("--skip-hours", type=float, default=4.0,
                    help="skip a coin/side journaled this many hours back")
    sp.set_defaults(func=cmd_scalp)

    sj = sub.add_parser("scalp-journal", help="replay the scalp calls and refresh the journal")
    sj.add_argument("--csv", default="journal/scalps.csv")
    sj.add_argument("--md", default="journal/SCALP_JOURNAL.md")
    sj.set_defaults(func=cmd_scalp_journal)

    b = sub.add_parser("backtest", help="forward-return stats for a signal")
    b.add_argument("--coin", required=True)
    b.add_argument("--base", default="BTC")
    b.add_argument("--timeframe", default="1d")
    b.add_argument("--direction", default="bull", choices=["bull", "bear"])
    b.add_argument("--horizon", type=int, default=10)
    b.set_defaults(func=cmd_backtest)

    t = sub.add_parser("trade", help="CoinDCX INR futures: status, preview, open, add, "
                                     "tpsl, close, cancel, panic, resume, log, watch, "
                                     "recovery, propose, bot")
    t.add_argument("action", choices=["status", "preview", "open", "tpsl", "close", "cancel",
                                      "panic", "resume", "log", "reconcile", "watch",
                                      "scan", "ideas", "take", "trail-on", "trail-off",
                                      "adopt", "trail-set", "add", "recovery",
                                      "recovery-init", "propose", "bot"])
    t.add_argument("pair", nargs="?", default="",
                   help="coin or pair (BTC, B-BTC_USDT); order id for cancel")
    t.add_argument("side", nargs="?", choices=["long", "short"], default=None)
    t.add_argument("--sl", type=float, default=None, help="stop loss price (USDT)")
    t.add_argument("--tp", type=float, default=None, help="target price (USDT)")
    t.add_argument("--risk", type=float, default=0.0, help="INR to lose if the stop is hit")
    t.add_argument("--margin", type=float, default=0.0,
                   help="size by this INR margin instead of by --risk")
    t.add_argument("--lev", type=int, default=1, help="leverage")
    t.add_argument("--limit", type=float, default=None,
                   help="limit entry price; leave out for a market entry")
    t.add_argument("--every", type=int, default=30, help="watch: seconds between checks")
    t.add_argument("-n", type=int, default=30, help="log / ideas: how many rows")
    t.add_argument("--override", action="store_true",
                   help="break the gold-standard rules (10%% stop, 5%% margin, 5x) for "
                        "this one trade")
    t.add_argument("--account", default=None,
                   help="which CoinDCX account (default main; watch: all accounts)")
    t.add_argument("--dry-run", action="store_true",
                   help="send nothing, whatever trading.mode says")
    t.add_argument("--trail-pct", type=float, default=0.0,
                   help="adopt: keep the stop this %% behind the best price")
    t.add_argument("--trail-candle", default=None, choices=["1m", "5m", "15m", "1h"],
                   help="adopt / trail-set: keep the stop a notch under the last closed "
                        "CoinDCX candle of this size")
    t.add_argument("--every-min", type=int, default=0,
                   help="scan: repeat every N minutes (0 = once); bot: scan every N "
                        "minutes (default 15)")
    t.add_argument("--tf", default="15m", help="propose: the setup's timeframe")
    t.add_argument("--why", default="", help="propose: the reason, shown in Telegram")
    t.set_defaults(func=cmd_trade)

    args = parser.parse_args(argv)
    if getattr(args, "action", None) == "propose" and not (
            args.pair and args.side and args.sl and args.tp and (args.risk or args.margin)):
        parser.error("propose needs: PAIR long|short --sl PRICE --tp PRICE --risk INR "
                     "[--lev] [--limit] [--tf 15m] [--why TEXT]")
    if getattr(args, "action", None) in ("preview", "open") and not (
            args.pair and args.side and args.sl and (args.risk or args.margin)):
        parser.error("preview/open need: PAIR long|short --sl PRICE --risk INR|--margin INR [--tp] "
                     "[--lev] [--limit]")
    if getattr(args, "action", None) == "add" and not (args.pair and (args.risk or args.margin)):
        parser.error("add needs: PAIR --risk INR|--margin INR (same stop and target as the trade)")
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
