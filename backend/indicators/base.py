"""Indicator interface and result containers."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Marker:
    ts: pd.Timestamp
    kind: str          # e.g. 'buy', 'sell', 'bull_div', 'bear_div'
    price: float
    label: str = ""


@dataclass
class IndicatorResult:
    overlays: dict[str, pd.Series] = field(default_factory=dict)   # on price pane
    panes: dict[str, pd.Series] = field(default_factory=dict)      # lower pane series
    markers: list[Marker] = field(default_factory=list)
    signals: dict[str, bool] = field(default_factory=dict)         # latest flags


class Indicator(abc.ABC):
    """Compute an indicator over a canonical OHLCV frame."""

    name: str = "indicator"

    @abc.abstractmethod
    def compute(self, df: pd.DataFrame) -> IndicatorResult:
        ...
