"""Crypto Relative-Strength Screener — Streamlit dashboard (Phase 2).

Run with:  streamlit run frontend/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Make the repo root importable when Streamlit runs this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import load_config  # noqa: E402
from backend.screener import filters as filters_mod  # noqa: E402
from backend.screener import rs as rs_mod  # noqa: E402
from backend.screener import sectors as sectors_mod  # noqa: E402
from backend.service import ScreenerService  # noqa: E402

st.set_page_config(page_title="Crypto RS Screener", layout="wide")


@st.cache_resource(show_spinner="Connecting to exchange…")
def get_service():
    return ScreenerService(load_config())


@st.cache_data(show_spinner="Building relative-strength matrix…")
def build(coins, bases, timeframes, liquidity_gate, _nonce):
    svc = get_service()
    df = svc.build_matrix(coins, bases, timeframes, liquidity_gate=liquidity_gate)
    return df


def _strength_color(direction: str, strength: float) -> str:
    if direction == rs_mod.UNKNOWN:
        return "background-color: #2b2b2b; color: #777"
    if direction == rs_mod.NEUTRAL:
        return "background-color: #3a3a3a; color: #aaa"
    mag = min(abs(strength) / 2.5, 1.0) if pd.notna(strength) else 0.3
    if direction == rs_mod.BULL:
        g = int(80 + 120 * mag)
        return f"background-color: rgb(20,{g},60); color: #eafff0"
    r = int(80 + 120 * mag)
    return f"background-color: rgb({r},30,40); color: #ffecec"


def _cell_text(direction: str, strength: float) -> str:
    if direction == rs_mod.BULL:
        return f"▲ {abs(strength):.1f}"
    if direction == rs_mod.BEAR:
        return f"▼ {abs(strength):.1f}"
    if direction == rs_mod.NEUTRAL:
        return "·"
    return "—"


def render_heatmap(df: pd.DataFrame, base: str, timeframes: list[str]):
    sub = df[df["base"] == base]
    if sub.empty:
        st.info(f"No data for base {base}.")
        return
    coins = sorted(sub["coin"].unique())
    tfs = [t for t in timeframes if t in sub["timeframe"].unique()]
    text = pd.DataFrame(index=coins, columns=tfs, dtype=object)
    styles = pd.DataFrame(index=coins, columns=tfs, dtype=object)
    lookup = sub.set_index(["coin", "timeframe"])
    for c in coins:
        for t in tfs:
            try:
                row = lookup.loc[(c, t)]
                d, s = row["direction"], row["strength"]
            except KeyError:
                d, s = rs_mod.UNKNOWN, float("nan")
            text.loc[c, t] = _cell_text(d, s)
            styles.loc[c, t] = _strength_color(d, s)
    styler = text.style.apply(lambda _: styles, axis=None)
    st.dataframe(styler, use_container_width=True)


def render_chart(svc, coin, base, timeframe):
    frame = svc.ratio_frame(coin, base, timeframe)
    if frame.empty:
        st.warning("No candles for this pair/timeframe.")
        return
    ema = frame["close"].ewm(span=21, adjust=False).mean()
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=frame.index, open=frame["open"], high=frame["high"],
        low=frame["low"], close=frame["close"], name=f"{coin}/{base}"))
    fig.add_trace(go.Scatter(x=frame.index, y=ema, name="EMA21",
                             line=dict(color="orange", width=1)))
    fig.update_layout(height=520, xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=30, b=10),
                      title=f"{coin}/{base} · {timeframe}")
    st.plotly_chart(fig, use_container_width=True)


def main():
    st.title("📊 Crypto Relative-Strength Screener")
    cfg = load_config()

    with st.sidebar:
        st.header("Controls")
        svc = get_service()
        universe = svc.universe()
        coins = st.multiselect("Coins", options=universe, default=universe)
        bases = st.multiselect("Bases", options=cfg.bases, default=cfg.bases)
        timeframes = st.multiselect("Timeframes", options=cfg.timeframes,
                                    default=cfg.timeframes)
        liquidity_gate = st.checkbox("Liquidity gate", value=True)
        if st.button("🔄 Refresh data"):
            st.cache_data.clear()
        nonce = st.session_state.get("_nonce", 0)

    if not (coins and bases and timeframes):
        st.warning("Pick at least one coin, base and timeframe.")
        return

    df = build(tuple(coins), tuple(bases), tuple(timeframes), liquidity_gate, nonce)

    # -- regime header --------------------------------------------------------
    reg = svc.regime(df)
    c1, c2, c3 = st.columns(3)
    c1.metric("Market regime", reg.label.replace("_", " ").title())
    c2.metric("BTC 1d", reg.btc_trend.get("1d", "—"))
    b1d = reg.breadth.get("1d", float("nan"))
    c3.metric("Breadth 1d (% bull vs USDT)",
              f"{b1d:.0f}%" if b1d == b1d else "—")

    tab_screen, tab_filter, tab_sector, tab_chart = st.tabs(
        ["Screener", "Filters", "Sectors", "Chart"])

    with tab_screen:
        for base in bases:
            st.subheader(f"vs {base}")
            render_heatmap(df, base, timeframes)

    with tab_filter:
        st.caption("Combine conditions with AND to scan. Presets are saved filters.")
        preset = st.selectbox("Preset", ["(custom)"] + list(filters_mod.PRESETS))
        if preset != "(custom)":
            base = st.selectbox("Base", bases, key="preset_base")
            flt = filters_mod.PRESETS[preset](base) if preset != "fresh_momentum" \
                else filters_mod.PRESETS[preset](base)
            st.code(flt.name, language=None)
        else:
            st.write("Build an AND filter across timeframes:")
            fbase = st.selectbox("Base", bases, key="cust_base")
            ftfs = st.multiselect("Timeframes (all must be bull)", timeframes,
                                  default=timeframes[:3])
            fdir = st.radio("Direction", [rs_mod.BULL, rs_mod.BEAR], horizontal=True)
            flt = filters_mod.Filter(logic="AND", conditions=[
                filters_mod.Condition("*", fbase, tf, "direction", "is", fdir)
                for tf in ftfs])
        matches = sorted(flt.evaluate(df))
        st.success(f"{len(matches)} match(es): {', '.join(matches) or '—'}")
        if matches:
            st.dataframe(df[df["coin"].isin(matches)][
                ["coin", "base", "timeframe", "direction", "strength", "rank"]],
                use_container_width=True, hide_index=True)

    with tab_sector:
        for base in bases:
            hm = sectors_mod.sector_heatmap(df, cfg, base)
            if hm.empty:
                continue
            st.subheader(f"Sector strength vs {base}")
            st.dataframe(hm.reindex(columns=[t for t in timeframes if t in hm.columns])
                         .style.background_gradient(cmap="RdYlGn", axis=None),
                         use_container_width=True)

    with tab_chart:
        cc1, cc2, cc3 = st.columns(3)
        coin = cc1.selectbox("Coin", coins)
        base_opts = [b for b in bases if b != coin] or bases  # no COIN/COIN identity
        base = cc2.selectbox("Base", base_opts, key="chart_base")
        tf = cc3.selectbox("Timeframe", timeframes, key="chart_tf")
        if coin == base:
            st.info("Pick a base different from the coin.")
        else:
            render_chart(svc, coin, base, tf)


main()
