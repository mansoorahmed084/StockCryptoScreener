"""Alert widgets shared by the dashboard pages.

* ``sidebar_watch()`` — checks every active alert each minute while a page is
  open, pops a toast when one fires, and shows the recent hits.
* ``alert_box(...)`` — "Set an alert on this chart": one click on a detected
  trendline, flat level, order block, Fibonacci level or a typed price.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import streamlit as st

from backend.alerts import price_alerts as pa
from backend.config import load_config
from backend.screener import patterns as pt

CHECK_EVERY = int(load_config().alerts.get("check_seconds", 60))
RECENT_MS = 30 * 60_000                 # hits shown in the sidebar this long


def _svc():
    from frontend import pattern_view as pv     # late import: pattern_view uses us
    return pv.get_service()


def store() -> pa.AlertStore:
    return _svc().alerts()


def ms(ts) -> int:
    return int(pd.Timestamp(ts).value // 1_000_000)


def fmt(v: float | None) -> str:
    if v is None or not np.isfinite(v):
        return "—"
    return f"{v:,.2f}" if abs(v) >= 100 else f"{v:.6g}"


@st.fragment(run_every=CHECK_EVERY)
def _watch() -> None:
    try:
        _svc().check_alerts()
    except Exception as exc:                    # a network blip: try next minute
        st.caption(f"Alert check failed: {exc}")
    now = int(time.time() * 1000)
    recent = store().fired_since(now - RECENT_MS)
    seen = st.session_state.setdefault("_alerts_seen", set())
    for a in recent:
        if a.id not in seen:
            seen.add(a.id)
            st.toast(pa.message(a), icon="🔔", duration="long")
    n = len(store().list(pa.ACTIVE))
    st.caption(f"🔔 {n} active alert{'' if n == 1 else 's'} · checked "
               f"{time.strftime('%H:%M:%S')}")
    for a in recent[:3]:
        st.warning(pa.message(a), icon="🔔")


def sidebar_watch() -> None:
    """Call once per page; it re-runs itself every ``check_seconds``."""
    with st.sidebar:
        _watch()


def close_timeframe(where, cond: str, key: str, default: str = "15m") -> str:
    """For a "closes above / below" condition, ask which candle has to close."""
    if cond not in pa.CLOSES:
        return "1m"
    tfs = list(pa.TIMEFRAMES)
    return where.radio("On a close of the", tfs, index=tfs.index(default), horizontal=True,
                       key=key, format_func=lambda t: f"{t} candle")


def _add(alert: pa.Alert, price: float) -> None:
    if pa.already_met(alert, price):
        st.warning(f"Price {fmt(price)} already meets this — it would fire at once. "
                   "Not saved.")
        return
    store().add(alert)
    st.success(f"Alert set: {alert.describe()}")


def alert_box(coin: str, symbol: str, df: pd.DataFrame, a: pt.ChartAnalysis,
              obs: list[pt.OrderBlock], key: str) -> None:
    """Pick something on the chart (or type a price) and get told when it hits."""
    price = float(df["close"].iloc[-1])
    n = len(df)
    targets: list[tuple[str, dict]] = [("A price I type", {"kind": pa.PRICE})]
    for ln in a.resistances + a.supports:
        targets.append((
            f"{ln.kind.title()} line — now {fmt(ln.at(n - 1))}, {ln.touches} touches",
            {"kind": pa.LINE, "t1": ms(df.index[ln.i0]), "p1": ln.p0,
             "t2": ms(df.index[ln.i1]), "p2": ln.p1,
             "default": "break_up" if ln.kind == pt.RESISTANCE else "break_down"}))
    for lv in a.levels:
        targets.append((f"Flat {lv.kind} {fmt(lv.price)} (×{lv.touches})",
                        {"kind": pa.PRICE, "level": lv.price,
                         "default": "above" if lv.price > price else "below"}))
    for ob in obs:
        targets.append((f"{ob.label} {fmt(ob.bottom)}–{fmt(ob.top)}",
                        {"kind": pa.ZONE, "low": ob.bottom, "high": ob.top}))
    if a.fib:
        for r, v in a.fib.levels.items():
            targets.append((f"Fibonacci {r:g} — {fmt(v)}",
                            {"kind": pa.PRICE, "level": v,
                             "default": "above" if v > price else "below"}))

    with st.expander("🔔 Set an alert on this chart"):
        labels = [t for t, _ in targets]
        pick = st.selectbox("Alert me when price reaches", labels, key=f"{key}_al_t")
        spec = dict(targets[labels.index(pick)][1])
        kind = spec.pop("kind")
        default = spec.pop("default", None)
        if kind == pa.PRICE and "level" not in spec:
            spec["level"] = st.number_input("Price", value=price, format="%.6g",
                                            key=f"{key}_al_p")
        conds = pa.CONDITIONS[kind]
        cond = st.radio("Condition", conds, horizontal=True, key=f"{key}_al_c",
                        index=conds.index(default) if default in conds else 0,
                        format_func=lambda c: pa.CONDITION_TEXT[c])
        step = int((df.index[-1] - df.index[-2]).total_seconds() // 60) if n > 1 else 0
        chart_tf = next((t for t, m in pa.TIMEFRAMES.items() if m == step), "15m")
        tf = close_timeframe(st, cond, key=f"{key}_al_tf", default=chart_tf)
        note = st.text_input("Note (optional)", key=f"{key}_al_n",
                             placeholder="e.g. triangle breakout")
        if st.button("Add alert", key=f"{key}_al_add"):
            coin_ = coin or symbol.removesuffix("USDT")
            _add(pa.Alert(coin=coin_, symbol=symbol, kind=kind, condition=cond,
                          timeframe=tf, note=note, **spec), price)
        st.caption("Checked every minute while the dashboard is open — manage them "
                   "on the Alerts page.")
