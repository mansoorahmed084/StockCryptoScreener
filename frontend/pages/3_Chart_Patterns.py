"""Chart patterns — trendlines, flat levels, Fibonacci and patterns drawn
automatically on any Binance USDT perpetual.

The detection is in backend/screener/patterns.py; this file only draws it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.config import load_config, timeframe_to_seconds  # noqa: E402
from backend.indicators.vumanchu import VuManChuCipherB  # noqa: E402
from backend.screener import patterns as pt  # noqa: E402
from backend.service import ScreenerService  # noqa: E402

st.set_page_config(page_title="Chart patterns", layout="wide")

TIMEFRAMES = ["15m", "1h", "4h", "1d"]
PROJECT = 0.15          # lines run this share of the window past the last candle

# Categorical slots from the dataviz reference palette, one set per theme.
# Candles keep the dashboard's polarity: blue up, red down.
_DARK = dict(up="#3987e5", down="#e66767", support="#199e70", resistance="#d95926",
             fib="#c98500", ob="#9085e9", ob_fill="rgba(144,133,233,0.16)",
             level="#898781", ink="#ffffff", ink2="#c3c2b7",
             muted="#898781", grid="#2c2c2a", label_bg="rgba(26,26,25,0.85)",
             fill_bull="rgba(25,158,112,0.12)", fill_bear="rgba(217,89,38,0.12)",
             fill_neutral="rgba(137,135,129,0.12)")
_LIGHT = dict(up="#2a78d6", down="#e34948", support="#1baf7a", resistance="#eb6834",
              fib="#c98500", ob="#4a3aa7", ob_fill="rgba(74,58,167,0.12)",
              level="#898781", ink="#0b0b0b", ink2="#52514e",
              muted="#898781", grid="#e1e0d9", label_bg="rgba(252,252,251,0.85)",
              fill_bull="rgba(27,175,122,0.12)", fill_bear="rgba(235,104,52,0.12)",
              fill_neutral="rgba(137,135,129,0.12)")


# The VuManChu pane copies TradingView's Cipher B colours on purpose (same in
# both themes), so it looks like the indicator traders already read.
VMC = dict(mfi_up="rgba(62,225,69,0.35)", mfi_down="rgba(255,61,46,0.35)",
           wt2="#4994ec", sell="#ff3d2e", buy="#3ee145", div="#c71585")


def palette() -> dict:
    try:
        return _LIGHT if st.context.theme.type == "light" else _DARK
    except AttributeError:
        return _DARK


@st.cache_resource(show_spinner=False)
def get_service() -> ScreenerService:
    return ScreenerService(load_config(), refresh=False)


@st.cache_data(ttl=3600, show_spinner=False)
def perpetuals() -> dict[str, str]:
    return get_service().futures().perpetuals()


@st.cache_data(ttl=3600, show_spinner=False)
def top_coins() -> list[str]:
    try:
        return list(get_service().liquidation_coins(10))
    except Exception:
        return ["BTC", "ETH", "SOL", "XRP", "BNB"]


@st.cache_data(ttl=60, show_spinner="Loading candles…")
def candles(symbol: str, tf: str, n: int) -> pd.DataFrame:
    return get_service().futures().klines(symbol, tf, n)


@st.cache_data(ttl=300, show_spinner=False)
def daily_order_blocks(symbol: str) -> list[pt.OrderBlock]:
    return pt.order_blocks(get_service().futures().klines(symbol, "1d", 500))


def fmt(v: float) -> str:
    if v is None or not np.isfinite(v):
        return "—"
    return f"{v:,.2f}" if v >= 100 else f"{v:.6g}"


def pct(v: float, ref: float) -> str:
    return f"{(v / ref - 1) * 100:+.2f}%"


# -- chart ---------------------------------------------------------------------------
def build_figure(df: pd.DataFrame, a: pt.ChartAnalysis, tf: str, show: dict,
                 p: dict, title: str,
                 obs: list[pt.OrderBlock] | None = None) -> go.Figure:
    n = len(df)
    step = pd.Timedelta(seconds=timeframe_to_seconds(tf))
    proj = max(5, int(n * PROJECT))
    x_of = lambda i: df.index[0] + step * i          # bar index -> time
    end_i = n - 1 + proj
    last = float(df["close"].iloc[-1])

    rows = 1 + show["volume"] + show["vmc"]
    heights = [0.7] + ([0.1] if show["volume"] else []) + ([0.2] if show["vmc"] else [])
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.02,
                        row_heights=heights)
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        increasing=dict(line=dict(color=p["up"], width=1), fillcolor=p["up"]),
        decreasing=dict(line=dict(color=p["down"], width=1), fillcolor=p["down"]),
        name="Price", showlegend=False), row=1, col=1)

    def label(y: float, text: str, color: str) -> None:
        fig.add_annotation(x=1.0, xref="paper", xanchor="left", y=y, yref="y",
                           text=text, showarrow=False, bgcolor=p["label_bg"],
                           font=dict(size=11, color=color))

    # Daily order blocks: purple zones from their candle to the right edge,
    # drawn on every timeframe (from the chart's left edge if older).
    lo_view, hi_view = float(df["low"].min()), float(df["high"].max())
    pad_view = (hi_view - lo_view) * 0.08
    if show.get("obs") and obs:
        for ob in obs:
            if ob.top < lo_view - pad_view or ob.bottom > hi_view + pad_view:
                continue                              # off the visible range
            x0 = max(ob.ts, df.index[0])
            fig.add_shape(type="rect", x0=x0, x1=x_of(end_i), y0=ob.bottom, y1=ob.top,
                          fillcolor=p["ob_fill"], line=dict(color=p["ob"], width=1),
                          layer="below", row=1, col=1)
            label((ob.bottom + ob.top) / 2, f"{ob.label}<br>{fmt(ob.bottom)}–{fmt(ob.top)}",
                  p["ob"])

    # Pattern area first, so lines draw on top of it.
    if show["patterns"]:
        for pat in a.patterns:
            fill = {"bullish": p["fill_bull"], "bearish": p["fill_bear"]}.get(
                pat.bias, p["fill_neutral"])
            if pat.upper and pat.lower:
                xs = [x_of(pat.start), x_of(end_i), x_of(end_i), x_of(pat.start)]
                ys = [pat.upper.at(pat.start), pat.upper.at(end_i),
                      pat.lower.at(end_i), pat.lower.at(pat.start)]
                fig.add_trace(go.Scatter(x=xs, y=ys, fill="toself", fillcolor=fill,
                                         line=dict(width=0), hoverinfo="skip",
                                         showlegend=False), row=1, col=1)
                fig.add_annotation(x=x_of(pat.start), y=pat.upper.at(pat.start),
                                   yref="y", text=f"<b>{pat.name}</b> · {pat.status}",
                                   showarrow=False, yanchor="bottom", xanchor="left",
                                   bgcolor=p["label_bg"], font=dict(size=12, color=p["ink"]))
            if pat.points:                                # double top / bottom
                top = pat.bias == "bearish"
                fig.add_trace(go.Scatter(
                    x=[df.index[i] for i, _ in pat.points], y=[v for _, v in pat.points],
                    mode="markers+text", text=["T" if top else "B"] * len(pat.points),
                    textposition="top center" if top else "bottom center",
                    textfont=dict(color=p["ink"], size=11),
                    marker=dict(size=10, color=p["resistance"] if top else p["support"],
                                line=dict(width=1, color=p["ink"])),
                    hovertemplate=f"{pat.name}<extra></extra>", showlegend=False),
                    row=1, col=1)
            for lvl, tgt, arrow in ((pat.breakout_up, pat.target_up, "↑"),
                                    (pat.breakout_down, pat.target_down, "↓")):
                if np.isfinite(tgt):
                    fig.add_trace(go.Scatter(
                        x=[df.index[-1], x_of(end_i)], y=[tgt, tgt], mode="lines",
                        line=dict(color=p["ink2"], width=1, dash="dot"),
                        hovertemplate=f"{pat.name} target {arrow} %{{y:,.6g}}<extra></extra>",
                        showlegend=False), row=1, col=1)
                    label(tgt, f"target {arrow} {fmt(tgt)}", p["ink2"])
            if pat.name.startswith("Double"):
                neck = pat.breakout_down if pat.bias == "bearish" else pat.breakout_up
                fig.add_trace(go.Scatter(
                    x=[df.index[pat.start], x_of(end_i)], y=[neck, neck], mode="lines",
                    line=dict(color=p["ink2"], width=1, dash="dash"),
                    hovertemplate="neckline %{y:,.6g}<extra></extra>", showlegend=False),
                    row=1, col=1)

    if show["fib"] and a.fib:
        f = a.fib
        x0 = df.index[min(f.start_i, f.end_i)]
        gp = sorted([f.levels[0.5], f.levels[0.618]])      # the "golden pocket"
        fig.add_shape(type="rect", x0=x0, x1=x_of(end_i), y0=gp[0], y1=gp[1],
                      fillcolor=p["fib"], opacity=0.08, line_width=0, row=1, col=1)
        for r, v in f.levels.items():
            fig.add_trace(go.Scatter(
                x=[x0, x_of(end_i)], y=[v, v], mode="lines",
                line=dict(color=p["fib"], width=1, dash="dot"),
                hovertemplate=f"Fib {r:g}: %{{y:,.6g}}<extra></extra>", showlegend=False),
                row=1, col=1)
            label(v, f"{r:g} · {fmt(v)}", p["fib"])

    if show["levels"]:
        for lv in a.levels:
            color = p["resistance"] if lv.kind == pt.RESISTANCE else p["support"]
            fig.add_trace(go.Scatter(
                x=[df.index[lv.first], x_of(end_i)], y=[lv.price, lv.price], mode="lines",
                line=dict(color=color, width=1, dash="dash"),
                hovertemplate=f"{lv.kind} level %{{y:,.6g}} · {lv.touches} touches"
                              "<extra></extra>", showlegend=False), row=1, col=1)
            label(lv.price, f"{'R' if lv.kind == pt.RESISTANCE else 'S'} {fmt(lv.price)} "
                            f"×{lv.touches}", color)

    if show["trendlines"]:
        for lines, color in ((a.resistances, p["resistance"]), (a.supports, p["support"])):
            for k, ln in enumerate(lines):
                fig.add_trace(go.Scatter(
                    x=[df.index[ln.i0], x_of(end_i)], y=[ln.p0, ln.at(end_i)], mode="lines",
                    line=dict(color=color, width=2.2 if k == 0 else 1.2,
                              dash="dot" if ln.broken else
                              "solid" if k == 0 else "dash"),
                    hovertemplate=f"{ln.kind} line · {ln.touches} touches"
                                  f"{' · BROKEN' if ln.broken else ''}<br>"
                                  f"now {fmt(ln.at(n - 1))}<extra></extra>",
                    showlegend=False), row=1, col=1)

    row = 2
    if show["volume"]:
        colors = np.where(df["close"] >= df["open"], p["up"], p["down"])
        fig.add_trace(go.Bar(x=df.index, y=df["volume"], marker_color=colors,
                             opacity=0.6, showlegend=False,
                             hovertemplate="Volume %{y:,.0f}<extra></extra>"),
                      row=row, col=1)
        fig.update_yaxes(showticklabels=False, showgrid=False, row=row, col=1)
        row += 1
    if show["vmc"]:
        closed = df.iloc[:-1]                   # the forming candle repaints
        res = VuManChuCipherB().compute(closed)
        if res.panes:
            # Styled after TradingView's VuManChu Cipher B, so it reads like the
            # pane the user already knows: green / red money flow, a light WT1
            # and a blue WT2, sell dots on top, buy dots below.
            mfi, wt1, wt2 = res.panes["mfi"], res.panes["wt1"], res.panes["wt2"]
            for part, color in ((mfi.clip(lower=0), VMC["mfi_up"]),
                                (mfi.clip(upper=0), VMC["mfi_down"])):
                fig.add_trace(go.Scatter(x=closed.index, y=part, fill="tozeroy",
                                         line=dict(width=0), fillcolor=color,
                                         hoverinfo="skip", showlegend=False),
                              row=row, col=1)
            fig.add_trace(go.Scatter(x=closed.index, y=wt1, name="WT1",
                                     line=dict(color=p["ink"], width=1.3),
                                     hovertemplate="WT1 %{y:.1f}<extra></extra>",
                                     showlegend=False), row=row, col=1)
            fig.add_trace(go.Scatter(x=closed.index, y=wt2, name="WT2",
                                     line=dict(color=VMC["wt2"], width=1.3),
                                     hovertemplate="WT2 %{y:.1f}<extra></extra>",
                                     showlegend=False), row=row, col=1)
            fig.add_hline(y=0, line=dict(color=p["muted"], width=1), row=row, col=1)
            for y, dash in ((60, "solid"), (53, "dot"), (-53, "dot"), (-60, "solid")):
                fig.add_hline(y=y, line=dict(color=VMC["sell"] if y > 0 else VMC["buy"],
                                             width=1, dash=dash), opacity=0.6,
                              row=row, col=1)
            styles = {"sell": (VMC["sell"], 8, "WT sell"),
                      "buy": (VMC["buy"], 8, "WT buy"),
                      "bear_div": (VMC["div"], 11, "Bearish divergence"),
                      "bull_div": (VMC["buy"], 11, "Bullish divergence")}
            for kind, (color, size, text) in styles.items():
                ms = [m for m in res.markers if m.kind == kind]
                if ms:
                    fig.add_trace(go.Scatter(
                        x=[m.ts for m in ms], y=[wt2.get(m.ts, 0) for m in ms],
                        mode="markers", marker=dict(size=size, color=color,
                                                    line=dict(width=0)),
                        hovertemplate=f"{text}<extra></extra>", showlegend=False),
                        row=row, col=1)
        fig.update_yaxes(showgrid=False, tickfont=dict(color=p["muted"]),
                         range=[-100, 100], row=row, col=1)

    lo = float(df["low"].min())
    hi = float(df["high"].max())
    pad = (hi - lo) * 0.08
    fig.update_yaxes(range=[lo - pad, hi + pad], gridcolor=p["grid"], zeroline=False,
                     tickfont=dict(color=p["muted"]), tickformat=",.6~g",
                     automargin=True, row=1, col=1)
    fig.update_xaxes(showgrid=False, tickfont=dict(color=p["muted"]),
                     range=[df.index[0], x_of(end_i)], rangeslider_visible=False)
    fig.update_layout(height=760 if rows > 1 else 620, margin=dict(l=60, r=110, t=40, b=10),
                      title=dict(text=title, font=dict(size=14, color=p["ink2"])),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      hovermode="closest", dragmode="pan")
    return fig


# -- page ----------------------------------------------------------------------------
def main():
    p = palette()
    perps = perpetuals()
    tops = [c for c in top_coins() if c in perps]
    options = tops + sorted(c for c in perps if c not in tops)

    with st.sidebar:
        st.header("Controls")
        # The scanner opens a chart by setting these keys, then switching here.
        if st.session_state.get("cp_coin") not in options:
            st.session_state["cp_coin"] = "BTC" if "BTC" in options else options[0]
        st.session_state.setdefault("cp_tf", "1h")
        coin = st.selectbox("Coin", options, key="cp_coin",
                            format_func=lambda c: f"{c}  ({perps[c]})",
                            help="Type to search every Binance USDT perpetual.")
        tf = st.radio("Timeframe", TIMEFRAMES, key="cp_tf", horizontal=True)
        n = st.slider("Candles", 100, 1000, 300, step=50)
        swing = st.select_slider("Swing size", ["auto", 3, 4, 5, 6, 8, 10], value="auto",
                                 help="How many candles each side a swing high / low must "
                                      "beat. Bigger = fewer, more important lines.")
        st.subheader("Draw")
        show = {
            "obs": st.checkbox("Daily order blocks", True,
                               help="Purple zones: the last candle before a sharp "
                                    "daily move. Supply above price, demand below."),
            "trendlines": st.checkbox("Trendlines", True),
            "levels": st.checkbox("Flat support / resistance", True),
            "fib": st.checkbox("Fibonacci", True),
            "patterns": st.checkbox("Patterns", True),
            "volume": st.checkbox("Volume", True),
            "vmc": st.checkbox("VuManChu Cipher B", True),
        }
        if st.button("🔄 Refresh data"):
            st.cache_data.clear()
            get_service().futures()._cache.clear()

    symbol = perps[coin]
    df = candles(symbol, tf, n)
    a = pt.analyse(df, pivot=None if swing == "auto" else int(swing))
    last = float(df["close"].iloc[-1])

    st.title("Chart patterns")
    st.caption("Trendlines, flat levels, Fibonacci and patterns found automatically "
               "from swing highs and lows. Like hand-drawn lines, they describe the "
               "chart shown; they do not predict it. Not financial advice.")
    obs = daily_order_blocks(symbol) if show["obs"] else []
    st.plotly_chart(build_figure(df, a, tf, show, p,
                                 f"{symbol} · {tf} · {n} candles · last {fmt(last)}",
                                 obs),
                    width="stretch", theme=None,
                    config={"displayModeBar": True, "scrollZoom": True,
                            "modeBarButtonsToRemove": ["lasso2d", "select2d"]})
    st.caption("Green lines: support. Orange: resistance. The thick line is the "
               "strongest; a dotted one was broken in the last few candles. Purple "
               "zones: daily order blocks. Yellow dotted: Fibonacci, with the "
               "0.5–0.618 band shaded. Drag to pan, scroll to zoom.")

    # -- what the chart shows -------------------------------------------------------------
    st.subheader("What the chart shows")
    if a.patterns:
        for pat in a.patterns:
            parts = [f"**{pat.name}** ({pat.bias}), {pat.status}."]
            if np.isfinite(pat.breakout_up):
                parts.append(f"Break above **{fmt(pat.breakout_up)}** "
                             f"({pct(pat.breakout_up, last)})"
                             + (f" targets **{fmt(pat.target_up)}**."
                                if np.isfinite(pat.target_up) else "."))
            if np.isfinite(pat.breakout_down):
                parts.append(f"Break below **{fmt(pat.breakout_down)}** "
                             f"({pct(pat.breakout_down, last)})"
                             + (f" targets **{fmt(pat.target_down)}**."
                                if np.isfinite(pat.target_down) else "."))
            st.markdown("- " + " ".join(parts))
    else:
        st.markdown("- No clear pattern between the current support and resistance lines.")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Trendlines**")
        rows = [{"Line": ln.kind.title(), "Now": fmt(ln.at(len(df) - 1)),
                 "Distance": pct(ln.at(len(df) - 1), last), "Touches": ln.touches,
                 "Status": "broken" if ln.broken else "holding"}
                for ln in a.resistances + a.supports]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with c2:
        st.markdown("**Flat levels**")
        rows = [{"Level": lv.kind.title(), "Price": fmt(lv.price),
                 "Distance": pct(lv.price, last), "Touches": lv.touches}
                for lv in sorted(a.levels, key=lambda lv: -lv.price)]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with c3:
        st.markdown("**Fibonacci**")
        if a.fib:
            st.caption(f"{'Up' if a.fib.direction == 'up' else 'Down'} leg "
                       f"{fmt(a.fib.start)} → {fmt(a.fib.end)}")
            rows = [{"Ratio": f"{r:g}", "Price": fmt(v), "Distance": pct(v, last)}
                    for r, v in sorted(a.fib.levels.items(), key=lambda kv: -kv[1])]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    if obs:
        st.markdown("**Daily order blocks** (nearest first on each side)")
        rows = [{"Zone": f"{fmt(ob.bottom)}–{fmt(ob.top)}", "Acts as": ob.role,
                 "Kind": ob.label.replace("Daily ", ""),
                 "Formed": f"{ob.ts:%Y-%m-%d}", "Move after": f"{ob.move_pct:+.0f}%",
                 "Distance": "inside" if ob.bottom <= last <= ob.top else
                 pct(ob.bottom if ob.bottom > last else ob.top, last)}
                for ob in sorted(obs, key=lambda o: -o.top)]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("An order block is the last candle before a sharp daily move that "
                   "broke the recent low (supply) or high (demand). \"Flipped\" means "
                   "price later closed through it, so it now works the other way.")


main()
