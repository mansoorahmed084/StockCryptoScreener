"""Market Desk — its own Streamlit app, separate from the screener dashboard.

Run:  streamlit run market_desk/app.py --server.port 8503

Heatmap, screen, backtest verdicts, trade plans + paper trades, news and
sentiment, and price alerts. Paper only: no real order is ever sent.
"""
from __future__ import annotations

import datetime as dt
import math
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_desk import alerts, heatmap, paper  # noqa: E402
from market_desk.rules import TEXT  # noqa: E402
from market_desk.routines import Desk  # noqa: E402
from market_desk.settings import MARKET_NAMES, short  # noqa: E402

st.set_page_config(page_title="Market Desk", page_icon="🧭", layout="wide")

WORKSPACE = "http://localhost:8000/workspace"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
# Diverging pair (blue up, red down) with a gray midpoint, as on the screener.
BLUE, RED = "#256abf", "#e34948"


def dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except AttributeError:
        return False


@st.cache_resource
def get_desk() -> Desk:
    return Desk()


def chart_link(symbol: str) -> str:
    return f"{WORKSPACE}?{urlencode({'symbol': symbol, 'tf': '1d'})}"


def when(ts) -> str:
    if not ts:
        return "never"
    return dt.datetime.fromtimestamp(int(ts), IST).strftime("%d %b %H:%M IST")


@st.cache_data(ttl=60, show_spinner=False)
def load_heatmap(market: str) -> pd.DataFrame:
    desk = get_desk()
    if desk.settings.view_only:      # the server saves it every 15 minutes
        cols = ["market", "group", "label", "symbol", "last", "chg_1d", "chg_1w", "chg_1m"]
        rows = desk.store.heatmap(market)
        return pd.DataFrame(rows, columns=["ts"] + cols).astype(
            {c: float for c in ("last", "chg_1d", "chg_1w", "chg_1m")})
    return heatmap.build(desk.settings, desk.data, market)


@st.cache_data(ttl=30, show_spinner=False)
def load_quotes(symbols: tuple[str, ...]) -> dict:
    if not symbols:
        return {}
    desk = get_desk()
    try:
        if desk.settings.view_only:  # saved by the server on every tick
            saved = desk.store.quotes()
            return {s: saved[s] for s in symbols if s in saved}
        return desk.data.quotes(list(symbols))
    except Exception:   # quotes are a nice-to-have on this page
        return {}


def password_ok() -> bool:
    """MARKET_DESK_PASSWORD (a Streamlit secret) closes the page with a password."""
    import hmac
    import os
    want = os.environ.get("MARKET_DESK_PASSWORD", "")
    if not want or st.session_state.get("desk_ok"):
        return True
    st.title("🧭 Market Desk")
    pw = st.text_input("Password", type="password")
    if pw and hmac.compare_digest(pw, want):
        st.session_state["desk_ok"] = True
        st.rerun()
    elif pw:
        st.error("Wrong password.")
    return False


# ------------------------------------------------------------------ sidebar
def sidebar(desk: Desk) -> None:
    st.sidebar.title("🧭 Market Desk")
    st.sidebar.caption("Separate from the screener. **Paper trades only**: the desk "
                       "never sends a real order.")
    if desk.settings.view_only:
        st.sidebar.info("The jobs run on the server (night 03:00, morning 08:45 IST, "
                        "paper trades + alerts every 5 min). This page reads them from "
                        "Supabase.")
        if st.sidebar.button("🔄 Reload data", width="stretch"):
            st.cache_data.clear()
        st.sidebar.divider()
        for key, name in (("night", "Night"), ("morning", "Morning"), ("tick", "Tick")):
            st.sidebar.caption(f"{name}: {when(desk.store.get_meta(f'last_{key}'))}")
        return
    if st.sidebar.button("🌙 Night: backtest + news", width="stretch",
                         help="Tests every rule with fees and reads the headlines. "
                              "Takes a few minutes."):
        with st.spinner("Backtesting the rules and reading the news…"):
            desk.night(notify=False)
        st.cache_data.clear()
    if st.sidebar.button("☀️ Morning: screen + plans", width="stretch"):
        with st.spinner("Screening the watchlist…"):
            out = desk.morning(notify=False)
        st.sidebar.success(f"{len(out['plans'])} new plan(s)")
    if st.sidebar.button("🔄 Check paper trades + alerts", width="stretch"):
        with st.spinner("Checking…"):
            events = desk.tick()
        st.sidebar.success(f"{len(events)} event(s)")
    st.sidebar.divider()
    for key, name in (("night", "Night"), ("morning", "Morning"), ("tick", "Tick")):
        st.sidebar.caption(f"{name}: {when(desk.store.get_meta(f'last_{key}'))}")
    st.sidebar.caption("Run all of it on a schedule:\n\n"
                       "`.venv/Scripts/python.exe -m market_desk watch`")
    st.sidebar.caption(f"Data: {desk.store.where}")


