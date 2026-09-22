"""Scan many coins and timeframes for chart patterns near a breakout.

For every (coin, timeframe) it runs :func:`patterns.analyse` on Binance
futures candles, keeps the patterns asked for, and adds the daily order blocks
nearest the price above and below, so a pattern breaking up straight into
daily supply stands out from one with room to run.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from . import patterns as pt

BULLISH = ("Ascending triangle", "Falling wedge", "Double bottom")
BEARISH = ("Descending triangle", "Rising wedge", "Double top")
NEUTRAL = ("Symmetrical triangle", "Rising channel", "Falling channel", "Range",
           "Broadening pattern")
ALL_PATTERNS = BULLISH + BEARISH + NEUTRAL
DEFAULT_PATTERNS = ("Ascending triangle", "Falling wedge", "Descending triangle",
                    "Rising wedge")

COLUMNS = ["coin", "symbol", "timeframe", "pattern", "bias", "status", "price",
           "up_level", "up_pct", "down_level", "down_pct", "target_up",
           "target_down", "touches", "near_pct", "zone_above", "zone_above_pct",
           "zone_below", "zone_below_pct", "setup"]


def _pct(level: float, price: float) -> float:
    return (level / price - 1) * 100 if np.isfinite(level) else float("nan")


def _zone(obs: list[pt.OrderBlock], role: str, price: float) -> tuple[str, float]:
    side = [ob for ob in obs if ob.role == role]
    if not side:
        return "—", float("nan")
    ob = min(side, key=lambda z: min(abs(z.bottom - price), abs(z.top - price)))
    edge = ob.bottom if role == pt.RESISTANCE else ob.top
    inside = ob.bottom <= price <= ob.top
    return (f"{ob.bottom:.6g}–{ob.top:.6g} ({'flipped' if ob.broken else 'fresh' if ob.tests == 0 else 'tested'})",
            0.0 if inside else _pct(edge, price))


LATE_PCT = 3.0      # past the line by more than this: the move already ran


def setup_text(row: dict) -> str:
    """A plain description of where the pattern stands. Not advice."""
    name, status = row["pattern"], row["status"]
    bull = name in BULLISH or (name not in BEARISH and row["bias"] == "bullish")
    if status == "broke up" or (status == "confirmed" and bull):
        direction = "up"
    elif status == "broke down" or (status == "confirmed" and not bull):
        direction = "down"
    elif name in BULLISH or name in BEARISH:
        direction = "up" if bull else "down"
    else:                                   # neutral: the nearer line
        direction = "up" if abs(row["up_pct"]) <= abs(row["down_pct"]) else "down"
    line_pct = row["up_pct"] if direction == "up" else row["down_pct"]

    if status in ("broke up", "broke down", "confirmed"):
        text = f"Broke {direction}"
        if (direction == "up") != bull and (name in BULLISH or name in BEARISH):
            text += " against the usual bias"
        past = abs(line_pct) if np.isfinite(line_pct) else 0.0
        text += f", {past:.1f}% past the line (late)" if past > LATE_PCT else ", fresh"
    else:
        near = abs(line_pct)
        text = (f"{'Near breakout' if near <= 1.5 else 'Forming'}: {near:.1f}% to "
                f"the {'upper' if direction == 'up' else 'lower'} line")

    room = row["zone_above_pct"] if direction == "up" else row["zone_below_pct"]
    if np.isfinite(room):
        zone = "supply" if direction == "up" else "demand"
        text += f"; daily {zone} " + ("here" if room == 0 else f"{room:+.1f}% away")
    return text


def scan(fetch: Callable[[str, str, int], pd.DataFrame], coins: dict[str, str],
         timeframes: list[str], *, patterns: tuple[str, ...] = DEFAULT_PATTERNS,
         candles: int = 300, workers: int = 8,
         progress: Callable[[int, int], None] | None = None) -> pd.DataFrame:
    """``fetch(symbol, timeframe, limit)`` returns candles, oldest first."""
    wanted = set(patterns)

    def one(item: tuple[str, str]) -> list[dict]:
        coin, symbol = item
        rows: list[dict] = []
        try:
            daily = fetch(symbol, "1d", 500)
            obs = pt.order_blocks(daily) if len(daily) > 30 else []
        except Exception:
            daily, obs = pd.DataFrame(), []
        for tf in timeframes:
            try:
                df = daily.tail(candles) if tf == "1d" and len(daily) else \
                    fetch(symbol, tf, candles)
                if len(df) < 60:
                    continue
                a = pt.analyse(df)
            except Exception:
                continue
            price = float(df["close"].iloc[-1])
            for p in a.patterns:
                if p.name not in wanted:
                    continue
                above, above_pct = _zone(obs, pt.RESISTANCE, price)
                below, below_pct = _zone(obs, pt.SUPPORT, price)
                up_pct, dn_pct = _pct(p.breakout_up, price), _pct(p.breakout_down, price)
                touches = "/".join(str(ln.touches) for ln in (p.upper, p.lower) if ln) \
                    or str(len(p.points))
                row = {"coin": coin, "symbol": symbol, "timeframe": tf,
                       "pattern": p.name, "bias": p.bias, "status": p.status,
                       "price": price, "up_level": p.breakout_up, "up_pct": up_pct,
                       "down_level": p.breakout_down, "down_pct": dn_pct,
                       "target_up": p.target_up, "target_down": p.target_down,
                       "touches": touches,
                       "near_pct": np.nanmin([abs(up_pct), abs(dn_pct)]),
                       "zone_above": above, "zone_above_pct": above_pct,
                       "zone_below": below, "zone_below_pct": below_pct}
                row["setup"] = setup_text(row)
                rows.append(row)
        return rows

    items = list(coins.items())
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for done, rows in enumerate(pool.map(one, items), 1):
            out.extend(rows)
            if progress:
                progress(done, len(items))
    df = pd.DataFrame(out, columns=COLUMNS)
    # Fresh breakouts first, then whatever sits closest to its breakout line.
    order = df["status"].map({"broke up": 0, "broke down": 0, "confirmed": 0}).fillna(1)
    return df.assign(_o=order).sort_values(["_o", "near_pct"]).drop(columns="_o") \
        .reset_index(drop=True)
