"""Coins vs BTC / BTC.D — which coins are stronger than the benchmark, and
where each one trends.

Streamlit lists this file as a page of frontend/streamlit_app.py. The logic is
in backend/screener/btc_strength.py; this file only draws it.
"""
from __future__ import annotations

import sys
import time
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
from backend.watchlists import WatchlistStore, parse_symbols  # noqa: E402

st.set_page_config(page_title="Coins vs BTC", layout="wide")

ALL_TIMEFRAMES = list(bs.DEFAULT_TIMEFRAMES)
TOP_SIZES = [25, 50, 100, 200, 300, 500]
WINDOW_LABEL = {"1h": "1h", "4h": "4h", "1d": "24h", "1w": "7d", "1M": "30d"}
HORIZON_LABEL = {"short": "Short", "medium": "Medium", "long": "Long"}
TREND_TEXT = {bs.UP: "▲ Up", bs.DOWN: "▼ Down", bs.SIDEWAYS: "► Flat",
              rs_mod.UNKNOWN: "—"}
TREND_VALUE = {bs.UP: 1.0, bs.DOWN: -1.0, bs.SIDEWAYS: 0.0}
BTC_D_STATE_TEXT = {rs_mod.BULL: "BTC.D rising: BTC gaining on alts",
                    rs_mod.BEAR: "BTC.D falling: BTC losing to alts",
                    rs_mod.NEUTRAL: "no clear edge", rs_mod.UNKNOWN: "no data"}
NEW_LIST = "➕ New list"


