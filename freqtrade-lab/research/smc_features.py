"""What separates winning SMC trades from losing ones, for one config.

    python research/smc_features.py "<cfg tag>"     # tag from a round's jsonl

Buckets every trade by a feature known AT THE SIGNAL (never after it) and
prints avg R per bucket on FIT and HOLDOUT. A feature becomes a filter only if
the same buckets win on both halves. This is the self-improving step: the
round grid finds a family, this finds what to cut from it.
"""
from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smc  # noqa: E402


def cfg_from_tag(tag: str) -> smc.Cfg:
    kinds = {f.name: f.type for f in fields(smc.Cfg)}
    kw = {}
    for part in tag.split("|"):
        k, v = part.split("=", 1)
        t = kinds[k]
        if t in ("bool", bool):
            kw[k] = v == "True"
        elif t in ("int", int):
            kw[k] = int(v)
        elif t in ("float", float):
            kw[k] = float(v)
        else:
            kw[k] = v
    return smc.Cfg(**kw)


def enrich(coin: str, cfg: smc.Cfg, tr: pd.DataFrame, base: str = "15m") -> pd.DataFrame:
    """Signal-time features. Everything is read at the SIGNAL bar or earlier."""
    if len(tr) == 0:
        return tr
    L = smc.bars(coin, cfg.ltf, base)
    D = smc.bars(coin, "1d", base)
    S = smc.structure(coin, cfg.ltf, cfg.k_ltf, base)
    pos = L.index.get_indexer(tr["sig"])
    c = L["close"].to_numpy()
    v = L["volume"].to_numpy()
    vol_ma = pd.Series(v).rolling(96, min_periods=20).mean().to_numpy()
    # daily trend from CLOSED daily bars: close vs its 50-day mean
    dclose = D["close"]
    d_ma = dclose.rolling(50).mean()
    d_ok = (dclose > d_ma).astype(float).where(d_ma.notna())
    d_ok.index = d_ok.index + pd.Timedelta("1D")       # known at the close
    d_on = d_ok.reindex(tr["sig"] + smc.TF_DELTA[cfg.ltf], method="ffill").to_numpy()
    # BTC context the same way
    B = smc.bars("BTC", "1d", base)
    b_ma = B["close"].rolling(50).mean()
    b_ok = (B["close"] > b_ma).astype(float).where(b_ma.notna())
    b_ok.index = b_ok.index + pd.Timedelta("1D")
    b_on = b_ok.reindex(tr["sig"] + smc.TF_DELTA[cfg.ltf], method="ffill").to_numpy()
    out = tr.copy()
    out["hour"] = tr["sig"].dt.hour
    out["dow"] = tr["sig"].dt.dayofweek
    out["vol_x"] = v[pos] / vol_ma[pos]
    out["leg_atr"] = np.abs(S["ext"][pos] - S["org"][pos]) / S["atr"][pos]
    out["swept"] = S["swept"][pos]
    out["coin_up"] = d_on
    out["btc_up"] = b_on
    out["with_coin"] = np.where(np.isnan(d_on), np.nan,
                                (d_on == 1) == (tr["dir"].to_numpy() > 0))
    out["with_btc"] = np.where(np.isnan(b_on), np.nan,
                               (b_on == 1) == (tr["dir"].to_numpy() > 0))
    out["year"] = tr["sig"].dt.year
    return out


def table(df: pd.DataFrame, col: str, bins=None) -> pd.DataFrame:
    x = df[col]
    if bins is not None:
        x = pd.qcut(x, bins, duplicates="drop")
    g = df.groupby([x, "half"], observed=True)["r"].agg(["size", "mean"])
    return g.unstack("half").round(3)


def main(tag: str, base: str = "15m") -> pd.DataFrame:
    cfg = cfg_from_tag(tag)
    coins = [c for c in smc.UNIVERSE if smc.have(c, base)]
    fit, hold = smc.split(coins)
    parts = []
    for coin in coins:
        tr = smc.run(coin, cfg, base)
        if len(tr):
            e = enrich(coin, cfg, tr, base)
            e["half"] = "fit" if coin in fit else "hold"
            parts.append(e)
        for f in (smc.bars, smc.structure, smc.htf_on_ltf):
            f.cache_clear()
    df = pd.concat(parts, ignore_index=True)
    pd.set_option("display.width", 200)
    print(cfg.tag)
    for col, bins in [("dir", None), ("kind", None), ("swept", None),
                      ("with_coin", None), ("with_btc", None), ("year", None),
                      ("hour", 6), ("dow", None), ("vol_x", 5),
                      ("leg_atr", 5), ("risk_pct", 5)]:
        print(f"\n--- {col}")
        print(table(df, col, bins).to_string())
    return df


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "15m")