# ------------------------------------------------------------------ heatmap
def treemap_figure(d: pd.DataFrame, col: str, market: str) -> go.Figure:
    """Tiles coloured by % change. Crypto: groups of coins (a group's colour
    and number are its coins' average). India / US: one tile per sector."""
    lim = max(1.0, float(d[col].abs().quantile(0.9)))
    neutral, surface = ("#383835", "#0e1117") if dark() else ("#f0efec", "#ffffff")
    root = {"india": "India", "us": "US", "crypto": "Crypto"}[market]
    ids, labels, parents, colors, hover = [root], [root], [""], [float(d[col].mean())], [""]
    if market == "crypto":
        for group, g in d.groupby("group", sort=False):
            ids.append(f"g:{group}")
            labels.append(str(group))
            parents.append(root)
            colors.append(float(g[col].mean()))
            hover.append(f"{len(g)} coins, average")
    for r in d.itertuples():
        ids.append(r.symbol)
        labels.append(r.label)
        parents.append(f"g:{r.group}" if market == "crypto" else root)
        colors.append(float(getattr(r, col)))
        hover.append(f"{r.symbol} · last {r.last:,.6g}")
    text = [f"{c:+.2f}%" for c in colors]
    ink = "#f5f5f4" if dark() else "#1a1a19"
    # White on strong blue / red tiles, the page ink on pale ones.
    font_colors = ["#ffffff" if abs(c) >= 0.45 * lim else ink for c in colors]
    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, text=text, customdata=hover,
        values=[0] * (len(ids) - len(d)) + [1] * len(d), branchvalues="remainder",
        marker={"colors": colors, "colorscale": [(0, RED), (0.5, neutral), (1, BLUE)],
                "cmin": -lim, "cmax": lim, "cmid": 0, "line": {"width": 2, "color": surface},
                "showscale": True, "colorbar": {"title": "% change", "ticksuffix": "%"}},
        texttemplate="<b>%{label}</b><br>%{text}",
        textfont={"size": 15, "color": font_colors},
        hovertemplate="<b>%{label}</b> %{text}<br>%{customdata}<extra></extra>"))
    fig.update_layout(margin={"t": 10, "l": 0, "r": 0, "b": 0}, height=560)
    return fig


def heatmap_tab() -> None:
    c1, c2 = st.columns([2, 3])
    market = c1.radio("Market", ["india", "us", "crypto"], horizontal=True,
                      format_func=lambda m: {"india": "India sectors", "us": "US sectors",
                                             "crypto": "Crypto groups"}[m])
    period = c2.radio("Change over", ["chg_1d", "chg_1w", "chg_1m"], horizontal=True,
                      format_func=lambda c: {"chg_1d": "1 day", "chg_1w": "1 week",
                                             "chg_1m": "1 month"}[c])
    with st.spinner("Loading prices…"):
        df = load_heatmap(market)
    d = df.dropna(subset=[period])
    if d.empty:
        st.info("No prices yet. The server saves them every 15 minutes."
                if get_desk().settings.view_only else
                "No prices came back. Try again in a minute.")
        return
    if "ts" in d:
        st.caption(f"Prices saved by the server {when(d['ts'].max())}.")
        d = d.drop(columns=["ts"])
    st.plotly_chart(treemap_figure(d, period, market), width="stretch")
    st.caption("Blue = up, red = down, gray = flat. "
               + ("Crypto group tiles show the group's average. " if market == "crypto" else "")
               + ("Stocks are about 15 minutes delayed." if market != "crypto" else
                  "Binance spot, live."))
    with st.expander("Table"):
        t = d.drop(columns=["market"]).sort_values(period, ascending=False)
        st.dataframe(t, hide_index=True, width="stretch", column_config={
            "chg_1d": st.column_config.NumberColumn("1d %", format="%+.2f"),
            "chg_1w": st.column_config.NumberColumn("1w %", format="%+.2f"),
            "chg_1m": st.column_config.NumberColumn("1m %", format="%+.2f"),
            "last": st.column_config.NumberColumn("Last", format="%.4g")})


