"""Alerts — price, trendline and zone alerts you set, checked every minute.

The engine is backend/alerts/price_alerts.py; alerts are stored in SQLite
(data_cache/alerts.db) and checked on 1-minute Binance futures candles by any
open dashboard page, or all the time by ``python -m backend.cli alerts``.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.alerts import price_alerts as pa  # noqa: E402
from backend.alerts.telegram import load_dotenv  # noqa: E402
from frontend import alerts_view as av  # noqa: E402
from frontend import pattern_view as pv  # noqa: E402

st.set_page_config(page_title="Alerts", layout="wide")


@st.cache_data(ttl=30, show_spinner=False)
def last_price(symbol: str) -> float:
    return float(pv.get_service().futures().klines(symbol, "1m", 2)["close"].iloc[-1])


def when(ms_: int | None) -> str:
    if not ms_:
        return "—"
    return pd.Timestamp(ms_, unit="ms", tz="UTC").strftime("%b %d %H:%M UTC")


def new_alert_form(perps: dict[str, str], options: list[str]) -> None:
    st.subheader("New alert")
    c1, c2 = st.columns([1, 2])
    coin = c1.selectbox("Coin", options, key="na_coin",
                        format_func=lambda c: f"{c}  ({perps[c]})")
    symbol = perps[coin]
    price = last_price(symbol)
    c1.caption(f"Now {av.fmt(price)}")
    kind = c2.radio("Type", [pa.PRICE, pa.LINE, pa.ZONE], horizontal=True, key="na_kind",
                    format_func={pa.PRICE: "Price", pa.LINE: "Trendline",
                                 pa.ZONE: "Zone"}.get)
    spec: dict = {}
    if kind == pa.PRICE:
        spec["level"] = c2.number_input("Price", value=price, format="%.6g", key="na_lvl")
    elif kind == pa.ZONE:
        z1, z2 = c2.columns(2)
        spec["low"] = z1.number_input("Zone low", value=price * 0.98, format="%.6g",
                                      key="na_lo")
        spec["high"] = z2.number_input("Zone high", value=price * 0.99, format="%.6g",
                                       key="na_hi")
    else:
        c2.caption("Two points on the line, in UTC — read them off your chart. The "
                   "line runs on past the second point. Tip: the 🔔 box under a chart "
                   "on Chart Patterns sets a detected trendline in one click.")
        now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
        pts = []
        for i, back in ((1, dt.timedelta(days=2)), (2, dt.timedelta(hours=2))):
            a, b, c = c2.columns(3)
            d = a.date_input(f"Point {i} date", value=(now - back).date(), key=f"na_d{i}")
            t = b.time_input(f"Point {i} time", value=(now - back).time(), key=f"na_t{i}",
                             step=dt.timedelta(minutes=15))
            p = c.number_input(f"Point {i} price", value=price, format="%.6g",
                               key=f"na_p{i}")
            ts = dt.datetime.combine(d, t, tzinfo=dt.timezone.utc)
            pts.append((int(ts.timestamp() * 1000), p))
        (spec["t1"], spec["p1"]), (spec["t2"], spec["p2"]) = pts
    conds = pa.CONDITIONS[kind]
    cond = c2.radio("Condition", conds, horizontal=True, key="na_cond",
                    format_func=lambda c: pa.CONDITION_TEXT[c])
    note = c2.text_input("Note (optional)", key="na_note")
    if c2.button("Add alert", type="primary"):
        try:
            alert = pa.Alert(coin=coin, symbol=symbol, kind=kind, condition=cond,
                             note=note, **spec)
        except ValueError as exc:
            c2.error(str(exc))
        else:
            if kind == pa.ZONE and alert.low > alert.high:
                c2.error("Zone low must be under zone high.")
            else:
                with c2:
                    av._add(alert, price)


def active_table(alerts: list[pa.Alert]) -> None:
    st.subheader(f"Active ({len(alerts)})")
    if not alerts:
        st.caption("None yet. Add one above, or from the 🔔 box under any chart.")
        return
    rows = []
    for a in alerts:
        now_px = last_price(a.symbol)
        target = a.target_now()
        rows.append({"Alert": a.describe(), "Waiting for": av.fmt(target),
                     "Price now": av.fmt(now_px),
                     "Distance": f"{(target / now_px - 1) * 100:+.2f}%",
                     "Set": when(a.created_ms), "Last check": when(a.last_checked_ms)})
    event = st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                         on_select="rerun", selection_mode="multi-row", key="act_tbl")
    sel = event.selection.rows if event else []
    if sel and st.button(f"🗑 Delete {len(sel)} selected", key="act_del"):
        for i in sel:
            av.store().delete(alerts[i].id)
        st.rerun()


def fired_table(alerts: list[pa.Alert]) -> None:
    st.subheader(f"Fired ({len(alerts)})")
    if not alerts:
        st.caption("Nothing has fired yet.")
        return
    rows = [{"Alert": a.describe(), "Hit": av.fmt(a.trigger_price),
             "When": when(a.triggered_ms), "Set": when(a.created_ms)} for a in alerts]
    event = st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                         on_select="rerun", selection_mode="multi-row", key="fired_tbl")
    sel = event.selection.rows if event else []
    if sel:
        b1, b2 = st.columns(2)
        if b1.button(f"↻ Re-arm {len(sel)} selected", key="fired_rearm"):
            for i in sel:
                av.store().rearm(alerts[i].id)
            st.rerun()
        if b2.button(f"🗑 Delete {len(sel)} selected", key="fired_del"):
            for i in sel:
                av.store().delete(alerts[i].id)
            st.rerun()


def notifications() -> None:
    svc = pv.get_service()
    load_dotenv()
    telegram = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))
    desktop = svc.config.alerts.get("desktop", True)
    with st.expander("How you get told"):
        st.markdown(
            f"- **Dashboard pop-up:** on every page, checked every "
            f"{av.CHECK_EVERY} seconds while the page is open.\n"
            f"- **Windows notification:** {'on' if desktop else 'off'} "
            "(`alerts.desktop` in config.yaml).\n"
            f"- **Telegram:** {'on' if telegram else 'off'} — put `TELEGRAM_BOT_TOKEN` "
            "and `TELEGRAM_CHAT_ID` in a `.env` file in the project folder.\n"
            "- **With the dashboard closed:** run the watcher in a terminal:")
        st.code(".venv/Scripts/python.exe -m backend.cli alerts", language="bash")
        if st.button("Send a test notification"):
            ok = svc.alert_notifier().send("🔔 Test — alerts are working")
            st.toast("🔔 Test — alerts are working", icon="🔔")
            st.caption("Sent." if ok else "Shown here only: no Windows or Telegram "
                                          "channel is on.")


def main():
    perps = pv.perpetuals()
    tops = [c for c in pv.top_coins() if c in perps]
    options = tops + sorted(c for c in perps if c not in tops)
    av.sidebar_watch()

    st.title("Alerts")
    st.caption("Get told when price reaches a level, a trendline or a zone. Each alert "
               "fires once, on a 1-minute candle (wicks count; line breaks need a "
               "close), then waits in Fired where you can re-arm it.")
    c1, c2 = st.columns([1, 5])
    if c1.button("Check now"):
        fired = pv.get_service().check_alerts()
        c2.success(f"Checked — {len(fired)} fired." if fired else "Checked — nothing hit.")
    new_alert_form(perps, options)
    st.divider()
    active_table(av.store().list(pa.ACTIVE))
    fired_table(av.store().list(pa.TRIGGERED))
    notifications()


main()
