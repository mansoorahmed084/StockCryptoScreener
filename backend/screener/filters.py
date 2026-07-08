"""Multi-condition filter / query engine (plan sec 4.6).

A :class:`Condition` is one testable statement about a (coin, base, timeframe)
cell. A :class:`Filter` combines conditions (and nested groups) with AND / OR.
Evaluation runs as a predicate over the long-form RS matrix and returns the set
of coins that satisfy the whole expression — which powers both "check this coin"
and "scan the market" (subject = ``*``) use cases.

Filters serialise to/from plain dicts (JSON) so they persist unchanged across the
Streamlit MVP and any later API/frontend.
"""
from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from . import rs

ANY = "*"

# metric name -> matrix column
_METRIC_COLUMN = {
    "direction": "direction",
    "strength": "strength",
    "change_pct": "change_pct",
    "rs_rank": "rank",
    "quote_volume_24h": "quote_volume_24h",
    "sector_rank": "sector_rank",
}

_OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "is": operator.eq,
}

# metrics that are only meaningful on a classified (known) cell
_DIRECTIONAL_METRICS = {"direction", "strength", "change_pct", "rs_rank"}


@dataclass
class Condition:
    subject: str        # coin symbol or "*"
    base: str
    timeframe: str
    metric: str
    operator: str
    value: Any

    @classmethod
    def from_dict(cls, d: dict) -> "Condition":
        return cls(
            subject=str(d.get("subject", ANY)).upper(),
            base=str(d["base"]).upper(),
            timeframe=str(d["timeframe"]),
            metric=str(d["metric"]),
            operator=str(d["operator"]),
            value=d["value"],
        )

    def to_dict(self) -> dict:
        return {
            "subject": self.subject, "base": self.base, "timeframe": self.timeframe,
            "metric": self.metric, "operator": self.operator, "value": self.value,
        }

    def matching_coins(self, df: pd.DataFrame) -> set[str]:
        if self.metric not in _METRIC_COLUMN:
            raise ValueError(f"Unsupported metric: {self.metric!r}")
        if self.operator not in _OPS:
            raise ValueError(f"Unsupported operator: {self.operator!r}")
        col = _METRIC_COLUMN[self.metric]
        sub = df[(df["base"] == self.base) & (df["timeframe"] == self.timeframe)]
        if self.metric in _DIRECTIONAL_METRICS:
            sub = sub[sub["direction"] != rs.UNKNOWN]
        if col not in sub.columns or sub.empty:
            return set()
        series = sub[col]
        try:
            mask = _OPS[self.operator](series, self.value)
        except TypeError:
            return set()
        coins = set(sub.loc[mask.fillna(False), "coin"])
        if self.subject != ANY:
            return {self.subject} if self.subject in coins else set()
        return coins


@dataclass
class Filter:
    logic: str = "AND"                       # AND | OR
    conditions: list[Condition] = field(default_factory=list)
    groups: list["Filter"] = field(default_factory=list)
    name: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Filter":
        return cls(
            logic=str(d.get("logic", "AND")).upper(),
            conditions=[Condition.from_dict(c) for c in d.get("conditions", [])],
            groups=[Filter.from_dict(g) for g in d.get("groups", [])],
            name=d.get("name", ""),
        )

    def to_dict(self) -> dict:
        return {
            "logic": self.logic, "name": self.name,
            "conditions": [c.to_dict() for c in self.conditions],
            "groups": [g.to_dict() for g in self.groups],
        }

    def condition_cells(self) -> set[tuple[str, str]]:
        """(base, timeframe) pairs this filter's conditions actually test."""
        cells = {(c.base, c.timeframe) for c in self.conditions}
        for g in self.groups:
            cells |= g.condition_cells()
        return cells

    def evaluate(self, df: pd.DataFrame, all_coins: set[str] | None = None) -> set[str]:
        all_coins = all_coins if all_coins is not None else set(df["coin"].unique())
        sets: list[set[str]] = [c.matching_coins(df) for c in self.conditions]
        sets += [g.evaluate(df, all_coins) for g in self.groups]
        if not sets:
            return set(all_coins)
        if self.logic == "AND":
            out = set(all_coins)
            for s in sets:
                out &= s
            return out
        if self.logic == "OR":
            out: set[str] = set()
            for s in sets:
                out |= s
            return out
        raise ValueError(f"Unknown logic: {self.logic!r}")


def apply_filter(df: pd.DataFrame, flt: Filter) -> pd.DataFrame:
    """Return the matrix rows belonging to coins that satisfy ``flt``."""
    coins = flt.evaluate(df)
    return df[df["coin"].isin(coins)].copy()


# -- presets (just saved filters) --------------------------------------------
def full_stack_bull(base: str = "BTC",
                    timeframes=("1h", "4h", "1d", "1w")) -> Filter:
    """Bullish vs ``base`` on every listed timeframe (alignment)."""
    return Filter(
        logic="AND", name=f"Full-stack bull vs {base}",
        conditions=[Condition(ANY, base, tf, "direction", "is", rs.BULL)
                    for tf in timeframes],
    )


def higher_tf_pullback(base: str = "BTC") -> Filter:
    """Uptrend on 1w+1d but a dip on 1h — buy-the-dip in an uptrend."""
    return Filter(
        logic="AND", name=f"HTF uptrend + LTF pullback vs {base}",
        conditions=[
            Condition(ANY, base, "1w", "direction", "is", rs.BULL),
            Condition(ANY, base, "1d", "direction", "is", rs.BULL),
            Condition(ANY, base, "1h", "direction", "is", rs.BEAR),
        ],
    )


def multi_base_strength(bases=("BTC", "ETH", "USDT"), timeframe="1d") -> Filter:
    """Outperforming several bases at once on one timeframe."""
    if isinstance(bases, str):  # a lone base string must not be iterated char-wise
        bases = (bases,)
    return Filter(
        logic="AND", name="Multi-base strength",
        conditions=[Condition(ANY, b, timeframe, "direction", "is", rs.BULL)
                    for b in bases],
    )


def fresh_momentum(base: str = "USDT", timeframe: str = "4h",
                   min_rank: float = 90.0) -> Filter:
    """Top-decile relative strength on a fast timeframe."""
    return Filter(
        logic="AND", name="Fresh momentum",
        conditions=[Condition(ANY, base, timeframe, "rs_rank", ">=", min_rank)],
    )


PRESETS = {
    "full_stack_bull": full_stack_bull,
    "higher_tf_pullback": higher_tf_pullback,
    "multi_base_strength": multi_base_strength,
    "fresh_momentum": fresh_momentum,
}