# ------------------------------------------------------------------ screen
def screen_tab(desk: Desk) -> None:
    rows = desk.store.latest_screen()
    if not rows:
        st.info("No screen yet. Press **☀️ Morning** in the sidebar.")
        return
    st.caption(f"Screened {when(rows[0]['run_ts'])} on closed daily candles. "
               "Score: trend 40 + RSI 20 + slope 20 + volume 20. "
               "A high score is a strong trend, not a buy signal by itself.")
    df = pd.DataFrame(rows)
    market = st.radio("Market", ["all", "crypto", "india", "us"], horizontal=True,
                      format_func=lambda m: "All" if m == "all" else MARKET_NAMES[m],
                      key="screen_market")
    if market != "all":
        df = df[df["market"] == market]
    df = df.assign(name=df["symbol"].map(short), chart=df["symbol"].map(chart_link),
                   market=df["market"].map(MARKET_NAMES))
    st.dataframe(df[["name", "market", "score", "trend", "close", "rsi", "chg_1d", "chg_1w",
                     "chg_1m", "vol_ratio", "setups", "notes", "chart"]],
                 hide_index=True, width="stretch", height=560, column_config={
                     "name": "Symbol", "market": "Market",
                     "score": st.column_config.ProgressColumn("Score", min_value=0,
                                                              max_value=100, format="%.0f"),
                     "trend": "Trend",
                     "close": st.column_config.NumberColumn("Close", format="%.4g"),
                     "rsi": st.column_config.NumberColumn("RSI", format="%.0f"),
                     "chg_1d": st.column_config.NumberColumn("1d %", format="%+.1f"),
                     "chg_1w": st.column_config.NumberColumn("1w %", format="%+.1f"),
                     "chg_1m": st.column_config.NumberColumn("1m %", format="%+.1f"),
                     "vol_ratio": st.column_config.NumberColumn("Vol 5/50", format="%.2f"),
                     "setups": "Rules firing", "notes": "Notes",
                     "chart": st.column_config.LinkColumn("Chart", display_text="📈 open")})


# ------------------------------------------------------------------ backtest
def backtest_tab(desk: Desk) -> None:
    verdicts = desk.store.latest_verdicts()
    cfg = desk.settings.backtest
    st.markdown(
        f"Each rule is tested on **{cfg['years']} years** of daily candles with fees and "
        f"slippage. It is **kept** only with ≥ {cfg['min_trades']} trades, ≥ "
        f"{cfg['min_exp_r']:+.2f}R a trade, profit factor ≥ {cfg['min_pf']}, **and** a profit "
        "on the control symbols (symbols that are not on the watchlist).")
    if not verdicts:
        st.info("No backtest yet. Press **🌙 Night** in the sidebar.")
        return
    st.caption(f"Tested {when(verdicts[0]['run_ts'])}.")
    df = pd.DataFrame(verdicts)
    df = df.assign(market=df["market"].map(MARKET_NAMES),
                   verdict=df["keep"].map({1: "✅ keep", 0: "❌ kill"}))
    st.dataframe(df[["market", "rule", "verdict", "why", "w_trades", "w_win", "w_exp", "w_pf",
                     "w_dd", "c_trades", "c_exp", "recent_trades", "recent_exp"]],
                 hide_index=True, width="stretch", column_config={
                     "market": "Market", "rule": "Rule", "verdict": "Verdict", "why": "Why",
                     "w_trades": "Trades", "w_win": st.column_config.NumberColumn(
                         "Win %", format="%.0f"),
                     "w_exp": st.column_config.NumberColumn("Avg R", format="%+.2f"),
                     "w_pf": st.column_config.NumberColumn("PF", format="%.2f"),
                     "w_dd": st.column_config.NumberColumn("Max DD (R)", format="%.1f"),
                     "c_trades": "Control trades",
                     "c_exp": st.column_config.NumberColumn("Control avg R", format="%+.2f"),
                     "recent_trades": "Last-year trades",
                     "recent_exp": st.column_config.NumberColumn("Last-year avg R",
                                                                 format="%+.2f")})
    with st.expander("What each rule does"):
        for rule, text in TEXT.items():
            tr = desk.settings.rules.get(rule, {}).get("target_r", "—")
            st.markdown(f"**{rule}** (target {tr}R) — {text}")
        st.markdown("Exits: stop, target, or the close after "
                    f"{cfg['max_hold']} daily candles. An entry order waits "
                    f"{cfg['order_bars']} candles. A candle that touches the stop and the "
                    "target counts as a loss.")
    with st.expander("Per symbol"):
        per = pd.DataFrame(desk.store.latest_bt_symbols())
        if not per.empty:
            per = per.assign(name=per["symbol"].map(short))
            st.dataframe(per[["name", "scope", "rule", "trades", "win_rate", "exp_r", "pf",
                              "total_r", "max_dd_r"]].sort_values(["scope", "rule", "exp_r"]),
                         hide_index=True, width="stretch")
            st.caption("One symbol has few trades, so these numbers are noisy. "
                       "Judge a rule by the pooled table above, not by its best symbol.")


