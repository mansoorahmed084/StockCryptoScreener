"""Liquidation heatmap — estimated liquidation zones for BTC and the top coins.

A CoinGlass-style model built from Binance futures open interest; see
backend/screener/liquidation.py for how the levels are estimated.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.config import load_config  # noqa: E402
from backend.screener import liquidation as liq  # noqa: E402
from backend.screener import market_read as mr  # noqa: E402
from backend.service import ScreenerService  # noqa: E402
from frontend import alerts_view  # noqa: E402

st.set_page_config(page_title="Liquidation heatmap", layout="wide")

RANGE_KEYS = list(liq.RANGES)
# How far past the traded range the chart shows by default (it can be zoomed).
VIEW_PAD = {"12h": 0.03, "1d": 0.04, "3d": 0.06, "7d": 0.09, "30d": 0.13}

# Sequential blue ramp from the dataviz reference palette. Zero is see-through
# and small levels fade toward the surface, so only big clusters glow. The
# anchor flips between themes: the strong end contrasts with the page.
_LIGHT = dict(ramp=["rgba(205,226,251,0.35)", "#b7d3f6", "#5598e7", "#1c5cab",
                    "#0d366b"],
              price="#eb6834", bar="#2a78d6", ink="#0b0b0b", ink2="#52514e",
              muted="#898781", grid="#e1e0d9", label_bg="rgba(252,252,251,0.8)")
_DARK = dict(ramp=["rgba(13,54,107,0.35)", "#0d366b", "#256abf", "#6da7ec",
                   "#cde2fb"],
             price="#d95926", bar="#3987e5", ink="#ffffff", ink2="#c3c2b7",
             muted="#898781", grid="#2c2c2a", label_bg="rgba(26,26,25,0.8)")


def palette() -> dict:
    try:
        return _LIGHT if st.context.theme.type == "light" else _DARK
    except AttributeError:
        return _DARK


def heat_scale(p: dict) -> list[list]:
    r = p["ramp"]
    return [[0.0, "rgba(0,0,0,0)"], [0.01, r[0]], [0.3, r[1]], [0.55, r[2]],
            [0.8, r[3]], [1.0, r[4]]]


# -- data ----------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_service() -> ScreenerService:
    return ScreenerService(load_config(), refresh=False)


@st.cache_data(ttl=3600, show_spinner="Finding the top coins…")
def top_coins() -> dict[str, str]:
    return get_service().liquidation_coins(10)


@st.cache_data(ttl=3600, show_spinner=False)
def all_perpetuals() -> dict[str, str]:
    return get_service().futures().perpetuals()


@st.cache_data(ttl=60, show_spinner="Estimating liquidation levels…")
def liq_map(symbol: str, range_key: str) -> liq.LiqMap:
    return get_service().liquidation_map(symbol, range_key)


@st.cache_data(ttl=120, show_spinner="Scanning BTC and the top coins…")
def overview(coins: tuple[tuple[str, str], ...], range_key: str) -> pd.DataFrame:
    svc = get_service()

    def one(item: tuple[str, str]) -> dict:
        coin, symbol = item
        try:
            row = liq.summary(svc.liquidation_map(symbol, range_key))
        except Exception as exc:          # one bad symbol must not sink the table
            row = {"error": str(exc)}
        return {"coin": coin, "symbol": symbol, **row}

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(one, coins))
    cols = ["coin", "symbol", "price", "above_usd", "below_usd", "zone_above",
            "zone_above_pct", "zone_above_usd", "zone_below", "zone_below_pct",
            "zone_below_usd"]
    return pd.DataFrame(rows).reindex(columns=cols)


@st.cache_data(ttl=300, show_spinner="Reading the 1h charts and liquidity…")
def market_read() -> tuple[list[mr.CoinRead], str]:
    reads = get_service().market_read(10)
    return reads, pd.Timestamp.now(tz="UTC").strftime("%b %d, %H:%M UTC")


# -- formatting ------------------------------------------------------------------
def money(v: float) -> str:
    if v is None or pd.isna(v):
        return "—"
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"${v / div:.1f}{unit}"
    return f"${v:.0f}"


def price_fmt(v: float) -> str:
    if v is None or pd.isna(v):
        return "—"
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 1:
        return f"{v:,.3f}"
    return f"{v:.6g}"


# -- charts ------------------------------------------------------------------------
def heatmap_figure(m: liq.LiqMap, z: pd.DataFrame, symbol: str, range_key: str,
                   p: dict) -> go.Figure:
    times = m.candles.index
    positive = m.heat[m.heat > 0]
    # Clip at the 99th percentile so one huge level does not wash out the rest.
    zmax = float(np.percentile(positive, 99.5)) if positive.size else 1.0
    last = m.last_price
    profile = m.longs + m.shorts

    fig = make_subplots(rows=1, cols=2, shared_yaxes=True,
                        column_widths=[0.83, 0.17], horizontal_spacing=0.01)
    fig.add_trace(go.Heatmap(
        x=times, y=m.prices, z=m.heat.T, zmin=0, zmax=zmax,
        colorscale=heat_scale(p), showscale=False, hoverongaps=False,
        hovertemplate="%{x|%b %d %H:%M}<br>Price %{y:,.6g}"
                      "<br>Est. liquidations %{z:$,.3s}<extra></extra>"),
        row=1, col=1)
    fig.add_trace(go.Scatter(
        x=times, y=m.candles["close"], mode="lines", name="Price",
        line=dict(color=p["price"], width=2),
        hovertemplate="%{x|%b %d %H:%M}<br>Price %{y:,.6g}<extra></extra>"),
        row=1, col=1)
    # Right: open liquidations by price right now (above = shorts, below = longs).
    fig.add_trace(go.Bar(
        x=profile, y=m.prices, orientation="h", marker=dict(color=p["bar"]),
        hovertemplate="Price %{y:,.6g}<br>Open now %{x:$,.3s}<extra></extra>"),
        row=1, col=2)
    fig.add_hline(y=last, line=dict(color=p["price"], width=1, dash="dot"))
    # Label the biggest zones on the profile only: selective direct labels.
    for _, r in z.iterrows():
        fig.add_annotation(x=0, y=r["price"], xref="x2", yref="y",
                           text=f"{price_fmt(r['price'])} · {money(r['size_usd'])}",
                           showarrow=False, xanchor="left", yanchor="middle",
                           font=dict(size=11, color=p["ink"]), bgcolor=p["label_bg"])

    pad = VIEW_PAD.get(range_key, 0.05)
    lo = float(m.candles["low"].min()) * (1 - pad)
    hi = float(m.candles["high"].max()) * (1 + pad)
    fig.update_yaxes(range=[lo, hi], gridcolor=p["grid"], zeroline=False,
                     tickfont=dict(color=p["muted"]), automargin=True,
                     tickformat=",.6~g", row=1, col=1)
    fig.update_xaxes(showgrid=False, tickfont=dict(color=p["muted"]),
                     automargin=True, row=1, col=1)
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False,
                     row=1, col=2)
    fig.update_layout(height=640, showlegend=False, bargap=0,
                      margin=dict(l=60, r=10, t=30, b=40),
                      title=dict(text=f"{symbol} · last {range_key} · price "
                                      f"{price_fmt(last)}",
                                 font=dict(size=14, color=p["ink2"])),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      hovermode="closest")
    return fig


def zones_table(z: pd.DataFrame, side: str) -> pd.DataFrame:
    sub = z[z["side"] == side]
    return pd.DataFrame({
        "Price": [price_fmt(v) for v in sub["price"]],
        "Distance": [f"{v:+.2f}%" for v in sub["dist_pct"]],
        "Est. size": [money(v) for v in sub["size_usd"]],
    })


def market_read_panel() -> None:
    """The rules-based lean for BTC and the top 10 (see market_read.py)."""
    reads, when = market_read()
    with st.expander(f"📋 Market read · BTC and the top 10 · {when}", expanded=True):
        st.caption("A rules-based read of the 1h charts and the 1d / 7d liquidation "
                   "maps. It updates every 5 minutes. Not financial advice: "
                   "liquidity “magnets” are a tendency, not a rule.")
        if not reads:
            st.warning("No data from Binance right now.")
            return
        st.info(mr.market_summary(reads))

        def cluster(c: mr.Cluster | None) -> str:
            if c is None:
                return "—"
            return f"{price_fmt(c.price)} ({c.dist_pct:+.1f}%) · {money(c.size_usd)}"

        table = pd.DataFrame({
            "Coin": [r.coin for r in reads],
            "Price": [price_fmt(r.price) for r in reads],
            "Last 48h (1h)": [r.closes_48h for r in reads],
            "24h": [f"{r.chg_24h:+.1f}%" for r in reads],
            "Lean": [mr.LEAN_TEXT[r.lean] for r in reads],
            "Confidence": [r.confidence for r in reads],
            "Pull below": [cluster(r.below) for r in reads],
            "Pull above": [cluster(r.above) for r in reads],
            "Why": ["; ".join(r.reasons) for r in reads],
        })
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            "Last 48h (1h)": st.column_config.LineChartColumn(width="small"),
            "Lean": st.column_config.TextColumn(width="medium"),
            "Why": st.column_config.TextColumn(width="large"),
        })
        with st.popover("How the lean is scored"):
            st.markdown(
                "Each rule adds to a score:\n"
                "- **1h trend:** close above a rising 20 EMA, above the 50 EMA: "
                "+1. The mirror: −1.\n"
                "- **Nearest pull:** the side whose nearest big liquidation "
                "cluster is bigger per % of distance, by 1.5× or more: +1 above, "
                "−1 below.\n"
                "- **7d balance:** under half as much liquidity above as below: "
                "−0.5. Over twice as much: +0.5.\n"
                "- **Stretched:** 1h RSI over 70: −0.5. Under 30: +0.5.\n"
                "- **Crowded:** open interest +15% in 24h after a 5% move: −0.5 "
                "after a pump, +0.5 after a dump.\n"
                "- **Funding:** over 0.03%: −0.5. Under −0.01%: +0.5.\n\n"
                "Score ≥ 1: up. ≤ −1: down. When the 1h trend and the nearest "
                "pull disagree and the rest is small: *dip first, then up* (or "
                "*bounce first, then down*). Confidence never goes above medium, "
                "and small clusters near the price (under $5M together) are always low.")


# -- page --------------------------------------------------------------------------
def main():
    p = palette()
    tops = top_coins()
    perps = all_perpetuals()
    options = list(tops) + sorted(c for c in perps if c not in tops)
    if "liq_coin" not in st.session_state:
        st.session_state["liq_coin"] = "BTC"
    if "liq_coin_next" in st.session_state:          # a click in the overview
        st.session_state["liq_coin"] = st.session_state.pop("liq_coin_next")

    with st.sidebar:
        st.header("Controls")
        coin = st.selectbox("Coin", options, key="liq_coin",
                            format_func=lambda c: f"{c}  ({perps.get(c, '')})",
                            help="BTC and the top 10 by market cap come first. "
                                 "Type to search every Binance USDT perpetual.")
        range_key = st.radio("Range", RANGE_KEYS, index=RANGE_KEYS.index("1d"),
                             horizontal=True,
                             help="Binance keeps 30 days of open-interest history.")
        if st.button("🔄 Refresh data"):
            st.cache_data.clear()
            get_service().futures()._cache.clear()
    alerts_view.sidebar_watch()

    symbol = perps[coin]
    st.title("Liquidation heatmap")
    st.caption("Where leveraged traders would be liquidated, estimated from "
               "Binance futures open interest (the CoinGlass method). Bright "
               "bands are big clusters: price is often drawn to them. Model "
               "estimate, Binance only, so sizes are smaller than CoinGlass's "
               "all-exchange totals.")

    market_read_panel()

    m = liq_map(symbol, range_key)
    z = liq.zones(m, k=3)
    s = liq.summary(m)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", price_fmt(m.last_price))
    c2.metric("Open liquidations above", money(s["above_usd"]),
              help="Short positions that would be liquidated if price rises.")
    c3.metric("Open liquidations below", money(s["below_usd"]),
              help="Long positions that would be liquidated if price falls.")
    ratio = s["above_usd"] / s["below_usd"] if s["below_usd"] else np.nan
    c4.metric("Above ÷ below", "—" if pd.isna(ratio) else f"{ratio:.2f}",
              help="Above 1: more liquidity above price. Below 1: more below.")

    st.plotly_chart(heatmap_figure(m, z, symbol, range_key, p), width="stretch",
                    theme=None, config={"displayModeBar": False})
    st.caption("Left: estimated open liquidations over time; orange = price. "
               "Right: what is open now at each price, with the biggest "
               "zones labelled. The window starts empty, so its first "
               "candles look faint. Scroll or drag on the chart to zoom.")

    a, b = st.columns(2)
    a.markdown("**Biggest zones above price** (short liquidations)")
    a.dataframe(zones_table(z, liq.SHORT), hide_index=True, width="stretch")
    b.markdown("**Biggest zones below price** (long liquidations)")
    b.dataframe(zones_table(z, liq.LONG), hide_index=True, width="stretch")

    # -- BTC + top 10 overview ------------------------------------------------------
    st.subheader(f"BTC and the top coins · last {range_key}")
    ov = overview(tuple(tops.items()), range_key)
    def zone(side: str) -> list[str]:
        return [f"{price_fmt(pz)} ({pc:+.1f}%) · {money(sz)}" if pd.notna(pz) else "—"
                for pz, pc, sz in zip(ov[f"zone_{side}"], ov[f"zone_{side}_pct"],
                                      ov[f"zone_{side}_usd"])]

    table = pd.DataFrame({
        "Coin": ov["coin"],
        "Price": [price_fmt(v) for v in ov["price"]],
        "Above": [money(v) for v in ov["above_usd"]],
        "Below": [money(v) for v in ov["below_usd"]],
        "Above ÷ below": [f"{a_ / b_:.2f}" if pd.notna(a_) and b_ else "—"
                          for a_, b_ in zip(ov["above_usd"], ov["below_usd"])],
        "Biggest zone above": zone("above"),
        "Biggest zone below": zone("below"),
    })
    event = st.dataframe(table, hide_index=True, width="stretch",
                         on_select="rerun", selection_mode="single-row",
                         key="liq_overview")
    st.caption("Click a row to open its heatmap above.")
    # Act only when the clicked row changes: the table keeps its selection, and
    # a later pick in the sidebar must not be switched back to it.
    sel = tuple(event.selection.rows) if event else ()
    if sel != st.session_state.get("liq_last_sel", ()):
        st.session_state["liq_last_sel"] = sel
        if sel and table["Coin"].iloc[sel[0]] != coin:
            st.session_state["liq_coin_next"] = table["Coin"].iloc[sel[0]]
            st.rerun()


main()
