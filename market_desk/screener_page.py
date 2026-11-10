"""The "Screener" page of the Market Desk app: the screener's own results,
as saved by the server every 30 minutes (market_desk/screener_snap.py).

It reads the desk database only, so it works on Streamlit Cloud, where
Binance cannot be reached. Read-only: no trading from here.
"""
from __future__ import annotations

import datetime as dt
import math
import time
from urllib.parse import quote

import pandas as pd
import streamlit as st

from market_desk.screener_snap import LIQ_RANGES, frame_from

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
BLUE, RED = (37, 106, 191), (227, 73, 72)     # same pair as the heatmap: up / down
ARROW = {"bull": "▲", "bear": "▼", "neutral": "·"}
STATE = {"up": "▲ up", "down": "▼ down", "flat": "· flat"}


def _when(ts) -> str:
    if not ts:
        return "never"
    mins = int((time.time() - int(ts)) // 60)
    stamp = dt.datetime.fromtimestamp(int(ts), IST).strftime("%d %b %H:%M IST")
    return f"{stamp} ({mins} min ago)" if mins < 180 else stamp


def _num(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return math.nan
    return v


def _cell(direction: str, strength) -> str:
    s = _num(strength)
    if direction in ("bull", "bear"):
        return f"{ARROW[direction]} {abs(s):.1f}" if not math.isnan(s) else ARROW[direction]
    return "·" if direction == "neutral" else "—"


def _css(direction: str, strength) -> str:
    s = _num(strength)
    a = 0.25 + 0.55 * min(abs(s) / 2.5, 1.0) if not math.isnan(s) else 0.3
    if direction == "bull":
        return f"background-color: rgba({BLUE[0]},{BLUE[1]},{BLUE[2]},{a:.2f})"
    if direction == "bear":
        return f"background-color: rgba({RED[0]},{RED[1]},{RED[2]},{a:.2f})"
    if direction == "neutral":
        return "background-color: rgba(128,128,128,0.15)"
    return "color: #888"


def strength_grid(df: pd.DataFrame, row: str, rows: list[str], cols: list[str]):
    """Rows x timeframes of ▲ / ▼ cells, coloured by direction and strength."""
    look = df.set_index([row, "timeframe"])
    text = pd.DataFrame(index=rows, columns=cols, dtype=object)
    css = pd.DataFrame(index=rows, columns=cols, dtype=object)
    for r in rows:
        for c in cols:
            try:
                hit = look.loc[(r, c)]
                if isinstance(hit, pd.DataFrame):
                    hit = hit.iloc[0]
                d, s = hit["direction"], hit["strength"]
            except KeyError:
                d, s = "unknown", math.nan
            text.loc[r, c] = _cell(d, s)
            css.loc[r, c] = _css(d, s)
    return text.style.apply(lambda _: css, axis=None)


def tv_link(symbol: str) -> str:
    return f"https://www.tradingview.com/chart/?symbol={quote('BINANCE:' + str(symbol) + '.P')}"


# ------------------------------------------------------------------ tabs
def rs_tab(snap: dict) -> None:
    reg = snap["regime"]
    c = st.columns(3)
    c[0].metric("Market regime", reg["label"].replace("_", " ").title())
    c[1].metric("BTC 1d", reg["btc_trend"].get("1d", "—"))
    b1d = reg["breadth"].get("1d")
    c[2].metric("Breadth 1d (% bull vs USDT)", "—" if b1d is None else f"{b1d:.0f}%")
    df = frame_from(snap["matrix"])
    base = st.radio("Measured against", snap["bases"], horizontal=True,
                    index=snap["bases"].index("USDT") if "USDT" in snap["bases"] else 0)
    sub = df[df["base"] == base]
    if sub.empty:
        st.info(f"No data for base {base}.")
        return
    tfs = [t for t in snap["timeframes"] if t in set(sub["timeframe"])]
    st.dataframe(strength_grid(sub, "coin", sorted(sub["coin"].unique()), tfs),
                 width="stretch")
    st.caption("▲ stronger / ▼ weaker than the base, with the noise-filtered strength; "
               "· no clear edge; — no data. Blue = stronger, red = weaker.")


def btc_tab(snap: dict) -> None:
    c = st.columns(3)
    dom = snap.get("btc_dominance_pct")
    c[0].metric("BTC dominance", "—" if dom is None else f"{dom:.1f}%")
    c[1].metric("Coins", len(snap["order"]) - 2)
    c[2].metric("Ranked by", snap.get("coins_from", "—"))
    summary = frame_from(snap["summary"])
    strength = frame_from(snap["strength"])
    trends = frame_from(snap["trends"])
    st.subheader(f"Coins vs {snap['benchmark']}")
    rows = [a for a in snap["order"] if a in set(strength["asset"])]
    st.dataframe(strength_grid(strength, "asset", rows, snap["timeframes"]),
                 width="stretch", height=min(38 * len(rows) + 40, 720))
    with st.expander("Ranking (timeframes each coin beats / lags BTC)"):
        st.dataframe(summary, hide_index=True, width="stretch", column_config={
            "asset": "Coin", "beats": "Beats", "lags": "Lags",
            "score": st.column_config.NumberColumn("Mean strength", format="%+.2f")})
    with st.expander("Trend: daily EMA 20 / 50 / 200"):
        t = trends.assign(cell=trends["state"].map(lambda s: STATE.get(s, s))
                          + trends["dist_pct"].map(lambda v: f" ({_num(v):+.1f}%)"
                                                   if not math.isnan(_num(v)) else ""))
        piv = t.pivot_table(index="asset", columns="horizon", values="cell",
                            aggfunc="first")
        piv = piv.reindex(index=[a for a in snap["order"] if a in piv.index],
                          columns=[h for h in ("short", "medium", "long") if h in piv.columns])
        st.dataframe(piv, width="stretch")


def patterns_tab(snap: dict) -> None:
    df = frame_from(snap["table"])
    if df.empty:
        st.info("No patterns found in the last scan.")
        return
    c = st.columns([2, 2, 3])
    tfs = c[0].multiselect("Timeframes", snap["timeframes"], default=snap["timeframes"])
    biases = sorted(df["bias"].dropna().unique())
    bias = c[1].multiselect("Bias", biases, default=biases)
    statuses = sorted(df["status"].dropna().unique())
    status = c[2].multiselect("Status", statuses, default=statuses)
    df = df[df["timeframe"].isin(tfs) & df["bias"].isin(bias) & df["status"].isin(status)]
    df = df.assign(chart=df["symbol"].map(tv_link))
    st.caption(f"{len(df)} patterns over the top {snap['coins']} Binance perpetuals. "
               "Fresh breakouts first, then the closest to a breakout. "
               "📈 opens the coin on TradingView.")
    st.dataframe(df[["coin", "timeframe", "pattern", "bias", "status", "price", "up_level",
                     "up_pct", "down_level", "down_pct", "target_up", "target_down",
                     "setup", "chart"]],
                 hide_index=True, width="stretch", height=600, column_config={
                     "coin": "Coin", "timeframe": "TF", "pattern": "Pattern",
                     "bias": "Bias", "status": "Status",
                     "price": st.column_config.NumberColumn("Price", format="%.6g"),
                     "up_level": st.column_config.NumberColumn("Break up", format="%.6g"),
                     "up_pct": st.column_config.NumberColumn("Up %", format="%+.1f"),
                     "down_level": st.column_config.NumberColumn("Break down", format="%.6g"),
                     "down_pct": st.column_config.NumberColumn("Down %", format="%+.1f"),
                     "target_up": st.column_config.NumberColumn("Target up", format="%.6g"),
                     "target_down": st.column_config.NumberColumn("Target down",
                                                                  format="%.6g"),
                     "setup": st.column_config.TextColumn("Setup", width="large"),
                     "chart": st.column_config.LinkColumn("Chart", display_text="📈")})


def _cluster(c) -> str:
    if not c:
        return "—"
    return f"{c['price']:,.6g} ({c['dist_pct']:+.1f}%, ${c['size_usd'] / 1e6:,.0f}M)"


def liq_tab(snap: dict) -> None:
    reads = snap.get("market_read") or []
    if reads:
        st.subheader("Market read (1h)")
        df = pd.DataFrame([{
            "coin": r["coin"], "lean": r["lean"], "confidence": r["confidence"],
            "score": r["score"], "price": r["price"], "trend_1h": r["trend_1h"],
            "rsi_1h": r["rsi_1h"], "chg_6h": r["chg_6h"], "chg_24h": r["chg_24h"],
            "funding_pct": r["funding_pct"], "oi_24h_pct": r["oi_24h_pct"],
            "above": _cluster(r.get("above")), "below": _cluster(r.get("below")),
            "why": "; ".join(r.get("reasons") or []),
            "chart": tv_link(r["symbol"])} for r in reads])
        st.dataframe(df, hide_index=True, width="stretch", column_config={
            "coin": "Coin", "lean": "Lean", "confidence": "Confidence",
            "score": st.column_config.NumberColumn("Score", format="%+.1f"),
            "price": st.column_config.NumberColumn("Price", format="%.6g"),
            "trend_1h": "1h trend",
            "rsi_1h": st.column_config.NumberColumn("RSI 1h", format="%.0f"),
            "chg_6h": st.column_config.NumberColumn("6h %", format="%+.1f"),
            "chg_24h": st.column_config.NumberColumn("24h %", format="%+.1f"),
            "funding_pct": st.column_config.NumberColumn("Funding %", format="%+.4f"),
            "oi_24h_pct": st.column_config.NumberColumn("OI 24h %", format="%+.1f"),
            "above": "Nearest cluster above", "below": "Nearest cluster below",
            "why": st.column_config.TextColumn("Why", width="large"),
            "chart": st.column_config.LinkColumn("Chart", display_text="📈")})
        st.caption("Rules-based short-term lean from 1h candles, open interest, funding "
                   "and the liquidation maps. A read, not a signal.")
    st.subheader("Estimated liquidation levels")
    rk = st.radio("Range", list(LIQ_RANGES), horizontal=True)
    ov = frame_from(snap["overview"][rk])
    cols = [c for c in ("coin", "price", "above_usd", "below_usd", "zone_above",
                        "zone_above_pct", "zone_above_usd", "zone_below", "zone_below_pct",
                        "zone_below_usd") if c in ov]
    money = {c: st.column_config.NumberColumn(label, format="compact")
             for c, label in (("above_usd", "Shorts above $"), ("below_usd", "Longs below $"),
                              ("zone_above_usd", "Zone above $"),
                              ("zone_below_usd", "Zone below $"))}
    st.dataframe(ov[cols], hide_index=True, width="stretch", column_config={
        "coin": "Coin", "price": st.column_config.NumberColumn("Price", format="%.6g"),
        "zone_above": st.column_config.NumberColumn("Biggest zone above", format="%.6g"),
        "zone_above_pct": st.column_config.NumberColumn("Above %", format="%+.1f"),
        "zone_below": st.column_config.NumberColumn("Biggest zone below", format="%.6g"),
        "zone_below_pct": st.column_config.NumberColumn("Below %", format="%+.1f"),
        **money})
    st.caption("Model estimates from Binance open interest at 10x-100x leverage, like the "
               "laptop's Liquidation Heatmap page. Sizes are estimates.")


TABS = (("rs", "📊 Strength matrix", rs_tab), ("btc", "₿ BTC strength", btc_tab),
        ("patterns", "📐 Patterns", patterns_tab), ("liq", "💥 Liquidations", liq_tab))


def render(store) -> None:
    st.title("📊 Screener")
    snaps = {name: store.snapshot(name) for name, _, _ in TABS}
    made = [s["ts"] for s in snaps.values() if s]
    st.caption("The screener's own results, made by the server every 30 minutes "
               f"(last: {_when(max(made)) if made else 'never'}). Read-only. "
               "For drawing and trading, use the laptop dashboard.")
    if st.button("🔄 Reload", key="screener_reload"):
        st.rerun()
    tabs = st.tabs([label for _, label, _ in TABS])
    for tab, (name, label, fn) in zip(tabs, TABS):
        with tab:
            snap = snaps[name]
            if not snap:
                st.info("Not made yet. The server makes it every 30 minutes.")
                continue
            st.caption(f"Made {_when(snap['ts'])}.")
            try:
                fn(snap)
            except Exception as exc:     # one broken part must not hide the others
                st.error(f"Could not show this part: {type(exc).__name__}: {exc}")