# ------------------------------------------------------------------ plans + paper
def paper_tab(desk: Desk) -> None:
    acc = paper.account(desk.settings, desk.store)
    m = st.columns(6)
    m[0].metric("Paper equity", f"{acc['equity']:,.0f}", f"{acc['return_pct']:+.2f}%")
    m[1].metric("Closed trades", acc["closed"])
    m[2].metric("Win rate", f"{acc['win_rate']:.0f}%")
    m[3].metric("Avg trade", f"{acc['avg_r']:+.2f}R")
    m[4].metric("Total", f"{acc['total_r']:+.2f}R")
    m[5].metric("Open", acc["open"], f"{acc['open_risk_pct']:.1f}% at risk",
                delta_color="off")
    pcfg = desk.settings.paper
    st.caption(f"Risk layer: {pcfg['risk_pct']}% risk a trade, size ≤ "
               f"{pcfg['max_position_pct']}% of equity, ≤ {pcfg['max_open']} open "
               f"(≤ {pcfg['max_per_market']} a market), open risk ≤ "
               f"{pcfg['max_total_risk_pct']}%, ≤ {pcfg['max_new_per_day']} new a day.")

    pending = desk.store.plans("pending")
    open_ = desk.store.trades("open")
    quotes = load_quotes(tuple(sorted({p["symbol"] for p in pending} |
                                      {t["symbol"] for t in open_})))

    st.subheader("Waiting plans")
    if pending:
        df = pd.DataFrame(pending)
        last = df["symbol"].map(lambda s: (quotes.get(s) or {}).get("last", math.nan))
        df = df.assign(name=df["symbol"].map(short), last=last,
                       to_entry=(df["entry"] / last - 1) * 100,
                       rr=(df["target"] - df["entry"]) / (df["entry"] - df["stop"]),
                       starts=df["valid_from"].map(lambda t: dt.datetime.fromtimestamp(
                           t, dt.timezone.utc).strftime("%d %b")),
                       chart=df["symbol"].map(chart_link))
        st.dataframe(df[["id", "name", "rule", "entry", "stop", "target", "rr", "last",
                         "to_entry", "starts", "order_bars", "chart"]],
                     hide_index=True, width="stretch", column_config={
                         "id": "#", "name": "Symbol", "rule": "Rule",
                         "entry": st.column_config.NumberColumn("Buy above", format="%.4g"),
                         "stop": st.column_config.NumberColumn("Stop", format="%.4g"),
                         "target": st.column_config.NumberColumn("Target", format="%.4g"),
                         "rr": st.column_config.NumberColumn("R:R", format="%.1f"),
                         "last": st.column_config.NumberColumn("Last", format="%.4g"),
                         "to_entry": st.column_config.NumberColumn("To entry %",
                                                                   format="%+.2f"),
                         "starts": "From", "order_bars": "Days valid",
                         "chart": st.column_config.LinkColumn("Chart", display_text="📈")})
    else:
        st.caption("No waiting plans.")

    st.subheader("Open paper trades")
    if open_:
        df = pd.DataFrame(open_)
        last = df["symbol"].map(lambda s: (quotes.get(s) or {}).get("last", math.nan))
        df = df.assign(name=df["symbol"].map(short), last=last,
                       open_r=(last - df["entry"]) / (df["entry"] - df["stop"]),
                       chart=df["symbol"].map(chart_link))
        st.dataframe(df[["id", "name", "rule", "entry", "stop", "target", "last", "open_r",
                         "risk_amt", "notional", "chart"]], hide_index=True, width="stretch",
                     column_config={
                         "id": "#", "name": "Symbol", "rule": "Rule",
                         "entry": st.column_config.NumberColumn("Entry", format="%.4g"),
                         "stop": st.column_config.NumberColumn("Stop", format="%.4g"),
                         "target": st.column_config.NumberColumn("Target", format="%.4g"),
                         "last": st.column_config.NumberColumn("Last", format="%.4g"),
                         "open_r": st.column_config.NumberColumn("Now (R)", format="%+.2f"),
                         "risk_amt": st.column_config.NumberColumn("Risk", format="%.0f"),
                         "notional": st.column_config.NumberColumn("Size", format="%.0f"),
                         "chart": st.column_config.LinkColumn("Chart", display_text="📈")})
    else:
        st.caption("No open paper trades.")

    closed = desk.store.trades("closed")
    st.subheader("Closed paper trades")
    if closed:
        df = pd.DataFrame(closed).sort_values("exit_time")
        df = df.assign(name=df["symbol"].map(short), cum_r=df["r"].cumsum(),
                       closed=pd.to_datetime(df["exit_time"], unit="s"))
        fig = go.Figure(go.Scatter(x=df["closed"], y=df["cum_r"], mode="lines+markers",
                                   line={"width": 2, "color": BLUE}, marker={"size": 8},
                                   hovertemplate="%{x|%d %b %Y}<br>%{y:+.2f}R<extra></extra>"))
        fig.update_layout(height=260, margin={"t": 10, "l": 0, "r": 0, "b": 0},
                          yaxis_title="Total R", showlegend=False)
        st.plotly_chart(fig, width="stretch")
        st.dataframe(df[["id", "name", "rule", "entry", "exit", "why", "r", "pnl", "closed"]]
                     .iloc[::-1], hide_index=True, width="stretch", column_config={
                         "id": "#", "name": "Symbol", "rule": "Rule",
                         "entry": st.column_config.NumberColumn("Entry", format="%.4g"),
                         "exit": st.column_config.NumberColumn("Exit", format="%.4g"),
                         "why": "Why", "r": st.column_config.NumberColumn("R", format="%+.2f"),
                         "pnl": st.column_config.NumberColumn("P&L", format="%+.0f"),
                         "closed": st.column_config.DatetimeColumn("Closed (UTC)",
                                                                   format="D MMM YYYY")})
    else:
        st.caption("No closed paper trades yet.")

    with st.expander("Old plans (filled, expired, skipped)"):
        old = [p for p in desk.store.plans() if p["status"] != "pending"]
        if old:
            st.dataframe(pd.DataFrame(old)[["id", "symbol", "rule", "entry", "stop", "target",
                                            "status", "note"]], hide_index=True,
                         width="stretch")


