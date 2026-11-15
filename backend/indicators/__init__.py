"""Indicator engine: pluggable indicators (EMA/RSI/MFI/WaveTrend/VuManChu,
the Technical Sentiment Composite and the Wave & Flow Matrix)."""
from .base import Indicator, IndicatorResult, Marker

__all__ = ["Indicator", "IndicatorResult", "Marker"]
