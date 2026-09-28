"""Chart workspace — a TradingView-style chart with drawing tools, indicators
and watchlists, for crypto (Binance) and stocks (NSE, BSE, US).

The workspace is a separate full-screen page served by the API
(``uvicorn backend.api.app:app --port 8000``, then open /workspace). This page
links to it and shows it in a frame. ``chart.workspace_url`` in config.yaml
sets the address (default http://localhost:8000/workspace).
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlencode

import httpx
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.config import load_config  # noqa: E402

st.set_page_config(page_title="Chart workspace", layout="wide")


def main():
    url = load_config().chart_workspace_url
    qp = st.query_params
    if "symbol" in qp:
        url += "?" + urlencode({"symbol": qp["symbol"], "tf": qp.get("tf", "4h")})
    st.title("Chart workspace")
    st.link_button("Open full screen ↗", url, type="primary")
    try:
        httpx.get(url.split("?")[0], timeout=2).raise_for_status()
    except httpx.HTTPError:
        st.warning("The chart API is not running. Start it with:")
        st.code(".venv/Scripts/python.exe -m uvicorn backend.api.app:app --port 8000",
                language="bash")
        return
    components.iframe(url, height=820, scrolling=False)


main()