# ------------------------------------------------------------------ news
def news_tab(desk: Desk) -> None:
    fg = desk.store.get_meta("fear_greed")
    sent = desk.store.latest_sentiment()
    if not sent:
        st.info("No news yet. Press **🌙 Night** in the sidebar.")
        return
    c1, c2 = st.columns([1, 4])
    if fg:
        value, label = fg.split("|", 1)
        c1.metric("Crypto Fear & Greed", value, label, delta_color="off")
    c2.caption(f"Read {when(sent[0]['run_ts'])} from Google News"
               " (and Finnhub for US stocks when FINNHUB_API_KEY is set). Tone is a word "
               "count over each headline, −1 to +1. Buzz = last 24 h vs the 7-day daily "
               "average. Funding (crypto) = % per 8 h; high positive means crowded longs.")
    df = pd.DataFrame(sent)
    df = df.assign(name=df["symbol"].map(short), market=df["market"].map(MARKET_NAMES),
                   spike=df["spike"].map({1: "🔥", 0: ""}))
    st.dataframe(df[["name", "market", "headlines_24h", "headlines_7d", "buzz", "spike",
                     "tone", "label", "funding"]].sort_values("buzz", ascending=False),
                 hide_index=True, width="stretch", column_config={
                     "name": "Symbol", "market": "Market", "headlines_24h": "24 h",
                     "headlines_7d": "7 days",
                     "buzz": st.column_config.NumberColumn("Buzz", format="%.1f×"),
                     "spike": "Spike",
                     "tone": st.column_config.NumberColumn("Tone", format="%+.2f"),
                     "label": "Read",
                     "funding": st.column_config.NumberColumn("Funding %", format="%+.4f")})
    sym = st.selectbox("Headlines for", [r["symbol"] for r in sent], format_func=short)
    items = desk.store.news(sym, since=int(time.time()) - 7 * 86400, limit=40)
    for it in items:
        icon = "🔵" if it["tone"] > 0 else "🔴" if it["tone"] < 0 else "⚪"
        stamp = dt.datetime.fromtimestamp(it["ts"], IST).strftime("%d %b %H:%M")
        st.markdown(f"{icon} [{it['title']}]({it['link']})  \n"
                    f"<small>{it['source']} · {stamp} IST</small>", unsafe_allow_html=True)
    if not items:
        st.caption("No headlines in the last 7 days.")


