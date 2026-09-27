"""Trade sizing and safety checks for INR-margined CoinDCX futures.

Pure functions, no network. A trade is sized from the INR you are willing to
lose if the stop loss is hit, then checked against the exchange's rules for
the pair and your own limits in config.yaml (``trading.limits``). A plan with
any error must never be sent.

Prices are in USDT (the pairs are USDT perpetuals); margin, risk and P&L are
in INR at CoinDCX's fixed USDT->INR conversion price.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

LONG, SHORT = "long", "short"
MARKET, LIMIT = "market", "limit"

# Gold-standard rules, fixed in code on purpose (not in config.yaml). Every
# trade must meet them; only a trade the owner explicitly asks to make bigger
# (TradeRequest.override) may break them. The autopilot never overrides.
MAX_STOP_PCT = 10.0            # a stop further than this from entry: no trade
MAX_MARGIN_PCT_OF_FREE = 5.0   # margin per trade, % of the free INR futures balance
MAX_LEVERAGE = 5
MIN_SUGGEST_RR = 2.0           # a setup is only suggested when its reward is >= 2x its risk


def margin_budget(free_inr: float) -> float:
    return max(0.0, free_inr) * MAX_MARGIN_PCT_OF_FREE / 100.0


@dataclass(frozen=True)
class Limits:
    max_risk_inr: float = 500.0
    max_margin_inr: float = 5000.0
    max_leverage: int = 5
    max_open_positions: int = 3
    max_daily_loss_inr: float = 1500.0
    min_stop_pct: float = 0.3          # SL closer than this % of entry is refused
    allowed_pairs: tuple[str, ...] = ()  # empty = every active INR pair

    @classmethod
    def from_config(cls, raw: dict[str, Any] | None) -> "Limits":
        raw = dict(raw or {})
        if "allowed_pairs" in raw:
            raw["allowed_pairs"] = tuple(to_pair(p) for p in raw["allowed_pairs"] or ())
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass(frozen=True)
class Instrument:
    pair: str
    status: str
    price_step: Decimal
    qty_step: Decimal
    min_qty: float
    max_qty: float
    max_market_qty: float
    min_notional: float
    taker_fee_pct: float
    multiplier_up: float
    multiplier_down: float
    exit_only: bool
    leverage_tiers: dict[int, float]   # leverage -> max position size (USDT)
    max_leverage: float
    maint_margin_pct: float

    @classmethod
    def from_api(cls, d: dict) -> "Instrument":
        tiers = {int(float(k)): float(v)
                 for k, v in (d.get("dynamic_position_leverage_details") or {}).items()}
        safety = d.get("dynamic_safety_margin_details") or {}
        first_mm = (float(safety[min(safety, key=float)]) if safety
                    else float(d.get("safety_percentage") or 2.0))
        return cls(
            pair=d["pair"], status=str(d.get("status", "")),
            price_step=Decimal(str(d["price_increment"])),
            qty_step=Decimal(str(d["quantity_increment"])),
            min_qty=float(d.get("min_quantity") or 0),
            max_qty=float(d.get("max_quantity") or float("inf")),
            max_market_qty=float(d.get("max_market_order_quantity") or float("inf")),
            min_notional=float(d.get("min_notional") or 0),
            taker_fee_pct=float(d.get("taker_fee") or 0.075),
            multiplier_up=float(d.get("multiplier_up") or 100),
            multiplier_down=float(d.get("multiplier_down") or 100),
            exit_only=bool(d.get("exit_only")),
            leverage_tiers=tiers,
            max_leverage=float(d.get("max_leverage_long") or 1),
            maint_margin_pct=first_mm,
        )

    def max_leverage_for(self, notional_usdt: float) -> int:
        ok = [lev for lev, cap in self.leverage_tiers.items() if notional_usdt <= cap]
        return max(ok) if ok else int(self.max_leverage)


@dataclass
class TradeRequest:
    pair: str
    side: str                       # long | short
    stop_loss: float
    risk_inr: float
    leverage: int
    take_profit: float | None = None
    entry_type: str = MARKET        # market | limit
    limit_price: float | None = None
    margin_inr: float = 0.0         # > 0: size by this margin instead of by risk_inr
    override: bool = False          # owner asked to break the gold-standard rules


@dataclass
class Plan:
    request: TradeRequest
    entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float | None = None
    qty: float = 0.0
    notional_usdt: float = 0.0
    margin_inr: float = 0.0
    risk_inr: float = 0.0           # loss at the stop, fees included
    reward_inr: float | None = None
    liq_price: float = 0.0          # estimate for an isolated position
    rate: float = 0.0               # INR per USDT
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def order_side(self) -> str:
        return "buy" if self.request.side == LONG else "sell"

    @property
    def rr(self) -> float | None:
        return self.reward_inr / self.risk_inr if self.reward_inr and self.risk_inr else None

    def summary(self) -> str:
        r = self.request
        if not self.take_profit:
            target = "  target      none"
        elif self.rr is None:
            target = f"  target      {self.take_profit:g}"
        else:
            target = (f"  target      {self.take_profit:g}  -> make about Rs "
                      f"{self.reward_inr:,.0f}  ({self.rr:.1f}R)")
        lines = [
            f"{r.side.upper()} {self.qty:g} {r.pair} ({r.entry_type}) at {self.entry:g} USDT, "
            f"{r.leverage}x",
            f"  stop loss   {self.stop_loss:g}  -> lose about Rs {self.risk_inr:,.0f} (fees in)",
            target,
            f"  margin      Rs {self.margin_inr:,.0f}   size {self.notional_usdt:,.2f} USDT"
            f"   liquidation near {self.liq_price:g}",
            f"  USDT->INR   {self.rate:g}",
        ]
        lines += [f"  WARNING: {w}" for w in self.warnings]
        lines += [f"  BLOCKED: {e}" for e in self.errors]
        return "\n".join(lines)


def to_pair(coin_or_pair: str) -> str:
    """'sol' / 'SOLUSDT' / 'B-SOL_USDT' -> 'B-SOL_USDT'."""
    s = coin_or_pair.strip().upper()
    if s.startswith("B-"):
        return s
    if s.endswith("USDT"):
        s = s[:-4].rstrip("_/-")
    return f"B-{s}_USDT"


def round_step(value: float, step: Decimal, *, down: bool = False) -> float:
    q = (Decimal(str(value)) / step).quantize(
        Decimal(1), rounding=ROUND_DOWN if down else ROUND_HALF_UP)
    return float(q * step)


def liquidation_price(side: str, entry: float, leverage: int, maint_pct: float) -> float:
    """Isolated-margin estimate: margin (1/leverage) minus maintenance margin."""
    move = 1.0 / leverage - maint_pct / 100.0
    return entry * (1 - move) if side == LONG else entry * (1 + move)


def build_plan(req: TradeRequest, inst: Instrument, *, last_price: float, rate: float,
               limits: Limits, open_positions: int = 0, has_position: bool = False,
               loss_today_inr: float = 0.0, free_inr: float | None = None) -> Plan:
    plan = Plan(request=req, rate=rate)
    err, warn = plan.errors.append, plan.warnings.append

    if req.side not in (LONG, SHORT):
        err(f"side must be {LONG} or {SHORT}")
        return plan
    if req.entry_type not in (MARKET, LIMIT):
        err(f"entry type must be {MARKET} or {LIMIT}")
        return plan
    if req.entry_type == LIMIT and not req.limit_price:
        err("a limit entry needs a limit price")
        return plan
    if not (req.stop_loss and req.stop_loss > 0):
        err("every trade needs a stop loss")
        return plan
    if not (rate > 0 and last_price > 0):
        err("no live price or USDT->INR rate; try again")
        return plan

    step = inst.price_step
    entry = round_step(req.limit_price, step) if req.entry_type == LIMIT else last_price
    sl = round_step(req.stop_loss, step)
    tp = round_step(req.take_profit, step) if req.take_profit else None
    plan.entry, plan.stop_loss, plan.take_profit = entry, sl, tp

    # -- direction ----------------------------------------------------------
    long = req.side == LONG
    if long and not sl < entry:
        err(f"a long's stop loss ({sl:g}) must be below entry ({entry:g})")
    if not long and not sl > entry:
        err(f"a short's stop loss ({sl:g}) must be above entry ({entry:g})")
    if tp is not None and long and not tp > entry:
        err(f"a long's target ({tp:g}) must be above entry ({entry:g})")
    if tp is not None and not long and not tp < entry:
        err(f"a short's target ({tp:g}) must be below entry ({entry:g})")
    stop_dist = abs(entry - sl)
    if stop_dist / entry * 100 < limits.min_stop_pct:
        err(f"stop loss is {stop_dist / entry * 100:.2f}% away; the minimum is "
            f"{limits.min_stop_pct}% (trading.limits.min_stop_pct)")
    if plan.errors:
        return plan

    # -- size from risk, or from margin ------------------------------------
    fee = inst.taker_fee_pct / 100.0
    loss_per_unit_inr = (stop_dist + (entry + sl) * fee) * rate
    units = (req.margin_inr * req.leverage / (entry * rate) if req.margin_inr > 0
             else req.risk_inr / loss_per_unit_inr)
    qty = round_step(units, inst.qty_step, down=True)
    plan.qty = qty
    plan.notional_usdt = qty * entry
    plan.margin_inr = plan.notional_usdt * rate / req.leverage
    plan.risk_inr = qty * loss_per_unit_inr
    if tp is not None:
        plan.reward_inr = qty * (abs(tp - entry) - (entry + tp) * fee) * rate
    plan.liq_price = liquidation_price(req.side, entry, req.leverage, inst.maint_margin_pct)

    # -- exchange rules ------------------------------------------------------
    if inst.status != "active" or inst.exit_only:
        err(f"{req.pair} is not open for new positions on CoinDCX")
    if qty <= 0 or qty < inst.min_qty:
        err(f"size {qty:g} is below the minimum {inst.min_qty:g}; raise the risk or "
            "move the stop closer")
    if qty > inst.max_qty or (req.entry_type == MARKET and qty > inst.max_market_qty):
        err(f"size {qty:g} is above the exchange maximum")
    if plan.notional_usdt < inst.min_notional:
        err(f"order value {plan.notional_usdt:.2f} USDT is below the minimum "
            f"{inst.min_notional:g} USDT")
    if req.leverage < 1:
        err("leverage must be at least 1x")
    elif req.leverage > inst.max_leverage_for(plan.notional_usdt):
        err(f"{req.pair} allows at most {inst.max_leverage_for(plan.notional_usdt)}x "
            "at this size")
    if req.entry_type == LIMIT:
        hi = last_price * (1 + inst.multiplier_up / 100)
        lo = last_price * (1 - inst.multiplier_down / 100)
        if not lo <= entry <= hi:
            err(f"limit price must be between {lo:g} and {hi:g} right now")
        if long and entry > last_price or not long and entry < last_price:
            warn("this limit price is through the market; it will fill at once")
    if long and sl <= plan.liq_price or not long and sl >= plan.liq_price:
        err(f"the position would be liquidated near {plan.liq_price:g} before the stop "
            f"loss at {sl:g}; lower the leverage")

    # -- gold-standard rules -------------------------------------------------
    if req.override:
        warn("gold-standard rules OVERRIDDEN for this trade (asked for explicitly)")
    else:
        stop_pct = stop_dist / entry * 100
        if stop_pct > MAX_STOP_PCT:
            err(f"stop loss is {stop_pct:.1f}% away; the rule is at most {MAX_STOP_PCT:g}%")
        if req.leverage > MAX_LEVERAGE:
            err(f"leverage {req.leverage}x; the rule is at most {MAX_LEVERAGE}x")
        if free_inr is None:
            warn("free balance unknown (no API keys); the 5%-of-balance margin rule "
                 "is checked only with keys")
        elif plan.margin_inr > margin_budget(free_inr) + 0.005:
            err(f"margin Rs {plan.margin_inr:,.0f} is above {MAX_MARGIN_PCT_OF_FREE:g}% of your "
                f"free balance (Rs {margin_budget(free_inr):,.0f} of Rs {free_inr:,.0f})")

    # -- your limits ---------------------------------------------------------
    if limits.allowed_pairs and req.pair not in limits.allowed_pairs:
        err(f"{req.pair} is not in trading.limits.allowed_pairs")
    if req.leverage > limits.max_leverage:
        err(f"leverage {req.leverage}x is above your limit of {limits.max_leverage}x")
    trade_risk = max(req.risk_inr, plan.risk_inr)
    if trade_risk > limits.max_risk_inr:
        err(f"risk Rs {trade_risk:,.0f} is above your limit of Rs {limits.max_risk_inr:,.0f}")
    if plan.margin_inr > limits.max_margin_inr:
        err(f"margin Rs {plan.margin_inr:,.0f} is above your limit of "
            f"Rs {limits.max_margin_inr:,.0f}")
    if has_position:
        err(f"you already hold {req.pair}; close or manage it first")
    if open_positions >= limits.max_open_positions:
        err(f"{open_positions} positions are open; your limit is {limits.max_open_positions}")
    if loss_today_inr >= limits.max_daily_loss_inr:
        err(f"today's loss Rs {loss_today_inr:,.0f} has reached your daily limit of "
            f"Rs {limits.max_daily_loss_inr:,.0f}; no new trades until tomorrow (UTC)")
    if plan.rr is not None and plan.rr < 1:
        warn(f"the target pays less than the risk ({plan.rr:.2f}R)")
    return plan


def check_stop_move(side: str, *, stop_loss: float | None, take_profit: float | None,
                    mark: float) -> list[str]:
    """Errors for a new SL / TP on an open position at the current mark price."""
    errors = []
    long = side == LONG
    if stop_loss is not None and (long and stop_loss >= mark or not long and stop_loss <= mark):
        errors.append(f"stop loss {stop_loss:g} is on the wrong side of the price {mark:g}; "
                      "it would fire at once")
    if take_profit is not None and (long and take_profit <= mark
                                    or not long and take_profit >= mark):
        errors.append(f"target {take_profit:g} is on the wrong side of the price {mark:g}")
    return errors
