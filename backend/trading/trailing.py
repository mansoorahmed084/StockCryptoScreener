"""Trailing stop loss, run by the watcher (CoinDCX has none of its own).

R is the trade's first risk: the distance from entry to the stop it was
opened with. Once price has gone ``activate_r`` R into profit, the stop moves
to breakeven (entry plus a small buffer for fees). After that it follows the
best price seen, ``trail_r`` R behind it. It only ever moves in the trade's
favour, and only by at least ``min_step_r`` R at a time, so CoinDCX is not
asked to re-place the stop on every tick.

Only trades opened by this tool are trailed (``trades.trail`` = 1; turn one
off with ``trade trail-off PAIR``). Positions opened by hand are not touched.
Prices are polled every watcher round, so a spike between rounds is missed:
the trail can only be as fine as ``trade watch --every``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from backend.trading import risk
from backend.trading.manager import LIVE, TradeError, TradeManager, _f, position_side
from backend.trading.store import OPEN


@dataclass(frozen=True)
class Settings:
    enabled: bool = True
    activate_r: float = 1.0           # start once price is this many R in profit
    trail_r: float = 1.0              # then keep the stop this many R behind the best price
    min_step_r: float = 0.25          # move only when the stop gains at least this much
    breakeven_buffer_pct: float = 0.2  # breakeven = entry + this % (covers both fees)
    min_gap_pct: float = 0.2          # never put the stop closer than this to the price
    candle_buffer_pct: float = 0.1    # candle trail: this % below the low (above the high)

    @classmethod
    def from_config(cls, raw: dict[str, Any] | None) -> "Settings":
        raw = raw or {}
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})


def next_stop(side: str, *, entry: float, initial_stop: float, best: float, price: float,
              current_stop: float | None, s: Settings) -> float | None:
    """The stop to move to now, or None to leave it."""
    r = abs(entry - initial_stop)
    if r <= 0:
        return None
    sign = 1 if side == risk.LONG else -1
    if sign * (best - entry) < s.activate_r * r:
        return None
    breakeven = entry * (1 + sign * s.breakeven_buffer_pct / 100)
    trail = best - sign * s.trail_r * r
    gap = price * (1 - sign * s.min_gap_pct / 100)
    if sign > 0:
        new = min(max(breakeven, trail), gap)
    else:
        new = max(min(breakeven, trail), gap)
    if current_stop and sign * (new - current_stop) < s.min_step_r * r:
        return None
    return new


def next_stop_pct(side: str, *, pct: float, best: float, price: float,
                  current_stop: float | None, s: Settings) -> float | None:
    """Percent trail (positions adopted with ``trade adopt``): the stop sits ``pct``%
    behind the best price from the first round, and moves in steps of a quarter
    of that distance."""
    if pct <= 0:
        return None
    sign = 1 if side == risk.LONG else -1
    new = best * (1 - sign * pct / 100)
    gap = price * (1 - sign * s.min_gap_pct / 100)
    new = min(new, gap) if sign > 0 else max(new, gap)
    if current_stop and sign * (new - current_stop) < best * pct / 100 * s.min_step_r:
        return None
    return new


CANDLE_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}


def last_closed(candles: list[dict], minutes: int, now_ms: int) -> dict | None:
    closed = [c for c in candles if c["time"] + minutes * 60_000 <= now_ms]
    return closed[-1] if closed else None


def next_stop_candle(side: str, *, candle: dict, price: float, current_stop: float | None,
                     s: Settings) -> float | None:
    """Candle trail: a notch under the last closed candle's low (over its high for
    a short). Moves only in the trade's favour, never onto the price."""
    sign = 1 if side == risk.LONG else -1
    edge = float(candle["low"] if sign > 0 else candle["high"])
    new = edge * (1 - sign * s.candle_buffer_pct / 100)
    gap = price * (1 - sign * s.min_gap_pct / 100)
    new = min(new, gap) if sign > 0 else max(new, gap)
    if current_stop and sign * (new - current_stop) <= 0:
        return None
    return new


def run(mgr: TradeManager, s: Settings) -> list[str]:
    """Move the stop of every trailed open trade that has earned it."""
    if not s.enabled:
        return []
    msgs: list[str] = []
    held = {p["pair"]: p for p in mgr.positions()}
    for t in mgr.store.trades(OPEN):
        pos = held.get(t["pair"])
        if t["mode"] != LIVE or not t["trail"] or pos is None:
            continue
        pair = t["pair"]
        side = position_side(pos)
        entry = _f(pos.get("avg_price")) or _f(t["entry"])
        pct = _f(t["trail_pct"])
        tf = t["trail_candle"]
        initial = _f(t["initial_stop"]) or _f(t["stop_loss"])
        price = mgr.last_price(pair)
        if not (entry and price and (initial or pct or tf)):
            continue
        prev_best = _f(t["best_price"]) or entry
        best = max(prev_best, price) if side == risk.LONG else min(prev_best, price)
        if best != _f(t["best_price"]) or (initial and not _f(t["initial_stop"])):
            mgr.store.update_trade(t["id"], best_price=best, initial_stop=initial or None)
        current = _f(pos.get("stop_loss_trigger")) or None
        if tf:
            minutes = CANDLE_MINUTES[tf]
            candle = last_closed(mgr.client.candles(pair, minutes, 6 * minutes * 60),
                                 minutes, int(time.time() * 1000))
            if candle is None:
                continue
            new = next_stop_candle(side, candle=candle, price=price, current_stop=current, s=s)
        elif pct:
            new = next_stop_pct(side, pct=pct, best=best, price=price, current_stop=current, s=s)
        else:
            new = next_stop(side, entry=entry, initial_stop=initial, best=best, price=price,
                            current_stop=current, s=s)
        if new is None:
            continue
        new = risk.round_step(new, mgr.instrument(pair).price_step,
                              down=side == risk.LONG)
        if current and (new <= current if side == risk.LONG else new >= current):
            continue
        locked = (new / entry - 1) * 100 * (1 if side == risk.LONG else -1)
        try:
            mgr.set_tpsl(pair, stop_loss=new)
            msgs.append(f"{pair}: trailing stop {current or 'none'} -> {new:g} "
                        f"({locked:+.1f}% vs entry; best {best:g})"
                        + ("" if mgr.live else " [dry run: not sent]"))
        except TradeError as exc:
            msgs.append(f"{pair}: trailing stop move to {new:g} failed: {exc}")
    for m in msgs:
        mgr.notify(m)
    return msgs
