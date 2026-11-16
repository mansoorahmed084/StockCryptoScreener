"""Price action concepts — market structure (BOS / CHoCH, internal and swing),
order blocks, liquidity with volume, grabs, equal highs / lows, fair value
gaps, daily levels and sweep-break style setups on any Binance USDT perpetual.

Our own build of the "price action concepts" idea, on the same structure rules
as the tested SMC engine. Detection: backend/screener/price_action.py; drawing:
frontend/pa_view.py. A link like ``Price_Action?coin=SOL&tf=4h`` opens a chart.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.screener import patterns as pt  # noqa: E402
from backend.screener import price_action as pa  # noqa: E402
from frontend import pa_view  # noqa: E402
from frontend import pattern_view as pv  # noqa: E402

st.set_page_config(page_title="Price action", layout="wide")


@st.cache_data(ttl=300, show_spinner=False)
def daily(symbol: str) -> pd.DataFrame:
    return pv.get_service().futures().klines(symbol, "1d", 400)


def main():
    perps = pv.perpetuals()
    tops = [c for c in pv.top_coins() if c in perps]
    options = tops + sorted(c for c in perps if c not in tops)

    qp = st.query_params
    wanted = (qp.get("coin", "").upper(), qp.get("tf", ""))
    if any(wanted) and st.session_state.get("_pa_link") != wanted:
        if wanted[0] in options:
            st.session_state["pa_coin"] = wanted[0]
        if wanted[1] in pv.TIMEFRAMES:
            st.session_state["pa_tf"] = wanted[1]
        st.session_state["_pa_link"] = wanted
    if st.session_state.get("pa_coin") not in options:
        st.session_state["pa_coin"] = "BTC" if "BTC" in options else options[0]
    st.session_state.setdefault("pa_tf", "4h")

    with st.sidebar:
        st.header("Controls")
        coin = st.selectbox("Coin", options, key="pa_coin",
                            format_func=lambda c: f"{c}  ({perps[c]})",
                            help="Type to search every Binance USDT perpetual.")
        tf = st.radio("Timeframe", pv.TIMEFRAMES, key="pa_tf", horizontal=True)
        n = st.slider("Candles", 100, 1000, 300, step=50)
        with st.expander("Swing sizes"):
            k_int = st.slider("Internal structure", 2, 6, 3,
                              help="Candles each side for a small swing.")
            k_swing = st.slider("Swing structure", 5, 20, 10,
                                help="Candles each side for a major swing.")
            k_liq = st.slider("Liquidity swings", 3, 15, 5,
                              help="Candles each side for a liquidity level.")
        st.subheader("Draw")
        show = {
            "swing": st.checkbox("Swing structure", True),
            "internal": st.checkbox("Internal structure", True),
            "ob": st.checkbox("Order blocks", True),
            "liquidity": st.checkbox("Liquidity levels", True),
            "taken": st.checkbox("Taken liquidity", False),
            "grabs": st.checkbox("Liquidity grabs (×)", True),
            "equals": st.checkbox("Equal highs / lows", True),
            "fvg": st.checkbox("Fair value gaps", False),
            "daily": st.checkbox("Previous day / week high-low", True),
            "setups": st.checkbox("Sweep-break setups (SB)", True),
            "crt": st.checkbox("CRT sweeps & setups", True,
                               help="Previous higher-timeframe candle's high / low, the "
                                    "sweep of one side, and a setup confirmed by a fair "
                                    "value gap or structure shift."),
            "patterns": st.checkbox("Chart patterns (wedges, triangles)", False),
            "volume": st.checkbox("Volume", True),
            "vmc": st.checkbox("VuManChu Cipher B", False),
        }
        crt_opts = ["1h", "4h", "1D", "W-MON", "MS"]
        crt_htf = st.selectbox("CRT range candle", crt_opts,
                               index=crt_opts.index(pa.CRT_HTF[tf]),
                               format_func=lambda r: pa.CRT_NAME.get(r, r),
                               help="Pick a candle bigger than the chart's timeframe.")
        if st.button("🔄 Refresh data"):
            st.cache_data.clear()
            pv.get_service().futures()._cache.clear()

    if (qp.get("coin"), qp.get("tf")) != (coin, tf):
        st.query_params.update(coin=coin, tf=tf)
        st.session_state["_pa_link"] = (coin, tf)

    st.title("Price action")
    st.caption("Market structure, order blocks and liquidity found from swing highs "
               "and lows on closed candles. They describe the chart; they do not "
               "predict it. Not financial advice.")

    symbol = perps[coin]
    df = pv.candles(symbol, tf, n)
    d = daily(symbol)
    step = pd.Timedelta(seconds=pv.timeframe_to_seconds(tf))
    cx = pa.analyse(df, k_internal=k_int, k_swing=k_swing, k_liq=k_liq,
                    daily=d, ltf_step=step)
    a = pt.analyse(df)
    base = {"patterns": show["patterns"], "volume": show["volume"], "vmc": show["vmc"]}
    last = float(df["close"].iloc[-1])
    p = pv.palette()
    fig = pv.build_figure(df, a, tf, base, p,
                          f"{symbol} · {tf} · {n} candles · last {pv.fmt(last)}")
    pa_view.draw(fig, df, cx, tf, show, p)
    crt = pa.crt(df.iloc[:-1], crt_htf) if show["crt"] else None
    if crt:
        pa_view.draw_crt(fig, df, crt, tf, p)
    st.plotly_chart(fig, width="stretch", theme=None, key="pa_chart",
                    config={"displayModeBar": True, "scrollZoom": True,
                            "modeBarButtonsToRemove": ["lasso2d", "select2d"]})
    st.caption(pa_view.LEGEND)
    if crt:
        pa_view.render_crt(df, crt)
    pa_view.render_details(df, cx)


main()
