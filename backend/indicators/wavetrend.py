"""WaveTrend oscillator (LazyBear / VuManChu variant)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import common


def wavetrend(df: pd.DataFrame, channel_len: int = 9, average_len: int = 12,
              ma_len: int = 3) -> tuple[pd.Series, pd.Series]:
    """Return (wt1, wt2).

    ap  = hlc3
    esa = ema(ap, channel_len)
    d   = ema(|ap-esa|, channel_len)
    ci  = (ap-esa) / (0.015*d)
    wt1 = ema(ci, average_len)
    wt2 = sma(wt1, ma_len)
    """
    ap = common.hlc3(df)
    esa = common.ema(ap, channel_len)
    d = common.ema((ap - esa).abs(), channel_len)
    ci = (ap - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = common.ema(ci, average_len)
    wt2 = common.sma(wt1, ma_len)
    return wt1, wt2