# ------------------------------------------------------------------ alerts
def alerts_tab(desk: Desk) -> None:
    with st.form("add_alert", clear_on_submit=True):
        c = st.columns([3, 1.4, 1.6, 3, 1])
        symbol = c[0].text_input("Symbol", placeholder="NSE:RELIANCE, BINANCE:SOLUSDT, "
                                                       "NASDAQ:AAPL")
        op = c[1].selectbox("When price is", ["above", "below"])
        price = c[2].number_input("Price", min_value=0.0, format="%.6g")
        note = c[3].text_input("Note")
        c[4].write("")
        if c[4].form_submit_button("Add"):
            try:
                aid = alerts.add(desk.store, symbol, op, price, note)
                st.success(f"Alert #{aid} set.")
            except ValueError as exc:
                st.error(str(exc))
    st.caption("Checked on every tick (the 🔄 button, or `python -m market_desk watch`). "
               "Crypto is live; stocks are about 15 minutes delayed.")
    active = desk.store.alerts(active=True)
    quotes = load_quotes(tuple(sorted({a["symbol"] for a in active})))
    st.subheader("Active")
    for a in active:
        last = (quotes.get(a["symbol"]) or {}).get("last")
        c = st.columns([6, 1])
        c[0].write(f"#{a['id']} **{a['symbol']}** {a['op']} {a['price']:g}"
                   + (f" · now {last:g}" if last else "") + (f" · {a['note']}" if a["note"] else ""))
        if c[1].button("Remove", key=f"rm{a['id']}"):
            desk.store.delete_alert(a["id"])
            st.rerun()
    if not active:
        st.caption("No active alerts.")
    fired = desk.store.alerts(active=False)[:20]
    if fired:
        st.subheader("Fired")
        st.dataframe(pd.DataFrame(fired)[["id", "symbol", "op", "price", "fired_px", "note"]]
                     .assign(when=[when(a["fired_ts"]) for a in fired]),
                     hide_index=True, width="stretch")


def main() -> None:
    if not password_ok():
        return
    desk = get_desk()
    sidebar(desk)
    tabs = st.tabs(["🗺️ Heatmap", "🏁 Screen", "🧪 Backtest", "📝 Plans & paper",
                    "📰 News & sentiment", "🔔 Alerts"])
    with tabs[0]:
        heatmap_tab()
    with tabs[1]:
        screen_tab(desk)
    with tabs[2]:
        backtest_tab(desk)
    with tabs[3]:
        paper_tab(desk)
    with tabs[4]:
        news_tab(desk)
    with tabs[5]:
        alerts_tab(desk)


main()
