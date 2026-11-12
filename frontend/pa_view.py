"""Drawing for the Price Action page: structure, order blocks, liquidity,
equal highs / lows, fair value gaps, daily levels and setups, on top of the
shared candle figure from frontend/pattern_view.py.

Detection is in backend/screener/price_action.py; this module only draws it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backend.screener import price_action as pa
from frontend import pattern_view as pv


def compact(v: float) -> str:
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"{v / div:.2f}{unit}"
    return f"{v:.0f}"


def draw(fig: go.Figure, df: pd.DataFrame, cx: pa.Concepts, tf: str, show: dict,
         p: dict, max_internal: int = 12, max_swing: int = 8) -> None:
    n = len(df)
    step = pd.Timedelta(seconds=pv.timeframe_to_seconds(tf))
    end_i = n - 1 + max(5, int(n * pv.PROJECT))
    x_of = lambda i: df.index[0] + step * i
    bull, bear = p["support"], p["resistance"]
    color = lambda side: bull if side == pa.BULL else bear
    span = (float(df["high"].max()) - float(df["low"].min())) * 0.012

    def line(x0, x1, y, col, dash, width, hover):
        fig.add_trace(go.Scatter(x=[x_of(x0), x_of(x1)], y=[y, y], mode="lines",
                                 line=dict(color=col, width=width, dash=dash),
                                 hovertemplate=hover + "<extra></extra>", showlegend=False),
                      row=1, col=1)

    def text(x, y, s, col, size=10, anchor="middle", pos="bottom"):
        fig.add_annotation(x=x_of(x), y=y, yref="y", text=s, showarrow=False,
                           xanchor={"middle": "center", "end": "right"}.get(anchor, "left"),
                           yanchor=pos, font=dict(size=size, color=col))

    # Order blocks and gaps first, so lines draw over them.
    if show.get("ob"):
        for ob in cx.order_blocks:
            fill = p["fill_bull"] if ob.side == pa.BULL else p["fill_bear"]
            fig.add_shape(type="rect", x0=x_of(ob.i), x1=x_of(end_i), y0=ob.bottom,
                          y1=ob.top, fillcolor=fill,
                          line=dict(color=color(ob.side), width=1,
                                    dash="solid" if ob.scope == "swing" else "dot"),
                          layer="below", row=1, col=1)
            # Label inside the box at its left end; the right edge belongs to
            # the liquidity labels, so the two never stack.
            text(ob.i, (ob.top + ob.bottom) / 2,
                 f"OB {compact(ob.volume)} ({ob.share:.0%})",
                 color(ob.side), 9, "start", "middle")
    if show.get("fvg"):
        for g in cx.gaps:
            fig.add_shape(type="rect", x0=x_of(g.i - 1), x1=x_of(end_i), y0=g.bottom,
                          y1=g.top, fillcolor=p["fib"], opacity=0.10, line_width=0,
                          layer="below", row=1, col=1)
            text(g.i - 1, g.top if g.side == pa.BULL else g.bottom,
                 "FVG", p["fib"], 9, "start", "bottom" if g.side == pa.BULL else "top")

    if show.get("liquidity"):
        for x in cx.liquidity:
            col = bear if x.side == pa.BULL else bull       # stops above highs are red
            if x.status == "open":
                line(x.i, end_i, x.price, col, "dash", 1.2,
                     f"{'Buy' if x.side == pa.BULL else 'Sell'}-side liquidity "
                     f"{pv.fmt(x.price)} · volume {compact(x.volume)}")
                text(end_i, x.price, f"{compact(x.volume)} ({x.share:.0%})", col, 10,
                     "end", "bottom")
            elif show.get("taken"):
                line(x.i, x.end_i, x.price, p["muted"], "dot", 1,
                     f"Liquidity {pv.fmt(x.price)} {x.status}")
        if show.get("grabs"):
            for side in (pa.BULL, pa.BEAR):
                gs = [x for x in cx.liquidity if x.side == side and x.status == "grabbed"]
                if not gs:
                    continue
                ys = [float(df["high"].iloc[x.end_i]) + span if side == pa.BULL
                      else float(df["low"].iloc[x.end_i]) - span for x in gs]
                fig.add_trace(go.Scatter(
                    x=[df.index[x.end_i] for x in gs], y=ys, mode="markers",
                    marker=dict(symbol="x-thin", size=9, line=dict(width=2, color=p["ink2"])),
                    hovertemplate=f"{'Buy' if side == pa.BULL else 'Sell'}-side grab: wick "
                                  "through the swing, close back inside<extra></extra>",
                    showlegend=False), row=1, col=1)

    if show.get("equals"):
        for e in cx.equals:
            col = bear if e.side == pa.BULL else bull
            line(e.i0, e.i1, e.price, col, "dot", 1.5, f"{'EQH' if e.side == pa.BULL else 'EQL'}"
                                                       f" {pv.fmt(e.price)}")
            text((e.i0 + e.i1) / 2, e.price, "EQH" if e.side == pa.BULL else "EQL", col, 9,
                 pos="bottom" if e.side == pa.BULL else "top")

    for key, lst, cap, width, size in (("internal", cx.internal, max_internal, 1, 9),
                                       ("swing", cx.swing, max_swing, 1.6, 11)):
        if not show.get(key):
            continue
        for b in lst[-cap:]:
            col = color(b.side)
            line(b.level_i, b.i, b.level, col, "dash" if key == "internal" else "solid",
                 width, f"{key.title()} {b.kind} {'up' if b.side == pa.BULL else 'down'}"
                        f" {pv.fmt(b.level)}{' · after a grab' if b.swept else ''}")
            label = b.kind + ("+" if b.swept else "")
            text((b.level_i + b.i) / 2, b.level, label, col, size,
                 pos="bottom" if b.side == pa.BULL else "top")

    if show.get("daily") and cx.htf_levels:
        for name, v in cx.htf_levels.items():
            line(max(0, n - 40), end_i, v, p["ink2"], "dashdot", 1, f"{name} {pv.fmt(v)}")
            text(max(0, n - 40), v, f"{name} {pv.fmt(v)}", p["ink2"], 9, "start")

    if show.get("setups") and cx.setups:
        for side in (pa.BULL, pa.BEAR):
            ss = [s for s in cx.setups if s.side == side]
            if not ss:
                continue
            ys = [float(df["low"].iloc[s.i]) - 2.5 * span if side == pa.BULL
                  else float(df["high"].iloc[s.i]) + 2.5 * span for s in ss]
            fig.add_trace(go.Scatter(
                x=[df.index[s.i] for s in ss], y=ys, mode="markers+text",
                text=["SB"] * len(ss),
                textposition="bottom center" if side == pa.BULL else "top center",
                textfont=dict(size=10, color=color(side)),
                marker=dict(symbol="triangle-up" if side == pa.BULL else "triangle-down",
                            size=11, color=color(side)),
                customdata=[[s.stop] for s in ss],
                hovertemplate=f"Sweep-break {'long' if side == pa.BULL else 'short'} setup"
                              "<br>stop %{customdata[0]:,.6g}<extra></extra>",
                showlegend=False), row=1, col=1)


LEGEND = ("Green: bullish, orange: bearish. Solid lines and big labels: swing "
          "structure; dashed and small: internal structure. CHoCH = break against the "
          "trend, BOS = with it; a + means the leg started with a liquidity grab. "
          "Boxes: live order blocks with their candle's volume and share. Dashed lines "
          "with a volume label: untaken liquidity (stops above highs, below lows). "
          "× = a grab (wick through, close back). Yellow boxes: unfilled fair value "
          "gaps. SB = sweep-break style setup in the daily trend's direction.")


def render_details(df: pd.DataFrame, cx: pa.Concepts) -> None:
    last = float(df["close"].iloc[-1])
    st.markdown("**Read**")
    st.markdown("\n".join(f"- {s}" for s in pa.notes(cx, last)))
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Liquidity**")
        rows = [{"Side": "Buy-side (above)" if x.side == pa.BULL else "Sell-side (below)",
                 "Price": pv.fmt(x.price), "Distance": pv.pct(x.price, last),
                 "Volume": compact(x.volume),
                 "Share": f"{x.share:.0%}" if x.status == "open" else "",
                 "Status": x.status,
                 "Formed": f"{df.index[x.i]:%m-%d %H:%M}"}
                for x in sorted(cx.liquidity, key=lambda x: (x.status != "open", -x.price))]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with c2:
        st.markdown("**Order blocks**")
        rows = [{"Zone": f"{pv.fmt(ob.bottom)}–{pv.fmt(ob.top)}",
                 "Kind": f"{ob.scope} {'demand' if ob.side == pa.BULL else 'supply'}",
                 "Distance": "inside" if ob.bottom <= last <= ob.top else
                 pv.pct(ob.bottom if ob.bottom > last else ob.top, last),
                 "Volume": compact(ob.volume), "Share": f"{ob.share:.0%}",
                 "Formed": f"{df.index[ob.i]:%m-%d %H:%M}"}
                for ob in sorted(cx.order_blocks, key=lambda o: -o.top)]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**Last structure breaks**")
        rows = [{"Time": f"{df.index[b.i]:%m-%d %H:%M}", "Scope": b.scope,
                 "Break": f"{'↑' if b.side == pa.BULL else '↓'} {b.kind}",
                 "Level": pv.fmt(b.level), "After grab": "yes" if b.swept else ""}
                for b in sorted(cx.swing[-5:] + cx.internal[-5:], key=lambda b: -b.i)]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with c4:
        st.markdown("**Sweep-break style setups**")
        if cx.setups:
            rows = [{"Time": f"{df.index[s.i]:%m-%d %H:%M}",
                     "Side": "long" if s.side == pa.BULL else "short",
                     "Broke": pv.fmt(s.level), "Stop (origin)": pv.fmt(s.stop)}
                    for s in reversed(cx.setups[-8:])]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.caption("None on this chart.")
        st.caption("Same break, grab and daily-trend rules as the SMC scanner, but "
                   "without its filters and trade management. Only the 4h version was "
                   "tested (+0.245R per trade on unseen coins). The scanner's calls "
                   "are the real signal.")


# ---------------------------------------------------------------- CRT
def draw_crt(fig: go.Figure, df: pd.DataFrame, r: pa.CRT, tf: str, p: dict,
             max_ranges: int = 12, max_setups: int = 15) -> None:
    """Previous HTF range lines, the sweep ("Manipulation") and confirmed
    setups with entry, stop and target zones."""
    n = len(df)
    step = pd.Timedelta(seconds=pv.timeframe_to_seconds(tf))
    end_i = n - 1 + max(5, int(n * pv.PROJECT))
    x_of = lambda i: df.index[0] + step * i
    hl = p["ink2"]
    for rg in r.ranges[-max_ranges:]:
        x1 = x_of(rg.end_i + 1 if rg.end_i < n - 1 else end_i)
        for y, name in ((rg.high, "CRT high"), (rg.low, "CRT low")):
            fig.add_trace(go.Scatter(
                x=[x_of(rg.start_i), x1], y=[y, y], mode="lines",
                line=dict(color=hl, width=1, dash="dot"),
                hovertemplate=f"{name} (previous {pa.CRT_NAME.get(r.htf, r.htf)} candle) "
                              f"{pv.fmt(y)}<extra></extra>", showlegend=False), row=1, col=1)
    for s in r.setups[-max_setups:]:
        top = s.side == pa.BEAR
        fig.add_annotation(x=x_of(s.extreme_i), y=s.extreme, yref="y", text="Manipulation",
                           showarrow=False, yanchor="bottom" if top else "top",
                           font=dict(size=10, color=p["fib"]))
        if s.confirm_i < 0:
            continue
        x0 = x_of(s.confirm_i)
        x1 = x_of(s.exit_i if s.exit_i >= 0 else end_i)
        for y0, y1, fill in ((s.entry, s.stop, p["fill_bear"]),
                             (s.entry, s.target, p["fill_bull"])):
            fig.add_shape(type="rect", x0=x0, x1=x1, y0=min(y0, y1), y1=max(y0, y1),
                          fillcolor=fill.replace("0.12", "0.28"),
                          line=dict(width=1, color=p["support"] if fill == p["fill_bull"]
                                    else p["resistance"]),
                          layer="below", row=1, col=1)
        mark = {"won": "✓", "lost": "✗", "expired": "–", "open": "…"}[s.outcome]
        fig.add_annotation(x=x0, y=s.target, yref="y", xanchor="left",
                           text=f"CRT {'long' if s.side == pa.BULL else 'short'} "
                                f"{s.trigger} {s.rr:.1f}R {mark}", showarrow=False,
                           yanchor="top" if top else "bottom",
                           font=dict(size=10, color=p["ink"]))


def render_crt(df: pd.DataFrame, r: pa.CRT) -> None:
    st_ = r.stats()
    st.markdown(f"**CRT on previous {pa.CRT_NAME.get(r.htf, r.htf)} candles**")
    c = st.columns(6)
    c[0].metric("Sweeps", st_["swept"])
    c[1].metric("Confirmed", st_["confirmed"])
    c[2].metric("Won", st_["won"])
    c[3].metric("Lost", st_["lost"])
    c[4].metric("Win rate", "—" if np.isnan(st_["win_rate"]) else f"{st_['win_rate']:.0%}")
    c[5].metric("Avg R", "—" if np.isnan(st_["avg_r"]) else f"{st_['avg_r']:+.2f}")
    rows = [{"Time": f"{df.index[s.confirm_i]:%m-%d %H:%M}",
             "Side": "long" if s.side == pa.BULL else "short", "Trigger": s.trigger,
             "Entry": pv.fmt(s.entry), "Stop": pv.fmt(s.stop), "Target": pv.fmt(s.target),
             "R:R": f"{s.rr:.1f}", "Outcome": s.outcome}
            for s in reversed(r.setups) if s.confirm_i >= 0]
    if rows:
        st.dataframe(pd.DataFrame(rows[:12]), hide_index=True, width="stretch")
    st.caption("Range = the previous higher-timeframe candle's high and low. A wick past "
               "one side inside the next candle is the sweep (Manipulation). It is "
               "confirmed only by a fair value gap or a structure shift back inside, in "
               "the same candle, with at least 1:1 to the far side. Entry at that close, "
               "stop at the sweep extreme, target the other side. Stop is checked before "
               "target; no fees. A handful of trades on one chart proves nothing.")
