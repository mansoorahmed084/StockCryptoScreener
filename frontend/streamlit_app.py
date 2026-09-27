"""Crypto Relative-Strength Screener — Streamlit dashboard (Phase 2).

Run with:  streamlit run frontend/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# Make the repo root importable when Streamlit runs this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import load_config  # noqa: E402
from backend.data.futures import fetch_futures  # noqa: E402
from backend.indicators.vumanchu import VuManChuCipherB  # noqa: E402
from backend.screener import filters as filters_mod  # noqa: E402
from backend.screener import rs as rs_mod  # noqa: E402
from backend.screener import sectors as sectors_mod  # noqa: E402
from backend.signals.backtest import backtest_signal  # noqa: E402
from backend.signals.journal import SignalJournal  # noqa: E402
from backend.service import ScreenerService  # noqa: E402
from frontend import alerts_view, trade_hours_view  # noqa: E402

st.set_page_config(page_title="Crypto RS Screener", layout="wide")


@st.cache_resource(show_spinner="Connecting to exchange…")
def get_service():
    return ScreenerService(load_config())


@st.cache_data(show_spinner="Building relative-strength matrix…")
def build(coins, bases, timeframes, liquidity_gate):
    svc = get_service()
    df = svc.build_matrix(coins, bases, timeframes, liquidity_gate=liquidity_gate)
    return df


@st.cache_data(ttl=60, show_spinner="Building confluence report…")
def build_report(coins, base, timeframes, div_lookback, all_bull):
    svc = get_service()
    return svc.report(list(coins), base, list(timeframes),
                      div_lookback=div_lookback, require_all_bull=all_bull)


@st.cache_data(ttl=120, show_spinner=False)
def futures_map():
    try:
        return {c: (fi.funding_rate, fi.bias) for c, fi in fetch_futures().items()}
    except Exception:
        return {}


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


_MARKER_STYLE = {
    "buy": dict(symbol="triangle-up", color="#22dd77"),
    "sell": dict(symbol="triangle-down", color="#ff4d4d"),
    "bull_div": dict(symbol="circle", color="#00e5ff"),
    "bear_div": dict(symbol="circle", color="#ffd000"),
}


def render_chart(svc, coin, base, timeframe, show_vumanchu=True):
    frame = svc.ratio_frame(coin, base, timeframe)
    if frame.empty:
        st.warning("No candles for this pair/timeframe.")
        return
    ema = frame["close"].ewm(span=21, adjust=False).mean()

    if show_vumanchu:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            row_heights=[0.7, 0.3], vertical_spacing=0.03)
    else:
        fig = make_subplots(rows=1, cols=1)

    fig.add_trace(go.Candlestick(
        x=frame.index, open=frame["open"], high=frame["high"], low=frame["low"],
        close=frame["close"], name=f"{coin}/{base}"), row=1, col=1)
    fig.add_trace(go.Scatter(x=frame.index, y=ema, name="EMA21",
                             line=dict(color="orange", width=1)), row=1, col=1)

    if show_vumanchu:
        # Signals only on closed candles — the forming candle repaints (plan 4.7).
        closed = frame.iloc[:-1]
        res = VuManChuCipherB().compute(closed)
        if res.panes:
            fig.add_trace(go.Scatter(x=closed.index, y=res.panes["wt1"], name="WT1",
                                     line=dict(color="#4da6ff", width=1)), row=2, col=1)
            fig.add_trace(go.Scatter(x=closed.index, y=res.panes["wt2"], name="WT2",
                                     line=dict(color="#b366ff", width=1),
                                     fill="tonexty"), row=2, col=1)
            fig.add_trace(go.Bar(x=closed.index, y=res.panes["mfi"], name="MFI",
                                 marker_color="#4caf50", opacity=0.4), row=2, col=1)
            fig.add_hline(y=53, line=dict(color="#555", dash="dot"), row=2, col=1)
            fig.add_hline(y=-53, line=dict(color="#555", dash="dot"), row=2, col=1)
        for m in res.markers:
            stl = _MARKER_STYLE.get(m.kind, {})
            fig.add_trace(go.Scatter(
                x=[m.ts], y=[m.price], mode="markers", name=m.kind,
                marker=dict(size=11, **stl), showlegend=False), row=1, col=1)
        sig = ", ".join(k for k, v in res.signals.items() if v) or "none"
        st.caption(f"VuManChu latest signals: {sig}")

    fig.update_layout(height=620, xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=30, b=10), showlegend=True,
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
    alerts_view.sidebar_watch()

    if not (coins and bases and timeframes):
        st.warning("Pick at least one coin, base and timeframe.")
        return

    df = build(tuple(coins), tuple(bases), tuple(timeframes), liquidity_gate)

    # -- regime header --------------------------------------------------------
    reg = svc.regime(df)
    c1, c2, c3 = st.columns(3)
    c1.metric("Market regime", reg.label.replace("_", " ").title())
    c2.metric("BTC 1d", reg.btc_trend.get("1d", "—"))
    b1d = reg.breadth.get("1d", float("nan"))
    c3.metric("Breadth 1d (% bull vs USDT)",
              f"{b1d:.0f}%" if b1d == b1d else "—")
    trade_hours_view.render()

    (tab_screen, tab_report, tab_filter, tab_sector, tab_chart, tab_bt,
     tab_journal) = st.tabs(
        ["Screener", "Report", "Filters", "Sectors", "Chart", "Backtest",
         "Journal"])

    with tab_screen:
        for base in bases:
            st.subheader(f"vs {base}")
            render_heatmap(df, base, timeframes)

    with tab_report:
        st.caption("Coins bullish on ALL selected timeframes at once, with recent "
                   "VuManChu divergences per timeframe. 💎 = fully aligned, "
                   "🔥 = bull divergence on 2+ timeframes.")
        rc1, rc2, rc3, rc4 = st.columns([1, 2, 1, 1])
        rbase = rc1.selectbox("Base", bases, key="rep_base",
                              index=bases.index("USDT") if "USDT" in bases else 0)
        default_tfs = [t for t in ("15m", "4h", "1d", "1w") if t in timeframes] \
            or timeframes
        rtfs = rc2.multiselect("Timeframes (all must be bull)", timeframes,
                               default=default_tfs, key="rep_tfs")
        lookback = rc3.slider("Div lookback (candles)", 3, 40, 10, key="rep_lb")
        only_aligned = rc4.checkbox("Only fully aligned", value=False,
                                    key="rep_all")
        if not rtfs:
            st.warning("Pick at least one timeframe.")
        else:
            rdf = build_report(tuple(coins), rbase, tuple(rtfs), lookback,
                               only_aligned)
            if rdf.empty:
                st.info("No coins matched.")
            else:
                disp = pd.DataFrame(index=rdf["coin"])
                badges = []
                for _, r in rdf.iterrows():
                    b = ("💎" if r["all_bull"] else "") + \
                        ("🔥" if r["multi_tf_bull_div"] else "")
                    badges.append(b)
                disp[""] = badges
                for tf in rtfs:
                    cells = []
                    for _, r in rdf.iterrows():
                        s = r[f"strength_{tf}"]
                        cells.append(_cell_text(
                            r[f"dir_{tf}"],
                            float(s) if s is not None else float("nan")))
                    disp[tf] = cells
                    divs = []
                    for _, r in rdf.iterrows():
                        d = r[f"div_{tf}"]
                        divs.append({"bull": "🟢 div", "bear": "🔴 div",
                                     "bull+bear": "🟢🔴 div"}.get(d, ""))
                    disp[f"{tf} div"] = divs
                disp["score"] = rdf["score"].values
                st.dataframe(disp, use_container_width=True)
                aligned = rdf[rdf["all_bull"]]["coin"].tolist()
                multi = rdf[rdf["multi_tf_bull_div"]]["coin"].tolist()
                m1, m2 = st.columns(2)
                m1.metric("Fully aligned bull", len(aligned),
                          ", ".join(aligned) if aligned else None)
                m2.metric("Multi-TF bull divergence", len(multi),
                          ", ".join(multi) if multi else None)

    with tab_filter:
        st.caption("Combine conditions with AND to scan. Presets are saved filters.")
        preset = st.selectbox("Preset", ["(custom)"] + list(filters_mod.PRESETS))
        if preset != "(custom)":
            base = st.selectbox("Base", bases, key="preset_base")
            factory = filters_mod.PRESETS[preset]
            # multi_base_strength ANDs a tuple of bases; the others take one base
            flt = factory() if preset == "multi_base_strength" else factory(base)
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
        show_vmc = st.checkbox("VuManChu Cipher B", value=True)
        fut = futures_map().get(coin)
        if fut:
            st.caption(f"Perp funding: {fut[0] * 100:.4f}% · {fut[1].replace('_', ' ')}")
        if coin == base:
            st.info("Pick a base different from the coin.")
        else:
            render_chart(svc, coin, base, tf, show_vumanchu=show_vmc)

    with tab_bt:
        st.caption("Replay a signal historically: forward return after each fire.")
        bc1, bc2, bc3, bc4 = st.columns(4)
        bcoin = bc1.selectbox("Coin", coins, key="bt_coin")
        bbase_opts = [b for b in bases if b != bcoin] or bases
        bbase = bc2.selectbox("Base", bbase_opts, key="bt_base")
        btf = bc3.selectbox("Timeframe", timeframes, key="bt_tf")
        bdir = bc4.selectbox("Direction", [rs_mod.BULL, rs_mod.BEAR], key="bt_dir")
        horizon = st.slider("Forward horizon (candles)", 3, 40, 10)
        if bcoin != bbase:
            frame = svc.ratio_frame(bcoin, bbase, btf)
            if frame.empty:
                st.warning("No candles for that pair/timeframe.")
            else:
                stats = backtest_signal(frame["close"], cfg.classifier_params(btf),
                                        direction=bdir, horizon=horizon)
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Signals", stats.n)
                m2.metric("Hit rate", f"{stats.hit_rate:.0%}" if stats.n else "—")
                m3.metric("Mean fwd", f"{stats.mean_fwd:+.2f}%" if stats.n else "—")
                m4.metric("Median fwd", f"{stats.median_fwd:+.2f}%" if stats.n else "—")

    with tab_journal:
        st.caption("Fired signals (from `python -m backend.cli scan` / watch).")
        j = SignalJournal()
        hist = j.to_frame(limit=200)
        counts = j.preset_counts()
        j.close()
        if counts.empty:
            st.info("No signals recorded yet. Run a scan or the alert scheduler.")
        else:
            st.dataframe(counts, use_container_width=True, hide_index=True)
            st.dataframe(hist, use_container_width=True, hide_index=True)


main()
