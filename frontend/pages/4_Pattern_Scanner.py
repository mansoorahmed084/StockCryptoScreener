"""Pattern scanner — triangles and wedges across coins and timeframes, with the
daily order blocks above and below each one.

The scan is in backend/screener/pattern_scan.py; this file only draws it.
Tick a row to see its chart below the table; the Coin and Chart columns
link to the full Chart Patterns page.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.config import load_config  # noqa: E402
from backend.screener import pattern_scan as ps  # noqa: E402
from backend.service import ScreenerService  # noqa: E402
from backend.watchlists import WatchlistStore  # noqa: E402
from frontend import pattern_view as pv  # noqa: E402

st.set_page_config(page_title="Pattern scanner", layout="wide")

TIMEFRAMES = ["15m", "1h", "4h", "1d"]
TOP_SIZES = [10, 25, 50, 100, 200]


@st.cache_resource(show_spinner=False)
def get_service() -> ScreenerService:
    return ScreenerService(load_config(), refresh=False)


@st.cache_data(ttl=3600, show_spinner="Ranking coins by market cap…")
def top_coins(n: int) -> dict[str, str]:
    return get_service().liquidation_coins(n)


@st.cache_data(ttl=3600, show_spinner=False)
def perpetuals() -> dict[str, str]:
    return get_service().futures().perpetuals()


@st.cache_resource
def scan_cache() -> dict:
    return {}


def run_scan(coins: dict[str, str], tfs: tuple[str, ...],
             patterns: tuple[str, ...]) -> tuple[pd.DataFrame, str]:
    """Cached for 5 minutes; a progress bar while it runs."""
    cache = scan_cache()
    key = (tuple(sorted(coins.items())), tfs, patterns)
    hit = cache.get(key)
    if hit and time.monotonic() - hit[0] < 300:
        return hit[1], hit[2]
    bar = st.progress(0.0, text=f"Scanning {len(coins)} coins…")
    out = ps.scan(get_service().futures().klines, coins, list(tfs),
                  patterns=patterns,
                  progress=lambda d, t: bar.progress(d / t, text=f"Scanning… {d} / {t}"))
    bar.empty()
    when = pd.Timestamp.now(tz="UTC").strftime("%b %d, %H:%M UTC")
    if len(cache) >= 6:
        cache.clear()
    cache[key] = (time.monotonic(), out, when)
    return out, when


def fmt(v: float) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:,.2f}" if v >= 100 else f"{v:.6g}"


def line(level: float, pct: float) -> str:
    return "—" if pd.isna(level) else f"{fmt(level)} ({pct:+.1f}%)"


def main():
    perps = perpetuals()
    with st.sidebar:
        st.header("Controls")
        source = st.radio("Coins", ["top", "watchlist"], horizontal=True,
                          format_func={"top": "Top by market cap",
                                       "watchlist": "My watchlist"}.get)
        if source == "top":
            n = st.select_slider("How many", TOP_SIZES, value=50)
            coins = top_coins(n)
        else:
            lists = WatchlistStore.from_config(get_service().config).load()
            if not lists:
                st.info("No watchlist yet. Make one on the BTC Strength page.")
                coins = {}
            else:
                name = st.selectbox("Watchlist", sorted(lists))
                coins = {c: perps[c] for c in lists[name] if c in perps}
                missing = [c for c in lists[name] if c not in perps]
                if missing:
                    st.caption(f"No Binance futures for: {', '.join(missing)}")
        tfs = st.multiselect("Timeframes", TIMEFRAMES, default=TIMEFRAMES)
        patterns = st.multiselect(
            "Patterns", list(ps.ALL_PATTERNS), default=list(ps.DEFAULT_PATTERNS),
            help="Bullish: ascending triangle, falling wedge, double bottom. "
                 "Bearish: descending triangle, rising wedge, double top.")
        only_live = st.toggle("Only fresh breakouts and near-breakouts", value=True,
                              help="Hide patterns still far from their lines and "
                                   "breakouts that already ran more than 3%.")
        if st.button("🔄 Refresh data"):
            scan_cache().clear()
            st.cache_data.clear()
            get_service().futures()._cache.clear()

    st.title("Pattern scanner")
    st.caption("Ascending / descending triangles, falling / rising wedges and more "
               "across coins and timeframes, each with the nearest daily order "
               "blocks. Patterns describe the chart; they do not predict it. Not "
               "financial advice.")
    if not (coins and tfs and patterns):
        st.warning("Pick coins, at least one timeframe and at least one pattern.")
        return

    df, when = run_scan(coins, tuple(tfs), tuple(patterns))
    live = df["setup"].str.contains("fresh|Near breakout", regex=True)
    view = df[live] if only_live else df

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Patterns found", len(df), help=f"{len(coins)} coins × {len(tfs)} timeframes")
    c2.metric("Fresh breakouts", int(df["setup"].str.contains("fresh").sum()))
    c3.metric("Near a breakout", int(df["setup"].str.startswith("Near breakout").sum()))
    c4.metric("Scanned", when)

    if view.empty:
        st.info("Nothing matches right now. Turn off “Only fresh breakouts and "
                "near-breakouts” to see every pattern.")
        return
    # Coin and Chart are links: they open the full chart page in a new tab.
    links = [f"Chart_Patterns?coin={c}&tf={t}"
             for c, t in zip(view["coin"], view["timeframe"])]
    table = pd.DataFrame({
        "Coin": links, "TF": view["timeframe"].tolist(),
        "Chart": links, "Pattern": view["pattern"].tolist(),
        "Setup": view["setup"].tolist(), "Price": [fmt(v) for v in view["price"]],
        "Upper line": [line(l, p) for l, p in zip(view["up_level"], view["up_pct"])],
        "Lower line": [line(l, p) for l, p in zip(view["down_level"], view["down_pct"])],
        "Target ↑": [fmt(v) for v in view["target_up"]],
        "Target ↓": [fmt(v) for v in view["target_down"]],
        "Touches": view["touches"].tolist(),
        "Daily supply above": [z if pd.isna(p) else f"{z} · {p:+.1f}%"
                               for z, p in zip(view["zone_above"], view["zone_above_pct"])],
        "Daily demand below": [z if pd.isna(p) else f"{z} · {p:+.1f}%"
                               for z, p in zip(view["zone_below"], view["zone_below_pct"])],
    })
    event = st.dataframe(
        table, hide_index=True, width="stretch", on_select="rerun",
        selection_mode="single-row", key="scan_table",
        column_config={
            "Coin": st.column_config.LinkColumn(
                "Coin", display_text=r"coin=([^&]+)",
                help="Opens the full chart in a new tab."),
            "Chart": st.column_config.LinkColumn(
                "Chart", display_text="📈 Open", width="small",
                help="Opens the full chart in a new tab."),
            "Setup": st.column_config.TextColumn(width="large"),
        })
    st.caption("Tick a row (the box on the left) to see its chart right here. Click a "
               "coin or 📈 Open for the full chart page in a new tab. Touches: upper / "
               "lower line. Targets: one pattern height past the breakout line.")

    sel = event.selection.rows if event else []
    if sel:
        row = view.iloc[sel[0]]
        st.divider()
        st.subheader(f"{row['coin']} · {row['timeframe']} · {row['pattern']}")
        st.caption(row["setup"])
        pv.render_chart(row["symbol"], row["timeframe"], 300,
                        key=f"scan_chart_{row['coin']}_{row['timeframe']}")

main()
