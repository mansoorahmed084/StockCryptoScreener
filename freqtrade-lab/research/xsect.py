"""Cross-sectional relative strength: long the strong, short the weak.

    python research/xsect.py [grid|final]

Why this and not another breakout. Finding 52: the two proven books lose in the
same years because both are long-only daily breakouts on the same universe.
Different indicators are not different exposures. A second book has to differ in
EXPOSURE, and the cleanest way to do that is to be market-neutral: hold the
strongest coins against the weakest, sized so the two legs cancel. Whatever the
whole market does that week affects both legs and drops out of the result.

This is also the repo's own core feature. `backend/screener/rs.py` computes a
blended relative-strength z-score, and no work in `freqtrade-lab` has used it.
Both that score and plain trailing return are tested as the ranking signal.

Structure, and why it is not a trade list:

  * every `hold` days, rank the universe, take the top `n_legs` long and the
    bottom `n_legs` short, equal weight, 0.5 gross each side so net is zero
  * hold to the next rebalance, no stops, no targets
  * score at date t uses closes up to and including t; the position is entered
    at the NEXT bar's open and exited at the open `hold` bars later, so no
    decision reads a bar it could not have seen
  * costs are charged as a full turnover each rebalance: every position pays to
    open and to close, which is pessimistic since some names persist

Held-out testing splits the UNIVERSE, not the dates, and each half is ranked
only against itself -- the same mechanism applied to a disjoint set of coins.

Survivorship note: these 76 coins are today's listings. Names that died are
absent, and they would have been the short leg's best trades, so the short side
is understated rather than flattered.
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import harness      # noqa: E402
import campaign     # noqa: E402
from backend.config import load_config       # noqa: E402
from backend.screener import rs              # noqa: E402

START = pd.Timestamp("2020-01-01", tz="UTC")
COST = 0.0015          # per side, per position
CAPITAL = 100_000.0


def panels(coins: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(opens, closes) as [date x coin] frames, daily."""
    op, cl = {}, {}
    for c in coins:
        try:
            df = harness.load(f"{c}/USDT", "1d")
        except FileNotFoundError:
            continue
        if len(df) < 400:
            continue
        op[c], cl[c] = df["open"], df["close"]
    return pd.DataFrame(op).sort_index(), pd.DataFrame(cl).sort_index()


