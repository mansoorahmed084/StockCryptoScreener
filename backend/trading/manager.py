"""Open, protect, change and close INR-margined CoinDCX futures trades.

Safety rules the manager enforces:

* Nothing is sent unless ``trading.mode`` is ``live``. In ``dry_run`` every
  write is logged as "not sent" and the exchange is only read.
* Every trade is re-sized and re-checked against live prices right before it
  is sent (risk.build_plan); a plan with any error is refused.
* Every entry carries a stop loss. After a fill the stop is attached and then
  read back from the position. If the exchange does not show it, the manager
  tries once more and then closes the position at market rather than leave it
  unprotected.
* A write that times out is never blindly re-sent; the exchange is re-read.
* ``panic`` cancels every open order, closes every position and blocks new
  trades until ``resume``.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.trading import risk, tgfmt
from backend.trading.client import MAIN, CoinDcxError, FuturesClient, UnknownOutcome
from backend.trading.store import CLOSED, FAILED, OPEN, PENDING, TradeStore

log = logging.getLogger(__name__)

LIVE, DRY_RUN = "live", "dry_run"
HALT_FLAG = "halted"
SL_TYPES = ("stop_market", "stop_limit")
TP_TYPES = ("take_profit_market", "take_profit_limit")
MAX_ADDS = 2            # adds to one winning trade


class TradeError(Exception):
    pass


def _f(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


TRAIL_CANDLES = ("1m", "5m", "15m", "1h")


def account_db(path: str, account: str) -> str:
    """Each account keeps its own records: trading.db for main, trading_<name>.db else."""
    if account == MAIN:
        return path
    p = Path(path)
    return str(p.with_name(f"{p.stem}_{account}{p.suffix}"))


def account_limits(trading: dict, account: str = MAIN) -> risk.Limits:
    """``trading.limits``, with any ``trading.accounts.<name>.limits`` laid over it."""
    own = ((trading.get("accounts") or {}).get(account) or {}).get("limits") or {}
    return risk.Limits.from_config({**(trading.get("limits") or {}), **own})


def check_trail(trail_pct: float, trail_candle: str | None) -> None:
    if bool(trail_pct) == bool(trail_candle):
        raise TradeError("give one trail: a percent (--trail-pct) or a candle (--trail-candle)")
    if trail_candle and trail_candle not in TRAIL_CANDLES:
        raise TradeError(f"--trail-candle must be one of {', '.join(TRAIL_CANDLES)}")
    if trail_pct and not 0 < trail_pct <= risk.MAX_STOP_PCT:
        raise TradeError(f"trail must be above 0% and at most {risk.MAX_STOP_PCT:g}%")


def position_side(pos: dict) -> str:
    return risk.LONG if _f(pos.get("active_pos")) > 0 else risk.SHORT


class TradeManager:
    def __init__(self, client: FuturesClient, store: TradeStore, limits: risk.Limits, *,
                 mode: str = DRY_RUN, notify: Callable[[str], Any] | None = None,
                 fill_timeout_s: float = 20.0, poll_s: float = 1.0,
                 close_unprotected: bool = False,
                 sleep: Callable[[float], None] = time.sleep, account: str = MAIN):
        if mode not in (LIVE, DRY_RUN):
            raise ValueError(f"trading.mode must be {LIVE!r} or {DRY_RUN!r}")
        self.client = client
        self.store = store
        self.limits = limits
        self.mode = mode
        self._notify = notify or (lambda text: None)
        self.fill_timeout_s = fill_timeout_s
        self.poll_s = poll_s
        self.close_unprotected = close_unprotected
        self.account = account
        self._sleep = sleep
        # The bot handles button taps on one thread and watches on another: one at a time.
        self.lock = threading.RLock()
        self._instruments: dict[str, risk.Instrument] = {}
        self._warned_unprotected: set[str] = set()

    @classmethod
    def from_config(cls, config, *, force_dry_run: bool = False,
                    account: str = MAIN) -> "TradeManager":
        from backend.alerts.telegram import notifier_from_env

        t = config.trading
        return cls(FuturesClient.from_env(account),
                   TradeStore(account_db(t.get("db", "data_cache/trading.db"), account)),
                   account_limits(t, account),
                   mode=DRY_RUN if force_dry_run else str(t.get("mode", DRY_RUN)),
                   notify=notifier_from_env().send_html,
                   fill_timeout_s=float(t.get("fill_timeout_s", 20)),
                   close_unprotected=bool(t.get("close_unprotected", False)),
                   account=account)

    @property
    def live(self) -> bool:
        return self.mode == LIVE

    @property
    def halted(self) -> bool:
        return self.store.flag(HALT_FLAG) == "1"

    def notify(self, text: str, *, card: bool = False) -> None:
        """A Telegram message (HTML). ``card``: a ready tgfmt card; any other
        text gets the small bot header and is escaped."""
        log.info(tgfmt.strip(text) if card else text)
        try:
            self._notify(text if card else tgfmt.notice(text, self.account))
        except Exception as exc:              # a failed message must not stop trading logic
            log.warning("notify failed: %s", exc)

    def _open_card(self, trade_id: int | None, ts: Any = None) -> None:
        """The OPEN card of a filled, protected trade. Never raises: a message
        must not stop trading logic."""
        try:
            self._open_card_send(trade_id, ts)
        except Exception as exc:
            log.warning("OPEN message failed: %s", exc)

    def _open_card_send(self, trade_id: int | None, ts: Any) -> None:
        t = self.store.trade(trade_id) if trade_id else None
        if t is None:
            return
        entry, tp, sl = _f(t["entry"]), _f(t["take_profit"]), _f(t["stop_loss"])
        rr = reward = None
        if tp and entry and sl and entry != sl and t["risk_inr"]:
            rr = abs(tp - entry) / abs(entry - sl)
            reward = rr * _f(t["risk_inr"])
        self.notify(tgfmt.open_card(t, self.account, self.live, ts, reward, rr), card=True)

    def realized_inr(self, position_id: str | None, since_ms: float, *,
                     tries: int = 1, wait_s: float = 2.0) -> float | None:
        """Booked profit/loss of a position since ``since_ms``: trades, funding
        and fees from the futures wallet ledger. None while nothing but funding
        is booked (``tries`` re-reads it ``wait_s`` apart: a close is booked a
        moment after it fills)."""
        if not position_id or not self.client.has_keys:
            return None
        for i in range(max(1, tries)):
            try:
                rows = [t for t in self.client.transactions(1)
                        if str(t.get("position_id")) == str(position_id)
                        and _f(t.get("created_at")) >= since_ms]
            except Exception as exc:
                log.warning("reading the ledger failed: %s", exc)
                return None
            if any(t.get("stage") != "funding" for t in rows):
                return sum(_f(t.get("amount")) - _f(t.get("fee_amount")) for t in rows)
            if i + 1 < tries:
                self._sleep(wait_s)
        return None

    def _exit_fill(self, pair: str, since_ms: float) -> tuple[float | None, str]:
        """(price, why) of the order that closed ``pair`` after ``since_ms``,
        when CoinDCX lists it; (None, '') otherwise."""
        try:
            done = [o for o in self.client.orders("filled")
                    if o.get("pair") == pair and _f(o.get("updated_at")) >= since_ms]
        except Exception:
            return None, ""
        if not done:
            return None, ""
        o = max(done, key=lambda o: _f(o.get("updated_at")))
        kind = str(o.get("order_type", ""))
        why = ("stop loss hit" if "stop" in kind else "target hit" if "take_profit" in kind
               else "closed at market")
        return (_f(o.get("avg_price")) or _f(o.get("price")) or None), why

    def closed_card(self, *, side: str, pair: str, entry: float, position_id: str | None,
                    since_ms: float, risk_inr: float | None, why: str,
                    trade_id: int | None = None, tries: int = 1) -> None:
        """Send the CLOSED card: booked profit/loss from the ledger, the exit
        price from the closing order (else the last price). Never raises."""
        try:
            self._closed_card_send(side, pair, entry, position_id, since_ms, risk_inr, why,
                                   trade_id, tries)
        except Exception as exc:
            log.warning("CLOSED message failed: %s", exc)

    def _closed_card_send(self, side, pair, entry, position_id, since_ms, risk_inr, why,
                          trade_id, tries) -> None:
        pnl = self.realized_inr(position_id, since_ms, tries=tries)
        exit_px, fill_why = self._exit_fill(pair, since_ms)
        if exit_px is None:
            try:
                exit_px = self.last_price(pair) or None
            except Exception:
                exit_px = None
        self.notify(tgfmt.closed_card(side=side, pair=pair, entry=entry, exit_px=exit_px,
                                      pnl_inr=pnl, risk_inr=risk_inr, why=fill_why or why,
                                      trade_id=trade_id, account=self.account), card=True)

    # -- market data -------------------------------------------------------------
    def instrument(self, pair: str) -> risk.Instrument:
        if pair not in self._instruments:
            self._instruments[pair] = risk.Instrument.from_api(self.client.instrument(pair))
        return self._instruments[pair]

    def last_price(self, pair: str) -> float:
        p = self.client.prices().get(pair) or {}
        return _f(p.get("ls")) or _f(p.get("mp"))

    def rate(self) -> tuple[float, str | None]:
        """(INR per USDT, warning). The futures rate needs keys; without them
        the INR spot price of USDT stands in for previews."""
        if self.client.has_keys:
            return self.client.conversion_rate(), None
        return self.client.spot_usdt_inr(), ("no API keys: sized with the spot USDT/INR "
                                             "price, not the futures rate")

    # -- account ---------------------------------------------------------------
    def positions(self) -> list[dict]:
        if not self.client.has_keys:
            return []
        return [p for p in self.client.positions() if _f(p.get("active_pos")) != 0]

    def position(self, pair: str) -> dict | None:
        rows = [p for p in self.client.positions([pair])
                if p.get("pair") == pair and _f(p.get("active_pos")) != 0]
        return rows[0] if rows else None

    def free_inr(self) -> float | None:
        """Unused INR in the futures wallet (CoinDCX's ``balance``), or None without keys."""
        if not self.client.has_keys:
            return None
        for w in self.client.wallets():
            if w.get("currency_short_name") == "INR":
                return _f(w.get("balance"))
        return 0.0

    def loss_today_inr(self) -> float:
        if not self.client.has_keys:
            return 0.0
        start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0,
                                                         microsecond=0)
        start_ms = start.timestamp() * 1000
        pnl = 0.0
        for page in range(1, 21):
            rows = self.client.transactions(page)
            pnl += sum(_f(t.get("amount")) - _f(t.get("fee_amount"))
                       for t in rows if _f(t.get("created_at")) >= start_ms)
            if len(rows) < 100 or min(_f(t.get("created_at")) for t in rows) < start_ms:
                break
        return max(0.0, -pnl)

    def status(self) -> dict:
        out: dict[str, Any] = {"mode": self.mode, "halted": self.halted,
                               "keys": self.client.has_keys}
        if self.client.has_keys:
            out["wallets"] = self.client.wallets()
            out["positions"] = self.positions()
            out["orders"] = self.client.orders()
            out["loss_today_inr"] = self.loss_today_inr()
        return out

    # -- writes go through here --------------------------------------------------
    def _write(self, action: str, fn: Callable[..., Any], *args, trade_id: int | None = None,
               **kwargs) -> Any:
        request = {"args": args, **kwargs}
        if not self.live:
            self.store.log(action, request, "dry run: not sent", True, trade_id)
            return None
        try:
            resp = fn(*args, **kwargs)
        except Exception as exc:
            self.store.log(action, request, f"{type(exc).__name__}: {exc}", False, trade_id)
            raise
        self.store.log(action, request, resp, True, trade_id)
        return resp

    # -- plan and open ------------------------------------------------------------
    def preview(self, req: risk.TradeRequest) -> risk.Plan:
        req.pair = risk.to_pair(req.pair)
        inst = self.instrument(req.pair)
        rate, rate_warning = self.rate()
        held = self.positions()
        plan = risk.build_plan(
            req, inst, last_price=self.last_price(req.pair), rate=rate, limits=self.limits,
            open_positions=len(held), has_position=any(p["pair"] == req.pair for p in held),
            loss_today_inr=self.loss_today_inr(), free_inr=self.free_inr())
        if rate_warning:
            plan.warnings.append(rate_warning)
        if self.halted:
            plan.errors.append("trading is halted (panic); run `trade resume` first")
        if self.live and not self.client.has_keys:
            plan.errors.append("live mode needs COINDCX_API_KEY and COINDCX_API_SECRET in .env")
        return plan

    def open(self, req: risk.TradeRequest, confirm: str) -> tuple[risk.Plan, int]:
        """Place the entry and, once filled, the stop loss and target.

        ``confirm`` must be the pair name typed by the person placing the trade.
        """
        plan = self.preview(req)
        if confirm.strip().upper() != plan.request.pair:
            raise TradeError(f"not confirmed: type {plan.request.pair} to place this trade")
        if not plan.ok:
            raise TradeError("; ".join(plan.errors))

        pair = plan.request.pair
        trade_id = self.store.add_trade(
            mode=self.mode, pair=pair, side=req.side, entry_type=req.entry_type,
            entry=plan.entry, qty=plan.qty, leverage=req.leverage, stop_loss=plan.stop_loss,
            initial_stop=plan.stop_loss,
            take_profit=plan.take_profit, risk_inr=plan.risk_inr, margin_inr=plan.margin_inr,
            status=PENDING, note="rules overridden" if req.override else "")

        order = {"side": plan.order_side, "pair": pair, "total_quantity": plan.qty,
                 "leverage": req.leverage, "notification": "email_notification"}
        if req.entry_type == risk.LIMIT:
            order.update(order_type="limit_order", price=plan.entry,
                         time_in_force="good_till_cancel")
        else:
            order["order_type"] = "market_order"

        try:
            self._write("update_leverage", self.client.update_leverage, pair, req.leverage,
                        trade_id=trade_id)
            resp = self._write("create_order", self.client.create_order, order,
                               trade_id=trade_id)
        except UnknownOutcome:
            resp = self._find_entry(pair)
            if resp is None:
                self.store.update_trade(trade_id, status=FAILED,
                                        note="entry timed out and nothing reached the exchange")
                raise TradeError("the order timed out and is not on the exchange; "
                                 "nothing was opened")
        except CoinDcxError as exc:
            self.store.update_trade(trade_id, status=FAILED, note=exc.message)
            raise TradeError(f"CoinDCX refused the order: {exc.message}") from exc

        if not self.live:
            self.store.update_trade(trade_id, status="dry_run",
                                    note="dry run: nothing was sent")
            return plan, trade_id

        self.store.update_trade(trade_id, order_id=str((resp or {}).get("id", "")))
        if req.entry_type != risk.MARKET:
            self.notify(tgfmt.card(
                tgfmt.head("⏳", f"ORDER PLACED {req.side.upper()} {tgfmt.coin(pair)}",
                           self.account), None,
                [tgfmt.risk_line(plan.risk_inr, plan.stop_loss, plan.entry),
                 tgfmt.reward_line(plan.reward_inr, plan.take_profit, plan.entry, plan.rr)],
                [f"Limit {tgfmt.px(plan.entry)} · waits for a fill · trade #{trade_id}"]),
                card=True)
        if req.entry_type == risk.MARKET:
            pos = self._wait_for_position(pair)
            if pos is None:
                self.store.update_trade(trade_id, note="no fill seen yet; the watcher will "
                                                      "attach SL/TP when it fills")
                self.notify(f"{pair}: market order sent but no position seen after "
                            f"{self.fill_timeout_s:.0f}s. Run `trade reconcile`.")
            else:
                self._protect(trade_id, pos, plan.stop_loss, plan.take_profit, announce=True)
        return plan, trade_id

    # -- add to a winner ---------------------------------------------------------------
    def preview_add(self, pair: str, *, risk_inr: float = 0.0, margin_inr: float = 0.0,
                    override: bool = False) -> tuple[risk.Plan, dict, dict]:
        """Plan an add to an open trade of this tool. Allowed only once its stop is at
        or past the position's average price, so the old part can no longer lose; the
        add is sized and checked like a new trade, at the same stop and target."""
        pair = risk.to_pair(pair)
        trade = self.store.latest_for_pair(pair, (OPEN,))
        if trade is None:
            raise TradeError(f"no open {pair} trade opened by this tool")
        if (trade["adds"] or 0) >= MAX_ADDS:
            raise TradeError(f"{pair} already has {MAX_ADDS} adds")
        pos = self.position(pair)
        if pos is None:
            raise TradeError(f"no open {pair} position")
        side = position_side(pos)
        avg, sl = _f(pos.get("avg_price")), _f(pos.get("stop_loss_trigger"))
        if not sl:
            raise TradeError(f"{pair} has no stop loss on the exchange")
        if side == risk.LONG and sl < avg or side == risk.SHORT and sl > avg:
            raise TradeError(f"the stop ({sl:g}) is not at breakeven yet (average {avg:g}); "
                             "add only once the trade cannot lose")
        req = risk.TradeRequest(pair=pair, side=side, stop_loss=sl, risk_inr=risk_inr,
                                leverage=int(_f(pos.get("leverage"))) or 1,
                                take_profit=_f(pos.get("take_profit_trigger")) or None,
                                margin_inr=margin_inr, override=override)
        inst = self.instrument(pair)
        rate, _ = self.rate()
        held = self.positions()
        plan = risk.build_plan(
            req, inst, last_price=self.last_price(pair), rate=rate, limits=self.limits,
            open_positions=len(held) - 1, loss_today_inr=self.loss_today_inr(),
            free_inr=self.free_inr())
        if self.halted:
            plan.errors.append("trading is halted (panic); run `trade resume` first")
        return plan, trade, pos

    def add(self, pair: str, confirm: str, *, risk_inr: float = 0.0, margin_inr: float = 0.0,
            override: bool = False) -> risk.Plan:
        """Add to a winning trade at market, then put the stop (and target) back on the
        whole, bigger position."""
        plan, trade, pos = self.preview_add(pair, risk_inr=risk_inr, margin_inr=margin_inr,
                                            override=override)
        pair = plan.request.pair
        if confirm.strip().upper() != pair:
            raise TradeError(f"not confirmed: type {pair} to add to this trade")
        if not plan.ok:
            raise TradeError("; ".join(plan.errors))
        before = abs(_f(pos.get("active_pos")))
        order = {"side": plan.order_side, "pair": pair, "total_quantity": plan.qty,
                 "leverage": plan.request.leverage, "order_type": "market_order",
                 "notification": "email_notification"}
        try:
            self._write("create_order", self.client.create_order, order, trade_id=trade["id"])
        except UnknownOutcome:
            pass                                 # re-read below; never sent twice
        except CoinDcxError as exc:
            raise TradeError(f"CoinDCX refused the add: {exc.message}") from exc
        if not self.live:
            return plan
        deadline = time.monotonic() + self.fill_timeout_s
        while True:
            now = self.position(pair)
            if now is None or abs(_f(now.get("active_pos"))) > before + 1e-12:
                break
            if time.monotonic() >= deadline:
                self.notify(f"{pair}: add sent but no fill seen after {self.fill_timeout_s:.0f}s;"
                            " the stop stays as it was. Check `trade status`.")
                return plan
            self._sleep(self.poll_s)
        if now is None:
            return plan
        n = (trade["adds"] or 0) + 1
        self.store.update_trade(trade["id"], adds=n, qty=abs(_f(now.get("active_pos"))),
                                note=f"{trade['note'] or ''}; add {n}: +{plan.qty:g} @ "
                                     f"{plan.entry:g}".lstrip("; "))
        # Put the stop and target on the whole position again.
        self.set_tpsl(pair, stop_loss=plan.stop_loss, take_profit=plan.take_profit)
        self.notify(f"{pair}: added {plan.qty:g} (add {n}); stop {plan.stop_loss:g} "
                    "now covers the whole position")
        return plan

    def _find_entry(self, pair: str) -> dict | None:
        pos = self.position(pair)
        if pos:
            return {"id": "", "position": pos}
        for o in self.client.orders("open,partially_filled"):
            if o.get("pair") == pair:
                return o
        return None

    def _wait_for_position(self, pair: str) -> dict | None:
        deadline = time.monotonic() + self.fill_timeout_s
        while True:
            pos = self.position(pair)
            if pos is not None or time.monotonic() >= deadline:
                return pos
            self._sleep(self.poll_s)

    # -- stop loss and target ---------------------------------------------------------
    def _protect(self, trade_id: int | None, pos: dict, stop_loss: float,
                 take_profit: float | None, announce: bool = False) -> bool:
        """Attach SL/TP to a filled position and read them back. Closes the
        position if the stop loss cannot be confirmed."""
        pair, pos_id = pos["pair"], pos["id"]
        for attempt in range(2):
            try:
                self._write("create_tpsl", self.client.create_tpsl, pos_id,
                            trade_id=trade_id, stop_loss=stop_loss,
                            take_profit=take_profit if attempt == 0 else None)
            except (CoinDcxError, UnknownOutcome) as exc:
                log.warning("create_tpsl failed on %s: %s", pair, exc)
            fresh = self.position(pair)
            if fresh is None:           # already closed (e.g. stop hit instantly)
                if trade_id:
                    self.store.update_trade(trade_id, status=CLOSED,
                                            note="position closed right after the fill")
                return True
            if _f(fresh.get("stop_loss_trigger")) > 0:
                if trade_id:
                    self.store.update_trade(trade_id, status=OPEN, position_id=pos_id,
                                            entry=_f(fresh.get("avg_price")) or None)
                if announce:
                    self._open_card(trade_id)
                if take_profit and not _f(fresh.get("take_profit_trigger")):
                    self.notify(f"{pair}: stop loss set at {fresh['stop_loss_trigger']} but the "
                                "target was not accepted; set it again with `trade tpsl`")
                elif not announce:
                    self.notify(f"{pair}: protected. SL {fresh['stop_loss_trigger']}"
                                f"  TP {fresh.get('take_profit_trigger') or 'none'}")
                return True
        # Could not confirm a stop loss: do not leave the position naked.
        try:
            self._write("exit_position", self.client.exit_position, pos_id, trade_id=trade_id)
            note = "stop loss not accepted by CoinDCX; position closed at market"
        except Exception as exc:
            note = f"stop loss not accepted AND the exit failed ({exc}); CLOSE IT BY HAND"
        if trade_id:
            self.store.update_trade(trade_id, status=FAILED, position_id=pos_id, note=note)
        self.notify(f"{pair}: {note}")
        return False

    def set_tpsl(self, pair: str, *, stop_loss: float | None = None,
                 take_profit: float | None = None) -> dict:
        """Move the stop loss and/or target of an open position."""
        pair = risk.to_pair(pair)
        if stop_loss is None and take_profit is None:
            raise TradeError("give a new stop loss, a new target, or both")
        pos = self.position(pair)
        if pos is None:
            raise TradeError(f"no open {pair} position")
        inst = self.instrument(pair)
        stop_loss = risk.round_step(stop_loss, inst.price_step) if stop_loss else None
        take_profit = risk.round_step(take_profit, inst.price_step) if take_profit else None
        errors = risk.check_stop_move(position_side(pos), stop_loss=stop_loss,
                                      take_profit=take_profit, mark=self.last_price(pair))
        if errors:
            raise TradeError("; ".join(errors))

        trade = self.store.latest_for_pair(pair)
        trade_id = trade["id"] if trade else None
        old_sl = _f(pos.get("stop_loss_trigger")) or None
        old_tp = _f(pos.get("take_profit_trigger")) or None
        tpsl = [o for o in self.client.orders("untriggered")
                if o.get("pair") == pair and o.get("stage") == "tpsl_exit"]

        def cancel(types: tuple[str, ...]) -> None:
            for o in tpsl:
                if o.get("order_type") in types:
                    self._write("cancel_order", self.client.cancel_order, o["id"],
                                trade_id=trade_id)

        if take_profit is not None:
            cancel(TP_TYPES)
            self._write("create_tpsl", self.client.create_tpsl, pos["id"], trade_id=trade_id,
                        take_profit=take_profit)
        if stop_loss is not None:
            cancel(SL_TYPES)
            # SL alone first; if it does not show, send it with the target too (CoinDCX
            # sets the stop and only refuses the target leg when one already exists).
            tries = [dict(stop_loss=stop_loss)]
            tp_now = take_profit or old_tp
            if tp_now:
                tries.append(dict(stop_loss=stop_loss, take_profit=tp_now))
            for legs in tries:
                try:
                    self._write("create_tpsl", self.client.create_tpsl, pos["id"],
                                trade_id=trade_id, **legs)
                except (CoinDcxError, UnknownOutcome) as exc:
                    log.warning("new stop loss refused on %s: %s", pair, exc)
                if not self.live:
                    break
                check = self.position(pair)
                if check is None or _f(check.get("stop_loss_trigger")):
                    break
        if not self.live:
            return pos

        fresh = self.position(pair)
        if fresh is not None and stop_loss is not None and not _f(fresh.get("stop_loss_trigger")):
            # The new stop was refused after the old one was cancelled: put a stop back.
            self._protect(trade_id, fresh, old_sl or stop_loss, None)
            raise TradeError(f"CoinDCX refused the new stop loss; "
                             f"{'restored the old one' if old_sl else 'protection re-applied'}")
        if trade_id and fresh is not None:
            self.store.update_trade(trade_id,
                                    stop_loss=_f(fresh.get("stop_loss_trigger")) or old_sl,
                                    take_profit=_f(fresh.get("take_profit_trigger")) or old_tp)
        return fresh or {}

    def adopt(self, pair: str, trail_pct: float, confirm: str,
              trail_candle: str | None = None) -> int:
        """Let the watcher trail a position opened by hand: ``trail_pct``% behind its
        best price, or under the last closed ``trail_candle`` candle. Sends nothing
        itself; the watcher sets and moves the stop."""
        pair = risk.to_pair(pair)
        if confirm.strip().upper() != pair:
            raise TradeError(f"not confirmed: type {pair} to hand this position to the watcher")
        check_trail(trail_pct, trail_candle)
        if not self.live:
            raise TradeError("adopting needs live mode (the watcher trails live trades only)")
        pos = self.position(pair)
        if pos is None:
            raise TradeError(f"no open {pair} position")
        if self.store.latest_for_pair(pair, (PENDING, OPEN)):
            raise TradeError(f"{pair} is already managed by this tool")
        entry = _f(pos.get("avg_price"))
        return self.store.add_trade(
            mode=LIVE, pair=pair, side=position_side(pos), entry_type="adopted",
            entry=entry, qty=abs(_f(pos.get("active_pos"))), leverage=int(_f(pos.get("leverage"))),
            stop_loss=_f(pos.get("stop_loss_trigger")) or None,
            take_profit=_f(pos.get("take_profit_trigger")) or None,
            position_id=pos["id"], status=OPEN, trail=1, trail_pct=trail_pct or None,
            trail_candle=trail_candle,
            best_price=max(entry, self.last_price(pair)) if position_side(pos) == risk.LONG
            else min(entry, self.last_price(pair)),
            note="adopted (opened by hand); trailing "
                 + (f"under the last closed {trail_candle} candle" if trail_candle
                    else f"{trail_pct:g}% behind best"))

    def set_trail(self, pair: str, *, trail_pct: float = 0.0,
                  trail_candle: str | None = None) -> None:
        """Change how an open trade's stop is trailed (sends nothing itself)."""
        pair = risk.to_pair(pair)
        check_trail(trail_pct, trail_candle)
        trade = self.store.latest_for_pair(pair, (OPEN,))
        if trade is None:
            raise TradeError(f"no open {pair} trade managed by this tool")
        how = (f"under the last closed {trail_candle} candle" if trail_candle
               else f"{trail_pct:g}% behind best")
        note = trade["note"] or ""
        note = (note.split("; trailing")[0] if "; trailing" in note else note) or "trailing"
        self.store.update_trade(trade["id"], trail=1, trail_pct=trail_pct or None,
                                trail_candle=trail_candle,
                                note=f"{note}; trailing {how}" if note != "trailing"
                                else f"trailing {how}")

    # -- close and cancel ----------------------------------------------------------
    def close(self, pair: str, confirm: str, why: str = "closed by you") -> None:
        pair = risk.to_pair(pair)
        if confirm.strip().upper() != pair:
            raise TradeError(f"not confirmed: type {pair} to close this position")
        pos = self.position(pair)
        if pos is None:
            raise TradeError(f"no open {pair} position")
        trade = self.store.latest_for_pair(pair)
        trade_id = trade["id"] if trade else None
        started = time.time() * 1000
        self._write("exit_position", self.client.exit_position, pos["id"], trade_id=trade_id)
        try:
            self._write("cancel_position_orders", self.client.cancel_position_orders,
                        pos["id"], trade_id=trade_id)
        except Exception as exc:
            log.warning("cancelling leftover orders on %s failed: %s", pair, exc)
        if trade_id and self.live:
            self.store.update_trade(trade_id, status=CLOSED, note=why)
        if self.live:
            # a bot trade counts from its open; a position the bot did not
            # open, only from this close (not its whole funding history)
            since = trade["created_ms"] if trade else started - 60_000
            self.closed_card(side=position_side(pos), pair=pair, entry=_f(pos.get("avg_price")),
                             position_id=pos.get("id"), since_ms=since,
                             risk_inr=trade["risk_inr"] if trade else None, why=why,
                             trade_id=trade_id, tries=3)

    def cancel_order(self, order_id: str) -> None:
        self._write("cancel_order", self.client.cancel_order, order_id)
        if self.live:
            for t in self.store.trades(PENDING):
                if t["order_id"] == order_id:
                    self.store.update_trade(t["id"], status=CLOSED, note="entry cancelled")

    def panic(self, confirm: str) -> list[str]:
        """Block new trades, cancel every open order and close every position."""
        if confirm != "PANIC":
            raise TradeError("not confirmed: type PANIC")
        self.store.set_flag(HALT_FLAG, "1")
        done = []
        try:
            self._write("cancel_all_orders", self.client.cancel_all_orders)
            done.append("cancelled all open orders")
        except Exception as exc:
            done.append(f"cancel all orders FAILED: {exc}")
        for pos in self.positions():
            try:
                self._write("exit_position", self.client.exit_position, pos["id"])
                done.append(f"closed {pos['pair']}")
            except Exception as exc:
                done.append(f"closing {pos['pair']} FAILED: {exc} - close it by hand")
        self.notify("PANIC: " + "; ".join(done or ["nothing was open"]))
        return done

    def resume(self) -> None:
        self.store.set_flag(HALT_FLAG, "0")

    # -- watcher ---------------------------------------------------------------
    def reconcile(self) -> list[str]:
        """Bring the records in line with the exchange; protect filled entries.

        Run every ~30 s by ``trade watch``. SL/TP already on the exchange keep
        working if this stops; the watcher only handles limit fills, closed
        trades and positions that have no stop loss.
        """
        if not (self.live and self.client.has_keys):
            return []
        msgs: list[str] = []          # what happened, for the log
        notes: list[str] = []         # plain messages for Telegram (cards go at once)
        held = {p["pair"]: p for p in self.positions()}
        open_orders = {o.get("id") for o in self.client.orders("open,partially_filled")}

        for t in self.store.trades(PENDING):
            if t["mode"] != LIVE:
                continue
            pos = held.get(t["pair"])
            if pos is not None:
                if not _f(pos.get("stop_loss_trigger")):
                    self._protect(t["id"], pos, t["stop_loss"], t["take_profit"], announce=True)
                    msgs.append(f"{t['pair']}: entry filled; SL/TP attached")
                else:
                    self.store.update_trade(t["id"], status=OPEN, position_id=pos["id"])
            elif t["order_id"] and t["order_id"] not in open_orders:
                self.store.update_trade(t["id"], status=CLOSED,
                                        note="entry order is gone (cancelled or rejected)")
                msgs.append(f"{t['pair']}: entry order is no longer open")
                notes.append(msgs[-1])

        for t in self.store.trades(OPEN):
            if t["mode"] == LIVE and t["pair"] not in held:
                self.store.update_trade(t["id"], status=CLOSED,
                                        note="position closed (stop, target or by hand)")
                msgs.append(f"{t['pair']}: position closed")
                self.closed_card(side=t["side"], pair=t["pair"], entry=_f(t["entry"]),
                                 position_id=t["position_id"], since_ms=t["created_ms"],
                                 risk_inr=t["risk_inr"], trade_id=t["id"],
                                 why="stop, target, or closed outside the bot")

        known = {t["pair"] for t in self.store.trades(PENDING) + self.store.trades(OPEN)}
        unprotected = {pair for pair, pos in held.items()
                       if not _f(pos.get("stop_loss_trigger")) and pair not in known}
        self._warned_unprotected &= unprotected
        today = dt.datetime.now(tgfmt.IST).strftime("%Y-%m-%d")
        for pair in sorted(unprotected - self._warned_unprotected):
            if self.close_unprotected:
                self._write("exit_position", self.client.exit_position, held[pair]["id"])
                msgs.append(f"{pair}: had no stop loss; closed (trading.close_unprotected)")
                notes.append(msgs[-1])
                continue
            self._warned_unprotected.add(pair)
            msgs.append(f"{pair}: open with NO stop loss")
            # at most once a day per coin, also across bot restarts
            if self.store.flag(f"nostop_warned:{pair}") == today:
                continue
            self.store.set_flag(f"nostop_warned:{pair}", today)
            pos = held[pair]
            self.notify(tgfmt.warn_card(
                f"NO STOP LOSS {position_side(pos).upper()} {tgfmt.coin(pair)}",
                [f"Entry {tgfmt.px(_f(pos.get('avg_price')))}, now "
                 f"{tgfmt.px(_f(pos.get('mark_price')))}, liquidation "
                 f"{tgfmt.px(_f(pos.get('liquidation_price')))}",
                 "Set a stop in the CoinDCX app, or: python -m backend.cli trade tpsl "
                 f"{pair} --sl PRICE",
                 "Reminder once a day." + (" Protected coin: the bot never closes it."
                                           if risk.owner_coin(pair) else "")],
                self.account), card=True)
        for m in notes:
            self.notify(m)
        return msgs
