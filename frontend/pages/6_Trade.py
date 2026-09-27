"""Trade — open, protect and close CoinDCX INR-margined futures trades.

The engine is backend/trading/. Nothing is sent unless ``trading.mode`` in
config.yaml is ``live``; every write needs the pair name typed to confirm.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.config import load_config  # noqa: E402
from backend.trading import risk  # noqa: E402
from backend.trading.manager import TradeError, TradeManager  # noqa: E402

st.set_page_config(page_title="Trade", layout="wide")


@st.cache_resource(show_spinner=False)
def manager() -> TradeManager:
    return TradeManager.from_config(load_config())


@st.cache_data(ttl=3600, show_spinner=False)
def pairs() -> list[str]:
    return sorted(manager().client.active_pairs())


@st.cache_data(ttl=10, show_spinner=False)
def price(pair: str) -> float:
    return manager().last_price(pair)


def coin(pair: str) -> str:
    return pair.removeprefix("B-").removesuffix("_USDT")


def header(m: TradeManager) -> None:
    st.title("Trade")
    if m.live:
        st.error("**LIVE** — orders go to your CoinDCX account with real money.")
    else:
        st.info("**DRY RUN** — orders are checked and logged, nothing is sent. "
                "Set `trading.mode: live` in config.yaml to trade.")
    if not m.client.has_keys:
        st.warning("No API keys. Put `COINDCX_API_KEY` and `COINDCX_API_SECRET` in `.env`. "
                   "Previews still work, sized with the spot USDT/INR price.")
    if m.halted:
        st.error("Trading is **halted** (panic). New trades are blocked.")
        if st.button("Allow new trades again"):
            m.resume()
            st.rerun()
    lim = m.limits
    st.caption(f"Your limits: risk ≤ Rs {lim.max_risk_inr:,.0f} a trade · margin ≤ "
               f"Rs {lim.max_margin_inr:,.0f} · leverage ≤ {lim.max_leverage}x · "
               f"{lim.max_open_positions} positions · stop after Rs "
               f"{lim.max_daily_loss_inr:,.0f} lost in a day (`trading.limits`).")


def new_trade(m: TradeManager) -> None:
    st.subheader("New trade")
    all_pairs = pairs()
    default = all_pairs.index("B-BTC_USDT") if "B-BTC_USDT" in all_pairs else 0
    c1, c2, c3 = st.columns(3)
    pair = c1.selectbox("Coin", all_pairs, index=default, format_func=coin, key="t_pair")
    now = price(pair)
    c1.caption(f"Now {now:g} USDT")
    side = c1.radio("Side", [risk.LONG, risk.SHORT], horizontal=True, key="t_side",
                    format_func=str.title)
    kind = c1.radio("Entry", [risk.MARKET, risk.LIMIT], horizontal=True, key="t_kind",
                    format_func={risk.MARKET: "Market (now)", risk.LIMIT: "Limit"}.get)
    limit = (c1.number_input("Limit price", value=now, format="%.6g", key="t_limit")
             if kind == risk.LIMIT else None)
    long = side == risk.LONG
    sl = c2.number_input("Stop loss (required)", value=now * (0.97 if long else 1.03),
                         format="%.6g", key=f"t_sl_{pair}_{side}")
    use_tp = c2.checkbox("Set a target", value=True, key="t_use_tp")
    tp = (c2.number_input("Target", value=now * (1.06 if long else 0.94), format="%.6g",
                          key=f"t_tp_{pair}_{side}") if use_tp else None)
    risk_inr = c3.number_input("Risk (Rs lost if the stop is hit)", min_value=10.0,
                               value=min(200.0, m.limits.max_risk_inr), step=50.0,
                               key="t_risk")
    lev = c3.slider("Leverage", 1, max(1, m.limits.max_leverage), 2, key="t_lev")

    req = risk.TradeRequest(pair=pair, side=side, stop_loss=sl, take_profit=tp,
                            risk_inr=risk_inr, leverage=lev, entry_type=kind,
                            limit_price=limit)
    try:
        plan = m.preview(req)
    except Exception as exc:
        st.error(f"Could not build the trade: {exc}")
        return
    st.code(plan.summary(), language=None)
    if not plan.ok:
        st.caption("Fix the BLOCKED lines to place this trade.")
        return
    word = "LIVE" if m.live else "dry-run"
    typed = st.text_input(f"Type {pair} to confirm", key="t_confirm")
    if st.button(f"Place {word} {side} {coin(pair)}", type="primary",
                 disabled=typed.strip().upper() != pair):
        try:
            with st.spinner("Placing entry, then stop loss and target…"):
                _, trade_id = m.open(req, confirm=typed)
        except Exception as exc:
            st.error(f"Refused: {exc}")
        else:
            st.success(f"Trade #{trade_id} done ({word}). See it below and in the log.")


def positions(m: TradeManager) -> None:
    st.subheader("Open positions")
    if not m.client.has_keys:
        st.caption("Needs API keys.")
        return
    try:
        held = m.positions()
    except Exception as exc:
        st.error(f"Could not read positions: {exc}")
        return
    if not held:
        st.caption("None.")
    for p in held:
        pair = p["pair"]
        qty = float(p["active_pos"])
        sl_now = p.get("stop_loss_trigger")
        with st.expander(f"{'LONG' if qty > 0 else 'SHORT'} {abs(qty):g} {coin(pair)} @ "
                         f"{p['avg_price']} · SL {sl_now or 'NONE ⚠'} · "
                         f"TP {p.get('take_profit_trigger') or 'none'} · "
                         f"now {price(pair):g}", expanded=not sl_now):
            a, b, c = st.columns(3)
            new_sl = a.number_input("New stop loss", value=float(sl_now or 0) or None,
                                    format="%.6g", key=f"p_sl_{pair}")
            new_tp = b.number_input("New target",
                                    value=float(p.get("take_profit_trigger") or 0) or None,
                                    format="%.6g", key=f"p_tp_{pair}")
            typed = c.text_input(f"Type {pair} to confirm", key=f"p_ok_{pair}")
            ok = typed.strip().upper() == pair
            if c.button("Update SL / target", disabled=not ok, key=f"p_up_{pair}"):
                sl_arg = new_sl if new_sl and new_sl != float(sl_now or 0) else None
                tp_arg = (new_tp if new_tp and new_tp != float(p.get("take_profit_trigger")
                                                               or 0) else None)
                try:
                    m.set_tpsl(pair, stop_loss=sl_arg, take_profit=tp_arg)
                    st.success("Updated.")
                except Exception as exc:
                    st.error(f"Refused: {exc}")
            if c.button("Close at market", disabled=not ok, key=f"p_close_{pair}"):
                try:
                    m.close(pair, confirm=typed)
                    st.success("Exit sent.")
                except Exception as exc:
                    st.error(f"Refused: {exc}")


def orders(m: TradeManager) -> None:
    if not m.client.has_keys:
        return
    try:
        rows = m.client.orders()
    except Exception as exc:
        st.error(f"Could not read orders: {exc}")
        return
    st.subheader(f"Open orders ({len(rows)})")
    if not rows:
        st.caption("None.")
        return
    df = pd.DataFrame([{"Coin": coin(o["pair"]), "Side": o["side"], "Type": o["order_type"],
                        "Qty": o.get("total_quantity"),
                        "Price": o.get("price") or o.get("stop_price"),
                        "Status": o["status"], "id": o["id"]} for o in rows])
    st.dataframe(df, hide_index=True, width="stretch")
    oid = st.selectbox("Cancel an order", [""] + list(df["id"]), key="o_cancel")
    if oid and st.button("Cancel it", key="o_cancel_btn"):
        try:
            m.cancel_order(oid)
            st.success("Cancel sent.")
        except Exception as exc:
            st.error(f"Refused: {exc}")


def panic(m: TradeManager) -> None:
    with st.expander("🛑 Panic: cancel everything and close every position"):
        typed = st.text_input("Type PANIC", key="panic_ok")
        if st.button("Close everything now", type="primary", disabled=typed != "PANIC"):
            for line in m.panic(typed):
                st.write(line)


def log(m: TradeManager) -> None:
    with st.expander("Log of every order sent (or not sent, in dry run)"):
        ev = m.store.events(50)
        if not ev:
            st.caption("Empty.")
            return
        st.dataframe(pd.DataFrame([{
            "When": time.strftime("%m-%d %H:%M:%S", time.localtime(e["ts_ms"] / 1000)),
            "OK": "✓" if e["ok"] else "✗", "Action": e["action"],
            "Sent": e["request"], "Answer": e["response"][:300]} for e in ev]),
            hide_index=True, width="stretch")
        st.caption("Keep `python -m backend.cli trade watch` running in live mode: it "
                   "adds SL/TP when a limit entry fills and warns about any position "
                   "with no stop loss.")


def main() -> None:
    m = manager()
    header(m)
    new_trade(m)
    st.divider()
    positions(m)
    orders(m)
    panic(m)
    log(m)


main()