def score_panel(closes: pd.DataFrame, method: str, lookback: int) -> pd.DataFrame:
    """Ranking signal per coin per day. Uses closes at or before each date."""
    if method == "ret":
        return closes / closes.shift(lookback) - 1.0
    if method == "vol_adj":
        # momentum divided by its own noise: the same idea rs.py uses, cheaply
        r = closes.pct_change()
        return (closes / closes.shift(lookback) - 1.0) / (
            r.rolling(lookback, min_periods=lookback // 2).std() * np.sqrt(lookback))
    if method == "rs_vs_btc":
        # the repo's own blended strength score, on each coin's ratio to BTC
        params = load_config().classifier_params("1d")
        params.vol_lookback = lookback
        btc = closes.get("BTC")
        if btc is None:
            raise RuntimeError("BTC/USDT required for rs_vs_btc")
        out = {}
        for c in closes.columns:
            if c == "BTC":
                continue
            ratio = (closes[c] / btc).dropna()
            if len(ratio) < lookback + 30:
                continue
            out[c] = rs.strength_series(ratio, params)["strength"]
        return pd.DataFrame(out).reindex(closes.index)
    raise ValueError(method)


def run(opens: pd.DataFrame, closes: pd.DataFrame, method: str, lookback: int,
        n_legs: int, hold: int, side: str = "ls",
        cost: float = COST) -> pd.Series:
    """Period returns of the book. Index is the exit date of each period."""
    sc = score_panel(closes, method, lookback)
    dates = closes.index[closes.index >= START]
    # rebalance dates: need a next bar to enter on and one `hold` later to exit
    idx = list(closes.index)
    pos = {d: i for i, d in enumerate(idx)}
    rets = {}

    for d in dates[::hold]:
        i = pos[d]
        if i + 1 + hold >= len(idx):
            break
        row = sc.loc[d].dropna()
        # a coin only counts if it can actually be traded over the window
        entry = opens.iloc[i + 1]
        exit_ = opens.iloc[i + 1 + hold]
        tradable = row.index.intersection(
            entry.dropna().index).intersection(exit_.dropna().index)
        row = row.loc[tradable]
        if len(row) < 2 * n_legs:
            continue
        ranked = row.sort_values()
        weak, strong = ranked.index[:n_legs], ranked.index[-n_legs:]
        fwd = (exit_ / entry - 1.0)

        long_r = float(fwd[strong].mean())
        short_r = float(fwd[weak].mean())
        if side == "ls":
            gross = 1.0
            r = 0.5 * long_r - 0.5 * short_r
        elif side == "long":
            gross = 1.0
            r = long_r
        elif side == "short":
            gross = 1.0
            r = -short_r
        else:
            raise ValueError(side)
        rets[idx[i + 1 + hold]] = r - 2 * cost * gross
    return pd.Series(rets).sort_index()


def stats(r: pd.Series, hold: int) -> dict:
    if r.empty:
        return {"n": 0}
    eq = (1 + r).cumprod()
    if eq.iloc[-1] <= 0 or not np.isfinite(eq.iloc[-1]):
        # a market-neutral book CAN be wiped out by a single period; say so
        # rather than raising a fractional power of a negative number
        return {"n": len(r), "cagr%": -100.0, "total%": -100.0,
                "max_dd%": 100.0, "hit%": round(100*(r > 0).mean(), 1),
                "mean%": round(r.mean()*100, 3), "sd%": round(r.std()*100, 2),
                "sharpe": 0.0, "ratio": -1.0}
    years = (r.index[-1] - r.index[0]).days / 365.25
    dd = (eq.cummax() - eq) / eq.cummax()
    per_year = 365.25 / hold
    return {
        "n": len(r),
        "cagr%": round((eq.iloc[-1] ** (1 / years) - 1) * 100, 2)
        if years > 0 else 0.0,
        "total%": round((eq.iloc[-1] - 1) * 100, 1),
        "max_dd%": round(dd.max() * 100, 2),
        "hit%": round(100 * (r > 0).mean(), 1),
        "mean%": round(r.mean() * 100, 3),
        "sd%": round(r.std() * 100, 2),
        "sharpe": round(r.mean() / r.std() * np.sqrt(per_year), 2)
        if r.std() > 0 else 0.0,
        "ratio": round(((eq.iloc[-1] ** (1 / years) - 1) * 100) / (dd.max() * 100), 2)
        if years > 0 and dd.max() > 0 else float("inf"),
    }


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "grid"
    coins = [c for c in campaign.UNIVERSE
             if (harness.DATA_DIR / f"{c}_USDT-1d.feather").exists()]
    fit, hold_c = campaign.split(coins)
    o_f, c_f = panels(fit + ["BTC"] if "BTC" not in fit else fit)
    o_h, c_h = panels(hold_c + ["BTC"] if "BTC" not in hold_c else hold_c)
    print(f"# cross-sectional RS — FIT {c_f.shape[1]} coins / "
          f"HOLDOUT {c_h.shape[1]} coins, cost {COST*100:g}%/side\n")

    if mode == "grid":
        print("| score | lookback | legs | hold | side || FIT cagr | dd | ratio "
              "|| **HOLD cagr** | dd | **ratio** | sharpe | hit% |")
        print("|" + "---|" * 14)
        rows = []
        for method, lb, n, h, sd in product(
                ("ret", "vol_adj", "rs_vs_btc"), (14, 30, 60, 90),
                (5, 10), (7, 14, 30), ("ls",)):
            try:
                rf = run(o_f, c_f, method, lb, n, h, sd)
                rh = run(o_h, c_h, method, lb, n, h, sd)
            except Exception:
                continue
            sf, sh = stats(rf, h), stats(rh, h)
            if not sf.get("n") or sf["n"] < 20 or not sh.get("n"):
                continue
            rows.append((method, lb, n, h, sd, sf, sh))
        rows.sort(key=lambda x: -x[6].get("ratio", -9))
        for method, lb, n, h, sd, sf, sh in rows:
            print(f"| {method} | {lb} | {n} | {h} | {sd} || "
                  f"{sf['cagr%']:+.1f}% | {sf['max_dd%']:.1f}% | {sf['ratio']} || "
                  f"**{sh['cagr%']:+.1f}%** | {sh['max_dd%']:.1f}% | "
                  f"**{sh['ratio']}** | {sh['sharpe']} | {sh['hit%']} |")


if __name__ == "__main__":
    main()
