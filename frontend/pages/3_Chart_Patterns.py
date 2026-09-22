"""Chart patterns — price action, trendlines, flat levels, Fibonacci, patterns
and daily order blocks drawn automatically on any Binance USDT perpetual.

Drawing lives in frontend/pattern_view.py (shared with the Pattern Scanner);
detection in backend/screener/patterns.py. A link like
``Chart_Patterns?coin=XRP&tf=15m`` opens that chart directly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from frontend import pattern_view as pv  # noqa: E402

st.set_page_config(page_title="Chart patterns", layout="wide")


def main():
    perps = pv.perpetuals()
    tops = [c for c in pv.top_coins() if c in perps]
    options = tops + sorted(c for c in perps if c not in tops)

    # A link from the scanner (?coin=XRP&tf=15m) picks the chart once; after
    # that the sidebar is in charge and the URL follows it.
    qp = st.query_params
    wanted = (qp.get("coin", "").upper(), qp.get("tf", ""))
    if any(wanted) and st.session_state.get("_cp_link") != wanted:
        if wanted[0] in options:
            st.session_state["cp_coin"] = wanted[0]
        if wanted[1] in pv.TIMEFRAMES:
            st.session_state["cp_tf"] = wanted[1]
        st.session_state["_cp_link"] = wanted
    if st.session_state.get("cp_coin") not in options:
        st.session_state["cp_coin"] = "BTC" if "BTC" in options else options[0]
    st.session_state.setdefault("cp_tf", "1h")

    with st.sidebar:
        st.header("Controls")
        coin = st.selectbox("Coin", options, key="cp_coin",
                            format_func=lambda c: f"{c}  ({perps[c]})",
                            help="Type to search every Binance USDT perpetual.")
        tf = st.radio("Timeframe", pv.TIMEFRAMES, key="cp_tf", horizontal=True)
        n = st.slider("Candles", 100, 1000, 300, step=50)
        swing = st.select_slider("Swing size", ["auto", 3, 4, 5, 6, 8, 10], value="auto",
                                 help="How many candles each side a swing high / low must "
                                      "beat. Bigger = fewer, more important lines.")
        st.subheader("Draw")
        show = {
            "obs": st.checkbox("Daily order blocks", True,
                               help="Purple zones: the last candle before a sharp "
                                    "daily move. Supply above price, demand below."),
            "pa": st.checkbox("Price action (HH / HL / LH / LL)", True),
            "trendlines": st.checkbox("Trendlines", True),
            "levels": st.checkbox("Flat support / resistance", True),
            "fib": st.checkbox("Fibonacci", True),
            "patterns": st.checkbox("Patterns", True),
            "volume": st.checkbox("Volume", True),
            "vmc": st.checkbox("VuManChu Cipher B", True),
        }
        if st.button("🔄 Refresh data"):
            st.cache_data.clear()
            pv.get_service().futures()._cache.clear()

    # Keep the URL on the chart shown, so it can be bookmarked or shared.
    if (qp.get("coin"), qp.get("tf")) != (coin, tf):
        st.query_params.update(coin=coin, tf=tf)
        st.session_state["_cp_link"] = (coin, tf)

    st.title("Chart patterns")
    st.caption("Price action, trendlines, flat levels, Fibonacci, patterns and daily "
               "order blocks found automatically from swing highs and lows. Like "
               "hand-drawn lines, they describe the chart shown; they do not predict "
               "it. Not financial advice.")
    pv.render_chart(perps[coin], tf, n, swing=swing, show=show)


main()
