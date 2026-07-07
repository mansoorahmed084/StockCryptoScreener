"""Market-regime context (plan sec 4.10).

CoinDCX does not expose BTC dominance / total market cap, so we derive a
practical proxy from data we already have:

  * BTC's own trend (BTC/USDT direction per timeframe)
  * market **breadth** — the share of the scanned universe that is bullish vs
    bearish against USDT on a timeframe

Combined into a simple risk-on / risk-off / BTC-season / alt-season label so the
RS readings are never misread ("green vs BTC" in a BTC dump just means
"falling less").
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import rs

RISK_ON = "risk_on"
RISK_OFF = "risk_off"
BTC_SEASON = "btc_season"
ALT_SEASON = "alt_season"
NEUTRAL = "neutral"


@dataclass
class Regime:
    label: str = NEUTRAL
    btc_trend: dict[str, str] = field(default_factory=dict)
    breadth: dict[str, float] = field(default_factory=dict)  # tf -> % bullish


def breadth(df: pd.DataFrame, base: str, timeframe: str) -> float:
    """Percent of classified coins that are bullish vs ``base`` on ``timeframe``."""
    sub = df[(df["base"] == base.upper()) & (df["timeframe"] == timeframe)
             & (df["direction"] != rs.UNKNOWN)]
    if sub.empty:
        return float("nan")
    bulls = (sub["direction"] == rs.BULL).sum()
    return 100.0 * bulls / len(sub)


def btc_trend(df: pd.DataFrame, quote: str = "USDT") -> dict[str, str]:
    sub = df[(df["coin"] == "BTC") & (df["base"] == quote.upper())]
    return dict(zip(sub["timeframe"], sub["direction"]))


def assess(df: pd.DataFrame, *, quote: str = "USDT",
           anchor_tf: str = "1d") -> Regime:
    trend = btc_trend(df, quote)
    bd = {tf: breadth(df, quote, tf) for tf in df["timeframe"].unique()}
    btc = trend.get(anchor_tf, rs.UNKNOWN)
    b = bd.get(anchor_tf, float("nan"))

    label = NEUTRAL
    if b == b:  # not NaN
        alts_strong = b >= 50.0
        if btc == rs.BULL:
            label = RISK_ON if alts_strong else BTC_SEASON
        elif btc == rs.BEAR:
            label = ALT_SEASON if alts_strong else RISK_OFF
        else:
            label = RISK_ON if alts_strong else NEUTRAL
    return Regime(label=label, btc_trend=trend, breadth=bd)
