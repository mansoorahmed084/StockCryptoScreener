"""Coins vs BTC — which coins are stronger than BTC, and where each one trends.

Streamlit lists this file as a page of frontend/streamlit_app.py. The logic is
in backend/screener/btc_strength.py; this file only draws it.
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

from backend.config import load_config  # noqa: E402
from backend.screener import btc_strength as bs  # noqa: E402
from backend.screener import rs as rs_mod  # noqa: E402
from backend.service import ScreenerService  # noqa: E402

st.set_page_config(page_title="Coins vs BTC", layout="wide")

ALL_TIMEFRAMES = list(bs.DEFAULT_TIMEFRAMES)
WINDOW_LABEL = {"1h": "1h", "4h": "4h", "1d": "24h", "1w": "7d", "1M": "30d"}
HORIZON_LABEL = {"short": "Short", "medium": "Medium", "long": "Long"}
TREND_TEXT = {bs.UP: "▲ Up", bs.DOWN: "▼ Down", bs.SIDEWAYS: "► Flat",
              rs_mod.UNKNOWN: "—"}
TREND_VALUE = {bs.UP: 1.0, bs.DOWN: -1.0, bs.SIDEWAYS: 0.0}
STATE_TEXT = {rs_mod.BULL: "stronger than BTC", rs_mod.BEAR: "weaker than BTC",
              rs_mod.NEUTRAL: "no clear edge", rs_mod.UNKNOWN: "no data"}
BTC_D_STATE_TEXT = {rs_mod.BULL: "BTC gaining on alts",
                    rs_mod.BEAR: "BTC losing to alts",
                    rs_mod.NEUTRAL: "no clear edge", rs_mod.UNKNOWN: "no data"}


# -- theme ---------------------------------------------------------------------
# Diverging polarity: blue = stronger / up, red = weaker / down, gray = neither.
# Values from the dataviz reference palette, one set per mode.
_LIGHT = dict(pos="#2a78d6", neg="#e34948", mid="#f0efec", ink="#0b0b0b",
              ink2="#52514e", muted="#898781", grid="#e1e0d9")
_DARK = dict(pos="#3987e5", neg="#e66767", mid="#383835", ink="#ffffff",
             ink2="#c3c2b7", muted="#898781", grid="#2c2c2a")


def palette() -> dict[str, str]:
    try:
        return _LIGHT if st.context.theme.type == "light" else _DARK
    except AttributeError:          # older Streamlit: no theme info
        return _DARK


def colorscale(p: dict[str, str]) -> list[list]:
    return [[0.0, p["neg"]], [0.5, p["mid"]], [1.0, p["pos"]]]


# -- data ----------------------------------------------------------------------
@st.cache_resource(show_spinner="Connecting to exchange…")
def get_service() -> ScreenerService:
    return ScreenerService(load_config())


@st.cache_data(ttl=60, show_spinner="Comparing coins with BTC…")
def get_board(coins: tuple[str, ...], timeframes: tuple[str, ...],
              liquidity_gate: bool) -> bs.Board:
    return get_service().btc_board(list(coins), list(timeframes),
                                   liquidity_gate=liquidity_gate)


# -- formatting ------------------------------------------------------------------
def _pct(v: float) -> str:
    return "—" if pd.isna(v) else f"{v:+.1f}%"


def _turning(direction: str, strength: float) -> bool:
    """The filtered state holds for a candle or two after the latest score
    flips sign (noise filter); call that "turning"."""
    return pd.notna(strength) and (
        (direction == rs_mod.BULL and strength <= -0.1)
        or (direction == rs_mod.BEAR and strength >= 0.1))


def _strength_text(direction: str, strength: float) -> str:
    if direction == rs_mod.UNKNOWN or pd.isna(strength):
        return "—"
    if direction == rs_mod.NEUTRAL:
        return "·"
    arrow = "▲" if direction == rs_mod.BULL else "▼"
    if _turning(direction, strength):
        return f"{arrow} turning"
    return f"{arrow} {abs(strength):.1f}"


def _state_z(direction: str, strength: float) -> float:
    """Cell color follows the state, so it always matches the arrow. The
    score only sets how deep the color is (0.75..3, never near-gray)."""
    if direction == rs_mod.NEUTRAL:
        return 0.0
    if direction not in (rs_mod.BULL, rs_mod.BEAR) or pd.isna(strength):
        return np.nan
    depth = 0.75
    if not _turning(direction, strength):
        depth += 0.75 * min(abs(strength), 3.0)
    return depth if direction == rs_mod.BULL else -depth


def _trend_line(trends: pd.DataFrame, asset: str) -> str:
    sub = trends[trends["asset"] == asset].set_index("horizon")
    parts = [f"{HORIZON_LABEL.get(h, h)} {TREND_TEXT.get(r['state'], '—')}"
             for h, r in sub.iterrows()]
    return " · ".join(parts) or "—"


def _market_read(board: bs.Board) -> str:
    s = board.strength[board.strength["asset"] == bs.BTC_D].set_index("timeframe")
    dirs = [s.loc[tf, "direction"] for tf in ("1d", "1w") if tf in s.index]
    if dirs and all(d == rs_mod.BEAR for d in dirs):
        return "Alts are taking share from BTC (BTC.D falling on 1d and 1w)."
    if dirs and all(d == rs_mod.BULL for d in dirs):
        return "BTC is taking share from alts (BTC.D rising on 1d and 1w)."
    return "No clear rotation: BTC.D is mixed on 1d and 1w."


# -- charts ------------------------------------------------------------------------
def board_figure(board: bs.Board, mode: str, p: dict[str, str]) -> go.Figure:
    """Strength heatmap (left) and trend heatmap (right), rows aligned."""
    order = board.order
    tfs = board.timeframes
    horizons = list(dict.fromkeys(board.trends["horizon"]))
    s = board.strength.set_index(["asset", "timeframe"])
    t = board.trends.set_index(["asset", "horizon"])

    # "% vs BTC" colors are scaled per column, so a 1h move and a 1M move
    # both fill the range; the text shows the real number.
    col_scale = {}
    for tf in tfs:
        vals = board.strength.loc[board.strength["timeframe"] == tf, "pct_vs_btc"]
        m = float(vals.abs().max()) if vals.notna().any() else 0.0
        col_scale[tf] = m if m > 0 else 1.0

    z, text, hover = [], [], []
    for asset in order:
        zr, tr, hr = [], [], []
        for tf in tfs:
            if asset == bs.BTC:
                zr.append(np.nan)
                tr.append("benchmark" if tf == tfs[0] else "")
                hr.append("BTC is the benchmark.<br>See the BTC.D row for BTC's strength.")
                continue
            if (asset, tf) not in s.index:
                zr.append(np.nan)
                tr.append("—")
                hr.append("no data")
                continue
            row = s.loc[(asset, tf)]
            d, st_, pct = row["direction"], row["strength"], row["pct_vs_btc"]
            if mode == "pct":
                zr.append(np.nan if pd.isna(pct) else 3 * pct / col_scale[tf])
                tr.append(_pct(pct))
            else:
                zr.append(_state_z(d, st_))
                tr.append(_strength_text(d, st_))
            states = BTC_D_STATE_TEXT if asset == bs.BTC_D else STATE_TEXT
            vs = "BTC.D change" if asset == bs.BTC_D else "vs BTC"
            reason = f"<br>Reason: {row['reason']}" if d == rs_mod.UNKNOWN and row["reason"] else ""
            turning = ("<br>Turning: the latest score points the other way."
                       "<br>The state flips only if that holds (noise filter)."
                       if _turning(d, st_) else "")
            hr.append(f"<b>{asset} · {tf}</b><br>{states.get(d, d)}"
                      f"<br>Latest score: {'—' if pd.isna(st_) else f'{st_:+.2f}'}"
                      f"<br>{vs}, last {WINDOW_LABEL.get(tf, tf)}: {_pct(pct)}"
                      f"{turning}{reason}")
        z.append(zr)
        text.append(tr)
        hover.append(hr)

    tz, ttext, thover = [], [], []
    for asset in order:
        zr, tr, hr = [], [], []
        for h in horizons:
            if (asset, h) not in t.index:
                zr.append(np.nan)
                tr.append("—")
                hr.append("no data")
                continue
            row = t.loc[(asset, h)]
            state = row["state"]
            zr.append(TREND_VALUE.get(state, np.nan))
            tr.append(TREND_TEXT.get(state, "—"))
            dist = "" if pd.isna(row["dist_pct"]) else \
                f"<br>Close is {abs(row['dist_pct']):.1f}% " \
                f"{'above' if row['dist_pct'] >= 0 else 'below'} EMA{row['ema']}"
            price = "BTC.D" if asset == bs.BTC_D else f"{asset}/USDT"
            hr.append(f"<b>{price} · {HORIZON_LABEL.get(h, h)} term</b>"
                      f"<br>{TREND_TEXT.get(state, '—')} (daily close vs EMA{row['ema']}){dist}")
        tz.append(zr)
        ttext.append(tr)
        thover.append(hr)

    fig = make_subplots(rows=1, cols=2, shared_yaxes=True,
                        column_widths=[0.6, 0.4], horizontal_spacing=0.03,
                        subplot_titles=(
                            "Strength vs BTC" if mode == "strength"
                            else "% vs BTC over the last 1h / 4h / 24h / 7d / 30d",
                            "Price trend (daily EMA 20 / 50 / 200)"))
    common = dict(colorscale=colorscale(p), showscale=False, xgap=2, ygap=2,
                  texttemplate="%{text}", hoverongaps=False,
                  hovertemplate="%{customdata}<extra></extra>",
                  textfont=dict(size=13))
    fig.add_trace(go.Heatmap(z=z, x=tfs, y=order, text=text, customdata=hover,
                             zmin=-3, zmax=3, **common), row=1, col=1)
    fig.add_trace(go.Heatmap(z=tz, x=[HORIZON_LABEL.get(h, h) for h in horizons],
                             y=order, text=ttext, customdata=thover,
                             zmin=-1.6, zmax=1.6, **common), row=1, col=2)
    # Line between the benchmark rows (BTC.D, BTC) and the coins.
    fig.add_hline(y=1.5, line=dict(color=p["muted"], width=1.5))
    fig.update_yaxes(autorange="reversed", tickfont=dict(color=p["ink"], size=13),
                     showgrid=False, zeroline=False, ticks="", automargin=True)
    fig.update_xaxes(side="top", tickfont=dict(color=p["ink2"], size=12),
                     showgrid=False, zeroline=False, ticks="")
    fig.update_annotations(font=dict(color=p["ink2"], size=13), yshift=22)
    fig.update_layout(height=90 + 34 * len(order),
                      margin=dict(l=70, r=10, t=70, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color=p["ink"]))
    return fig


def pct_bar_figure(board: bs.Board, tf: str, p: dict[str, str]) -> go.Figure:
    df = board.strength[(board.strength["timeframe"] == tf)
                        & (board.strength["asset"] != bs.BTC_D)]
    df = df.dropna(subset=["pct_vs_btc"]).sort_values("pct_vs_btc")
    colors = [p["pos"] if v >= 0 else p["neg"] for v in df["pct_vs_btc"]]
    fig = go.Figure(go.Bar(
        x=df["pct_vs_btc"], y=df["asset"], orientation="h",
        marker=dict(color=colors, line=dict(width=0)),
        text=[_pct(v) for v in df["pct_vs_btc"]], textposition="outside",
        textfont=dict(color=p["ink2"], size=12), cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>%{x:+.2f}% vs BTC<extra></extra>"))
    fig.add_vline(x=0, line=dict(color=p["muted"], width=1))
    # Fixed range with room on both sides for the outside value labels.
    lo = min(0.0, float(df["pct_vs_btc"].min())) if len(df) else 0.0
    hi = max(0.0, float(df["pct_vs_btc"].max())) if len(df) else 1.0
    pad = 0.18 * ((hi - lo) or 1.0)
    fig.update_xaxes(ticksuffix="%", gridcolor=p["grid"], zeroline=False,
                     tickfont=dict(color=p["muted"]),
                     range=[lo - (pad if lo < 0 else 0), hi + (pad if hi > 0 else 0)])
    fig.update_yaxes(tickfont=dict(color=p["ink"], size=13), automargin=True,
                     showgrid=False, ticks="")
    fig.update_layout(height=60 + 26 * max(len(df), 1), bargap=0.3,
                      margin=dict(l=60, r=20, t=10, b=30),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def legend_html(p: dict[str, str]) -> str:
    def chip(color: str, label: str) -> str:
        return (f"<span style='display:inline-block;width:12px;height:12px;"
                f"border-radius:3px;background:{color};margin:0 6px -1px 14px'></span>"
                f"{label}")
    return ("<div style='font-size:0.85rem;opacity:0.85'>"
            + chip(p["pos"], "▲ stronger than BTC / uptrend")
            + chip(p["mid"], "· no clear edge / flat")
            + chip(p["neg"], "▼ weaker than BTC / downtrend")
            + "</div>")


# -- page --------------------------------------------------------------------------
def main():
    st.title("Coins vs BTC")
    st.caption("Which coins are stronger than BTC on each timeframe, and where "
               "each coin's own price is trending.")
    p = palette()

    with st.sidebar:
        st.header("Controls")
        svc = get_service()
        universe = [c for c in svc.universe() if c != bs.BTC]
        coins = st.multiselect("Coins", options=universe, default=universe)
        timeframes = st.multiselect("Timeframes", options=ALL_TIMEFRAMES,
                                    default=ALL_TIMEFRAMES)
        mode = st.radio("Cells show", ["strength", "pct"], horizontal=True,
                        format_func=lambda m: {"strength": "Strength score",
                                               "pct": "% vs BTC"}[m],
                        help="Strength score: noise-filtered trend of COIN/BTC "
                             "on closed candles (about -3 to +3). "
                             "% vs BTC: how much the coin beat or lagged BTC "
                             "over the last 1h / 4h / 24h / 7d / 30d, live.")
        liquidity_gate = st.checkbox("Liquidity gate", value=True,
                                     help="Hide coins whose USDT book trades "
                                          "less than the floor in config.yaml.")
        if st.button("🔄 Refresh data"):
            st.cache_data.clear()

    if not (coins and timeframes):
        st.warning("Pick at least one coin and one timeframe.")
        return
    timeframes = [t for t in ALL_TIMEFRAMES if t in timeframes]
    board = get_board(tuple(coins), tuple(timeframes), liquidity_gate)

    # -- header: BTC, BTC.D and the market read ------------------------------------
    c1, c2, c3 = st.columns([1, 1.3, 1.3])
    c1.metric("BTC.D now", "—" if board.btc_dominance_pct is None
              else f"{board.btc_dominance_pct:.1f}%",
              help="BTC's share of the whole crypto market cap (CoinGecko).")
    c2.markdown(f"**BTC trend**  \n{_trend_line(board.trends, bs.BTC)}")
    c3.markdown(f"**BTC.D trend**  \n{_trend_line(board.trends, bs.BTC_D)}")
    st.info(_market_read(board))

    # -- breadth: coins stronger than BTC per timeframe ------------------------------
    br = board.breadth()
    st.markdown("**Coins stronger than BTC**")
    cols = st.columns(len(br))
    for col, (_, r) in zip(cols, br.iterrows()):
        col.metric(r["timeframe"], f"{r['stronger']} / {r['known']}",
                   help=f"{r['weaker']} coins are weaker than BTC on "
                        f"{r['timeframe']}. Coins with no data are left out.")

    # -- main board -----------------------------------------------------------------
    st.markdown(legend_html(p), unsafe_allow_html=True)
    st.plotly_chart(board_figure(board, mode, p), width="stretch",
                    theme=None, config={"displayModeBar": False})
    st.caption("Rows: BTC.D and BTC first, then coins from strongest to weakest. "
               "BTC's strength comes from BTC.D (Binance BTCDOM index), because "
               "BTC cannot be measured against itself. Hover a cell for details.")

    # -- % vs BTC bar chart -------------------------------------------------------------
    st.subheader("How much each coin beat or lagged BTC")
    default_tf = "1d" if "1d" in timeframes else timeframes[0]
    bar_tf = st.radio("Window", timeframes, index=timeframes.index(default_tf),
                      horizontal=True,
                      format_func=lambda tf: f"last {WINDOW_LABEL.get(tf, tf)}")
    st.plotly_chart(pct_bar_figure(board, bar_tf, p), width="stretch",
                    theme=None, config={"displayModeBar": False})

    # -- table view -----------------------------------------------------------------------
    with st.expander("Table view"):
        s = board.strength
        table = pd.DataFrame(index=board.order)
        for tf in timeframes:
            sub = s[s["timeframe"] == tf].set_index("asset")
            table[f"{tf} score"] = sub["strength"].round(2)
            table[f"{tf} % vs BTC"] = sub["pct_vs_btc"].round(2)
        tr = board.trends.pivot(index="asset", columns="horizon", values="state")
        for h in tr.columns:
            table[f"{HORIZON_LABEL.get(h, h)} trend"] = tr[h]
        summ = board.summary().set_index("asset")
        table["TFs stronger"] = summ["beats"]
        table["TFs weaker"] = summ["lags"]
        st.dataframe(table, width="stretch")


main()
