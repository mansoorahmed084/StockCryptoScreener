"""Best time to trade — a 24-hour IST strip. Green = high liquidity, white = no trade."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from backend.data.binance_futures import BinanceFutures
from backend.screener import trade_hours as th


@st.cache_data(ttl=3600, show_spinner=False)
def _profile() -> tuple[list[th.HourSlot], bool]:
    """(slots, live) — live is False when the fallback hours were used."""
    try:
        klines = BinanceFutures().klines("BTCUSDT", "1h", 1000)
        return th.hour_profile(klines), True
    except Exception:
        return th.fallback_profile(), False


def _cell(slot: th.HourSlot, is_now: bool) -> str:
    bg, fg = ("#1f9d55", "#ffffff") if slot.good else ("#ffffff", "#555555")
    border = "3px solid #ff9800" if is_now else "1px solid #cccccc"
    tip = f"{slot.ist_start}–{slot.ist_end} IST"
    if slot.ratio is not None:
        tip += f" · volume {slot.ratio:.2f}x an average hour"
    return (f'<div title="{tip}" style="flex:1;min-width:0;background:{bg};color:{fg};'
            f'border:{border};border-radius:3px;padding:6px 0;text-align:center;'
            f'font-size:11px;line-height:1.2">{slot.ist_start[:2]}<br>'
            f'<span style="font-size:9px">:30</span></div>')


def render() -> None:
    slots, live = _profile()
    now = datetime.now(timezone.utc)
    cur = th.current_slot(slots, now)
    weekend = now.astimezone(th.IST).weekday() >= 5

    st.subheader("Best time to trade (IST)")
    cells = "".join(_cell(s, s.utc_hour == cur.utc_hour) for s in slots)
    st.markdown(f'<div style="display:flex;gap:2px;margin-bottom:6px">{cells}</div>',
                unsafe_allow_html=True)

    now_ist = now.astimezone(th.IST).strftime("%H:%M")
    if cur.good:
        status = f"🟢 **Now {now_ist} IST — good time to trade.**"
    else:
        nxt = th.next_good(slots, now)
        status = f"⚪ **Now {now_ist} IST — no trade.**"
        if nxt:
            status += f" Next good slot starts {nxt.ist_start} IST."
    windows = ", ".join(f"{a}–{b}" for a, b in th.good_windows(slots)) or "—"
    st.markdown(f"{status} Good windows: {windows}.")

    notes = []
    if weekend:
        notes.append("Weekend: liquidity is thin all day, even in the green hours.")
    notes.append("Green = BTC perp volume at least "
                 f"{th.GOOD_RATIO:.1f}x an average hour (median of the last ~6 weeks, "
                 "weekdays). Orange box = now.")
    if not live:
        notes.append("Binance was not reachable, so these are the usual "
                     "London-open and London/New York overlap hours.")
    st.caption(" ".join(notes))
