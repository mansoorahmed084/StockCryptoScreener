"""The trader's reset idea applied to a high-frequency trigger.

Two separate results pointed at this:

  * batch 6 — an EMA pullback on 4h fires ~83 times a year behind the daily
    gate, at 68.7% net-win, but with a 21.8R drawdown. Plenty of frequency,
    poor quality per trade.
  * the trader's own observation — a pullback is only worth taking when the
    oscillators have RESET: stochastic down in the oversold zone and turning
    up, RSI low and turning up.

So: keep the frequent trigger, and demand the reset as a quality filter. Every
filter is optional and independently switchable, so the sweep measures what each
one is actually worth instead of assuming the stack helps.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strategies import atr                            # noqa: E402
from hf_strategies import _emit                       # noqa: E402
from user_setup import stochastic, _divergence_recent  # noqa: E402
from backend.indicators import common                 # noqa: E402


def pullback_reset(df: pd.DataFrame, *, side: str = "long",
                   # --- trigger ---
                   ema_len: int = 50, trigger: str = "ema_touch",
                   # --- reset filters, each optional ---
                   stoch_max: float | None = 30.0, stoch_cross: bool = True,
                   stoch_k: int = 14, stoch_smooth: int = 3, stoch_d: int = 3,
                   rsi_max: float | None = 45.0, rsi_turning: bool = True,
                   rsi_len: int = 14,
                   # The trader describes a SEQUENCE: oscillators reset, then
                   # cross, then price turns up. Demanding all of it on one
                   # candle gives n=0 over six years. `within` is how many bars
                   # back each reset condition may have been satisfied.
                   within: int = 3,
                   require_div: bool = False, div_within: int = 6,
                   # --- risk ---
                   swing_len: int = 10, atr_mult: float = 1.0, atr_len: int = 14,
                   max_risk_pct: float = 0.10,
                   gate: pd.Series | None = None,
                   gate_allow: tuple[str, ...] = ("bull", "neutral")
                   ) -> pd.DataFrame:
    """Frequent pullback trigger, gated on the oscillators having reset."""
    direction = 1 if side == "long" else -1
    ema_f = common.ema(df["close"], ema_len)
    k, d = stochastic(df, stoch_k, stoch_smooth, stoch_d)
    r = common.rsi(df["close"], rsi_len)
    a = atr(df, atr_len)

    # --- the trigger: price dips to the EMA and closes back the right side ---
    if direction > 0:
        if trigger == "ema_touch":
            trig = (df["low"] <= ema_f) & (df["close"] > ema_f)
        else:                                    # "ema_reclaim"
            trig = (df["close"].shift(1) <= ema_f.shift(1)) & (df["close"] > ema_f)
        stop = df["low"].rolling(swing_len, min_periods=1).min() - atr_mult * a
    else:
        if trigger == "ema_touch":
            trig = (df["high"] >= ema_f) & (df["close"] < ema_f)
        else:
            trig = (df["close"].shift(1) >= ema_f.shift(1)) & (df["close"] < ema_f)
        stop = df["high"].rolling(swing_len, min_periods=1).max() + atr_mult * a

    # --- the reset filters, each satisfiable anywhere in the last `within` bars ---
    def recently(cond: pd.Series) -> pd.Series:
        return cond.fillna(False).rolling(within, min_periods=1).max().astype(bool)

    if stoch_max is not None:
        level = stoch_max if direction > 0 else 100 - stoch_max
        trig &= recently((k <= level) if direction > 0 else (k >= level))
    if stoch_cross:
        cross = ((k.shift(1) <= d.shift(1)) & (k > d)) if direction > 0 \
            else ((k.shift(1) >= d.shift(1)) & (k < d))
        trig &= recently(cross)
    if rsi_max is not None:
        trig &= recently((r <= rsi_max) if direction > 0 else (r >= 100 - rsi_max))
    if rsi_turning:
        # this one stays on the trigger bar: "and THEN it tries to go up"
        trig &= (r > r.shift(1)) if direction > 0 else (r < r.shift(1))
    if require_div:
        trig &= _divergence_recent(df, side, div_within)

    return _emit(df, trig, direction, stop, gate, gate_allow, max_risk_pct)
