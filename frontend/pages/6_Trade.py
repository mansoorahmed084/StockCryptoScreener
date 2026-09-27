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
from backend.trading import ideas, risk  # noqa: E402
from backend.trading.manager import TradeError, TradeManager  # noqa: E402
from frontend import trade_hours_view  # noqa: E402

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
    free = m.free_inr()
    budget = (f" — now Rs {risk.margin_budget(free):,.0f} of Rs {free:,.0f} free"
              if free is not None else "")
    st.markdown(f"**Gold-standard rules** (in code): stop loss ≤ {risk.MAX_STOP_PCT:g}% "
                f"from entry · margin ≤ {risk.MAX_MARGIN_PCT_OF_FREE:g}% of free balance"
                f"{budget} · leverage ≤ {risk.MAX_LEVERAGE}x. Only a trade you tick "
                "**override** on may break them.")
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
    size_by = c3.radio("Size by", ["risk", "margin"], horizontal=True, key="t_size_by",
                       format_func={"risk": "Rs I can lose", "margin": "Rs of margin"}.get)
    risk_inr = margin_inr = 0.0
    if size_by == "risk":
        risk_inr = c3.number_input("Risk (Rs lost if the stop is hit)", min_value=10.0,
                                   value=min(200.0, m.limits.max_risk_inr), step=50.0,
                                   key="t_risk")
    else:
        free = m.free_inr()
        default_margin = risk.margin_budget(free) if free else 1000.0
        margin_inr = c3.number_input("Margin (Rs)", min_value=50.0,
                                     value=float(round(max(50.0, default_margin))), step=50.0,
                                     key="t_margin")
    lev = c3.slider("Leverage", 1, max(1, m.limits.max_leverage), 2, key="t_lev")
    override = c3.checkbox("Override the gold-standard rules (bigger position)",
                           key="t_override",
                           help="Only for a trade you explicitly want bigger than the rules "
                                "allow. It is logged as overridden.")

    req = risk.TradeRequest(pair=pair, side=side, stop_loss=sl, take_profit=tp,
                            risk_inr=risk_inr, leverage=lev, entry_type=kind,
                            limit_price=limit, margin_inr=margin_inr, override=override)
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


def trail_note(m: TradeManager, p: dict) -> None:
    """Trailing-stop state of a position opened by this tool, with an on/off switch."""
    from backend.trading import trailing

    t = m.store.latest_for_pair(p["pair"], ("open",))
    if t is None:
        st.caption("Opened by hand: the trailing stop leaves it alone.")
        return
    s = trailing.Settings.from_config(load_config().trading.get("trailing"))
    entry = float(p["avg_price"] or t["entry"])
    initial = float(t["initial_stop"] or t["stop_loss"] or 0)
    r = abs(entry - initial)
    sign = 1 if float(p["active_pos"]) > 0 else -1
    start = entry + sign * s.activate_r * r
    on = st.toggle("Trailing stop", value=bool(t["trail"]), key=f"trail_{p['pair']}")
    if on != bool(t["trail"]):
        m.store.update_trade(t["id"], trail=int(on))
    best = t["best_price"]
    st.caption(f"1R = {r:g}. The stop moves to breakeven at {start:g}, then follows the best "
               f"price {s.trail_r:g}R behind it. Best so far: {best or '—'}. Needs "
               "`trade watch` running." if on else "Trailing is off for this trade.")


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
            trail_note(m, p)
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
                        "Price": o.get("stop_price") or o.get("price"),
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


@st.cache_resource(show_spinner=False)
def screener_service():
    from backend.service import ScreenerService
    return ScreenerService(load_config(), refresh=False)


def setup_settings() -> ideas.Settings:
    return ideas.Settings.from_config(load_config().trading.get("setups"))


@st.dialog("Place this trade?")
def confirm_place(m: TradeManager, idea: dict) -> None:
    word = "LIVE" if m.live else "dry-run"
    st.markdown(f"**LONG {idea['coin']}** ({idea['timeframe']} {idea['pattern']}) at market\n\n"
                f"Stop loss **{idea['stop']:g}** · target **{idea['target']:g}**\n\n"
                f"{idea['reason']}")
    st.caption("Size, stop and rules are checked again at the current price before "
               "anything is sent.")
    a, b = st.columns(2)
    if a.button(f"Yes, place {word}", type="primary"):
        try:
            with st.spinner("Placing entry, then stop loss and target…"):
                trade_id = ideas.place(m, idea["id"], setup_settings())
            st.success(f"Placed: trade #{trade_id}.")
        except Exception as exc:
            st.error(f"Refused: {exc}")
    if b.button("Cancel"):
        st.rerun()


def setups(m: TradeManager) -> None:
    st.subheader("Setups from the scan")
    st.caption("The scanner's buy setups with the trade each would make. Nothing is placed "
               "until you tap Place and confirm. A setup you traded is never offered "
               "again, and a coin rests 24h after any trade on it, including one you "
               "closed by hand.")
    s = setup_settings()
    if st.button(f"Scan the top {s.top} coins now (places nothing)"):
        with st.spinner("Scanning… about a minute"):
            try:
                new = ideas.scan(m, ideas.find_setups(screener_service(), s.top), s)
                st.success(f"{len(new)} new setup(s).")
            except Exception as exc:
                st.error(f"Scan failed: {exc}")
    rows = m.store.ideas(60)
    if not rows:
        st.caption("No setups yet. Scan now, or run `python -m backend.cli trade scan`.")
        return
    fresh_ms = s.max_age_minutes * 60_000
    now = time.time() * 1000
    ready = [i for i in rows if i["status"] == ideas.READY and now - i["ts_ms"] <= fresh_ms]
    for i in ready:
        a, b = st.columns([5, 1])
        a.markdown(f"🟢 **{i['coin']}** {i['timeframe']} {i['pattern']} · SL {i['stop']:g} · "
                   f"TP {i['target']:g} · {i['rr']:.1f}R — {i['reason']}")
        if b.button("Place", key=f"idea_{i['id']}", type="primary"):
            confirm_place(m, i)
    if not ready:
        st.caption("No setup is ready to place right now.")
    with st.expander(f"All recent setups ({len(rows)})"):
        st.dataframe(pd.DataFrame([{
            "When": time.strftime("%m-%d %H:%M", time.localtime(i["ts_ms"] / 1000)),
            "Coin": i["coin"], "TF": i["timeframe"], "Pattern": i["pattern"],
            "Status": i["status"], "SL": i["stop"], "TP": i["target"],
            "R": round(i["rr"], 1), "Why / plan": i["reason"]} for i in rows]),
            hide_index=True, width="stretch")


def main() -> None:
    m = manager()
    header(m)
    trade_hours_view.render()
    setups(m)
    st.divider()
    new_trade(m)
    st.divider()
    positions(m)
    orders(m)
    panic(m)
    log(m)


main()