def state_text(bench: str) -> dict[str, str]:
    return {rs_mod.BULL: f"stronger than {bench}",
            rs_mod.BEAR: f"weaker than {bench}",
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
    svc = ScreenerService(load_config())
    # Keep candles 2 minutes: switching BTC <-> BTC.D then reuses them.
    svc.ohlcv.cache_ttl = 120
    svc.dominance().cache_ttl = 120
    return svc


@st.cache_data(ttl=6 * 3600, show_spinner="Ranking coins by market cap…")
def top_coins(n: int) -> tuple[list[str], str]:
    return get_service().top_coins(n)


@st.cache_data(ttl=600, show_spinner=False)
def usdt_coins() -> list[str]:
    return get_service().usdt_coins()


@st.cache_resource
def board_cache() -> dict:
    return {}


def get_board(coins: tuple[str, ...], timeframes: tuple[str, ...],
              liquidity_gate: bool, benchmark: str) -> bs.Board:
    """Cached board. Big lists take about a minute, so they are kept longer
    and show a progress bar while they build."""
    cache = board_cache()
    key = (coins, timeframes, liquidity_gate, benchmark)
    ttl = 60 if len(coins) <= 50 else 300
    hit = cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    label = f"Comparing {len(coins)} coins with {benchmark}"
    bar = st.progress(0.0, text=f"{label}…")

    def progress(done: int, total: int) -> None:
        bar.progress(done / total, text=f"{label}… {done} / {total}")

    board = get_service().btc_board(list(coins), list(timeframes),
                                    benchmark=benchmark,
                                    liquidity_gate=liquidity_gate,
                                    progress=progress)
    bar.empty()
    if len(cache) >= 8:
        cache.clear()
    cache[key] = (time.monotonic(), board)
    return board


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
def board_figure(board: bs.Board, order: list[str], mode: str,
                 p: dict[str, str]) -> go.Figure:
    """Strength heatmap (left) and trend heatmap (right), rows aligned."""
    bench = board.benchmark
    states = state_text(bench)
    tfs = board.timeframes
    horizons = list(dict.fromkeys(board.trends["horizon"]))
    s = board.strength.set_index(["asset", "timeframe"])
    t = board.trends.set_index(["asset", "horizon"])

    # "% vs" colors are scaled per column, so a 1h move and a 1M move both
    # fill the range; the text shows the real number.
    col_scale = {}
    for tf in tfs:
        vals = board.strength.loc[board.strength["timeframe"] == tf, "pct_vs"]
        m = float(vals.abs().max()) if vals.notna().any() else 0.0
        col_scale[tf] = m if m > 0 else 1.0

    z, text, hover = [], [], []
    for asset in order:
        zr, tr, hr = [], [], []
        for tf in tfs:
            if asset == bs.BTC and bench == bs.BTC:
                zr.append(np.nan)
                tr.append("base" if tf == tfs[0] else "")
                hr.append("BTC is the benchmark.<br>See the BTC.D row for BTC's strength.")
                continue
            if (asset, tf) not in s.index:
                zr.append(np.nan)
                tr.append("—")
                hr.append("no data")
                continue
            row = s.loc[(asset, tf)]
            d, st_, pct = row["direction"], row["strength"], row["pct_vs"]
            if mode == "pct":
                zr.append(np.nan if pd.isna(pct) else 3 * pct / col_scale[tf])
                tr.append(_pct(pct))
            else:
                zr.append(_state_z(d, st_))
                tr.append(_strength_text(d, st_))
            if asset == bs.BTC_D:
                what, vs = BTC_D_STATE_TEXT.get(d, d), "BTC.D change"
            else:
                what, vs = states.get(d, d), f"vs {bench}"
            reason = f"<br>Reason: {row['reason']}" if d == rs_mod.UNKNOWN and row["reason"] else ""
            turning = ("<br>Turning: the latest score points the other way."
                       "<br>The state flips only if that holds (noise filter)."
                       if _turning(d, st_) else "")
            hr.append(f"<b>{asset} · {tf}</b><br>{what}"
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

    dense = len(order) > 40
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True,
                        column_widths=[0.6, 0.4], horizontal_spacing=0.03,
                        subplot_titles=(
                            f"Strength vs {bench}" if mode == "strength"
                            else f"% vs {bench} over the last 1h / 4h / 24h / 7d / 30d",
                            "Price trend (daily EMA 20 / 50 / 200)"))
    common = dict(colorscale=colorscale(p), showscale=False, xgap=2, ygap=2,
                  texttemplate="%{text}", hoverongaps=False,
                  hovertemplate="%{customdata}<extra></extra>",
                  textfont=dict(size=11 if dense else 13))
    fig.add_trace(go.Heatmap(z=z, x=tfs, y=order, text=text, customdata=hover,
                             zmin=-3, zmax=3, **common), row=1, col=1)
    fig.add_trace(go.Heatmap(z=tz, x=[HORIZON_LABEL.get(h, h) for h in horizons],
                             y=order, text=ttext, customdata=thover,
                             zmin=-1.6, zmax=1.6, **common), row=1, col=2)
    # Line between the pinned rows (BTC.D, BTC) and the coins.
    fig.add_hline(y=1.5, line=dict(color=p["muted"], width=1.5))
    fig.update_yaxes(autorange="reversed",
                     tickfont=dict(color=p["ink"], size=11 if dense else 13),
                     showgrid=False, zeroline=False, ticks="", automargin=True)
    fig.update_xaxes(side="top", tickfont=dict(color=p["ink2"], size=12),
                     showgrid=False, zeroline=False, ticks="")
    fig.update_annotations(font=dict(color=p["ink2"], size=13), yshift=22)
    fig.update_layout(height=90 + (26 if dense else 34) * len(order),
                      margin=dict(l=70, r=10, t=70, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color=p["ink"]))
    return fig


def pct_bar_figure(df: pd.DataFrame, bench: str, p: dict[str, str]) -> go.Figure:
    df = df.sort_values("pct_vs")
    colors = [p["pos"] if v >= 0 else p["neg"] for v in df["pct_vs"]]
    fig = go.Figure(go.Bar(
        x=df["pct_vs"], y=df["asset"], orientation="h",
        marker=dict(color=colors, line=dict(width=0)),
        text=[_pct(v) for v in df["pct_vs"]], textposition="outside",
        textfont=dict(color=p["ink2"], size=12), cliponaxis=False,
        hovertemplate=f"<b>%{{y}}</b><br>%{{x:+.2f}}% vs {bench}<extra></extra>"))
    fig.add_vline(x=0, line=dict(color=p["muted"], width=1))
    # Fixed range with room on both sides for the outside value labels.
    lo = min(0.0, float(df["pct_vs"].min())) if len(df) else 0.0
    hi = max(0.0, float(df["pct_vs"].max())) if len(df) else 1.0
    pad = 0.18 * ((hi - lo) or 1.0)
    fig.update_xaxes(ticksuffix="%", gridcolor=p["grid"], zeroline=False,
                     tickfont=dict(color=p["muted"]),
                     range=[lo - (pad if lo < 0 else 0), hi + (pad if hi > 0 else 0)])
    fig.update_yaxes(tickfont=dict(color=p["ink"], size=12), automargin=True,
                     showgrid=False, ticks="", type="category")
    fig.update_layout(height=60 + 24 * max(len(df), 1), bargap=0.3,
                      margin=dict(l=60, r=20, t=10, b=30),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def legend_html(p: dict[str, str], bench: str) -> str:
    def chip(color: str, label: str) -> str:
        return (f"<span style='display:inline-block;width:12px;height:12px;"
                f"border-radius:3px;background:{color};margin:0 6px -1px 14px'></span>"
                f"{label}")
    return ("<div style='font-size:0.85rem;opacity:0.85'>"
            + chip(p["pos"], f"▲ stronger than {bench} / uptrend")
            + chip(p["mid"], "· no clear edge / flat")
            + chip(p["neg"], f"▼ weaker than {bench} / downtrend")
            + "</div>")


# -- sidebar pieces ----------------------------------------------------------------
def watchlist_editor(store: WatchlistStore) -> None:
    """Create, change, rename or delete a saved watchlist."""
    lists = store.load()
    target = st.selectbox("List to edit", [NEW_LIST] + sorted(lists), key="wl_target")
    is_new = target == NEW_LIST
    listed = usdt_coins()
    current = [] if is_new else lists[target]
    name = st.text_input("Name", value="" if is_new else target,
                         key=f"wl_name_{target}", placeholder="e.g. AI coins")
    picked = st.multiselect("Coins", sorted(set(listed) | set(current)),
                            default=current, key=f"wl_coins_{target}",
                            placeholder="Type to search…")
    pasted = st.text_area("Or paste symbols", key=f"wl_paste_{target}", height=80,
                          placeholder="SOL, ETH, BINANCE:PEPEUSDT …",
                          help="Commas, spaces or new lines. TradingView "
                               "tickers like BINANCE:SOLUSDT work too.")
    c1, c2 = st.columns(2)
    if c1.button("💾 Save", key=f"wl_save_{target}", width="stretch"):
        coins = list(dict.fromkeys(picked + parse_symbols(pasted)))
        if not name.strip():
            st.error("Give the list a name.")
        elif not coins:
            st.error("Add at least one coin.")
        else:
            if not is_new and name.strip() != target:
                store.delete(target)              # renamed
            saved = store.save(name, coins)
            missing = [c for c in saved if c not in set(listed)]
            msg = f"Saved “{name.strip()}” with {len(saved)} coins."
            if missing:
                msg += f" Not on CoinDCX, so no data: {', '.join(missing)}."
            st.session_state["wl_msg"] = msg
            # Show the saved list next run (a widget's key can't change after
            # it is drawn in this run).
            st.session_state["wl_next"] = name.strip()
            st.session_state["wl_target_next"] = name.strip()
            st.rerun()
    if not is_new and c2.button("🗑 Delete", key=f"wl_del_{target}", width="stretch"):
        store.delete(target)
        st.session_state["wl_msg"] = f"Deleted “{target}”."
        st.session_state["wl_target_next"] = NEW_LIST
        st.rerun()
    if msg := st.session_state.pop("wl_msg", None):
        st.success(msg)


# -- page --------------------------------------------------------------------------
def main():
    p = palette()
    svc = get_service()
    store = WatchlistStore.from_config(svc.config)
    # Apply choices queued by the watchlist editor before the widgets exist.
    for src, dst in (("wl_next", "wl_pick"), ("wl_target_next", "wl_target")):
        if src in st.session_state:
            st.session_state[dst] = st.session_state.pop(src)
            if dst == "wl_pick":
                st.session_state["coin_source"] = "watchlist"

    with st.sidebar:
        st.header("Controls")
        bench = st.radio(
            "Measure against", list(bs.BENCHMARKS), horizontal=True,
            help="BTC: each coin's COIN/BTC price. BTC.D: each coin's USDT price "
                 "divided by BTC dominance, so a coin is strong when it rises "
                 "faster than BTC's share of the market.")
        source = st.radio("Coins", ["top", "watchlist", "config"], key="coin_source",
                          format_func={"top": "Top by market cap",
                                       "watchlist": "My watchlist",
                                       "config": "Config list"}.get)
        if source == "top":
            n = st.select_slider("How many", TOP_SIZES, value=100,
                                 help="The biggest coins by CoinGecko market cap "
                                      "that CoinDCX lists. Stablecoins and "
                                      "wrapped tokens are left out. 500 coins "
                                      "take about a minute.")
            coins, ranked_by = top_coins(n)
            st.caption(f"{len(coins)} coins, ranked by {ranked_by}.")
        elif source == "watchlist":
            lists = store.load()
            if not lists:
                st.info("No watchlist yet. Make one in “Edit my watchlists” below.")
                coins = []
            else:
                pick = st.selectbox("Watchlist", sorted(lists), key="wl_pick")
                coins = lists.get(pick, [])
                st.caption(f"{len(coins)} coins.")
        else:
            universe = [c for c in svc.universe() if c != bs.BTC]
            coins = st.multiselect("Coins", options=universe, default=universe)
        timeframes = st.multiselect("Timeframes", options=ALL_TIMEFRAMES,
                                    default=ALL_TIMEFRAMES)
        timeframes = [t for t in ALL_TIMEFRAMES if t in timeframes]

        st.subheader("Display")
        mode = st.radio("Cells show", ["strength", "pct"], horizontal=True,
                        format_func={"strength": "Strength score",
                                     "pct": f"% vs {bench}"}.get,
                        help="Strength score: noise-filtered trend of the ratio "
                             "on closed candles (about -3 to +3). "
                             f"% vs {bench}: how much the coin beat or lagged "
                             "over the last 1h / 4h / 24h / 7d / 30d, live.")
        sort_by = st.selectbox("Sort by", ["overall"] + timeframes,
                               format_func=lambda v: "All timeframes" if v == "overall"
                               else f"{v} strength")
        weakest_first = st.toggle("Weakest first")
        rows = st.slider("Coins in the chart", 10, 200, 30, step=5)
        liquidity_gate = st.checkbox("Liquidity gate", value=True,
                                     help="Skip coins whose USDT book trades "
                                          "less than the floor in config.yaml.")
        if st.button("🔄 Refresh data"):
            board_cache().clear()
            st.cache_data.clear()
            svc.ohlcv.clear_cache()

        with st.expander("✏️ Edit my watchlists"):
            watchlist_editor(store)

    st.title(f"Coins vs {bench}")
    if bench == bs.BTC:
        st.caption("Each coin measured on COIN/BTC. BTC itself is measured on "
                   "BTC.D, because it cannot be measured against itself.")
    else:
        st.caption("Each coin, BTC included, measured on its USDT price divided "
                   "by BTC.D: strong = rising faster than BTC's market share.")

    if not (coins and timeframes):
        st.warning("Pick at least one coin and one timeframe.")
        return
    board = get_board(tuple(coins), tuple(timeframes), liquidity_gate, bench)

    # -- header: BTC, BTC.D and the market read ------------------------------------
    c1, c2, c3 = st.columns([1, 1.3, 1.3])
    c1.metric("BTC.D now", "—" if board.btc_dominance_pct is None
              else f"{board.btc_dominance_pct:.1f}%",
              help="BTC's share of the whole crypto market cap (CoinGecko).")
    c2.markdown(f"**BTC trend (BTC/USDT)**  \n{_trend_line(board.trends, bs.BTC)}")
    c3.markdown(f"**BTC.D trend**  \n{_trend_line(board.trends, bs.BTC_D)}")
    st.info(_market_read(board))

    # -- breadth: how many coins, and which, per timeframe ---------------------------
    st.markdown(f"**Coins stronger than {bench}**")
    br = board.breadth().set_index("timeframe")
    s = board.strength
    cols = st.columns(len(timeframes))
    for col, tf in zip(cols, timeframes):
        r = br.loc[tf]
        col.metric(tf, f"{r['stronger']}/{r['known']}",
                   help=f"{r['weaker']} coins are weaker than {bench} on {tf}. "
                        "Coins with no data are left out.")
        bulls = set(s.loc[(s["timeframe"] == tf) & (s["direction"] == rs_mod.BULL),
                          "asset"])
        names = [c for c in board.ranked(tf) if c in bulls]   # strongest first
        if not names:
            col.caption("none")
        elif len(names) <= 20:
            col.caption(", ".join(names))
        else:
            with col.container(height=150, border=False):
                st.caption(", ".join(names))

    # -- main board -----------------------------------------------------------------
    ranked = board.ranked(sort_by, weakest_first=weakest_first)
    shown = ranked[:rows]
    st.markdown(legend_html(p, bench), unsafe_allow_html=True)
    st.plotly_chart(board_figure(board, [bs.BTC_D, bs.BTC] + shown, mode, p),
                    width="stretch", theme=None, config={"displayModeBar": False})
    order_txt = "weakest" if weakest_first else "strongest"
    by_txt = "all timeframes" if sort_by == "overall" else f"{sort_by} strength"
    st.caption(f"Showing {len(shown)} of {len(ranked)} coins, {order_txt} first "
               f"by {by_txt}. Coins with no data go last. Hover a cell for details.")

    # -- % vs bar chart -----------------------------------------------------------------
    st.subheader(f"How much each coin beat or lagged {bench}")
    default_tf = "1d" if "1d" in timeframes else timeframes[0]
    bar_tf = st.radio("Window", timeframes, index=timeframes.index(default_tf),
                      horizontal=True,
                      format_func=lambda tf: f"last {WINDOW_LABEL.get(tf, tf)}")
    df = s[(s["timeframe"] == bar_tf) & ~s["asset"].isin(bs.PINNED)]
    df = df.dropna(subset=["pct_vs"]).sort_values("pct_vs", ascending=False)
    if len(df) > rows:
        half = max(rows // 2, 5)
        st.caption(f"Top {half} and bottom {half} of {len(df)} coins.")
        df = pd.concat([df.head(half), df.tail(half)])
    st.plotly_chart(pct_bar_figure(df, bench, p), width="stretch",
                    theme=None, config={"displayModeBar": False})

    # -- table view -----------------------------------------------------------------------
    with st.expander(f"Table: all {len(ranked)} coins"):
        table = pd.DataFrame(index=[bs.BTC_D, bs.BTC] + ranked)
        for tf in timeframes:
            sub = s[s["timeframe"] == tf].set_index("asset")
            table[f"{tf} score"] = sub["strength"].round(2)
            table[f"{tf} % vs {bench}"] = sub["pct_vs"].round(2)
        tr = board.trends.pivot(index="asset", columns="horizon", values="state")
        for h in tr.columns:
            table[f"{HORIZON_LABEL.get(h, h)} trend"] = tr[h]
        summ = board.summary().set_index("asset")
        table["TFs stronger"] = summ["beats"]
        table["TFs weaker"] = summ["lags"]
        st.dataframe(table, width="stretch")


main()
