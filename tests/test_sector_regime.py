from backend.config import load_config
from backend.screener import regime, sectors
from .util import matrix_df


def _df():
    rows = []
    # L1/Smart-Contract coins strong, Memes weak vs USDT on 1d
    for coin, direction, strength in [("SOL", "bull", 1.5), ("ETH", "bull", 1.2),
                                      ("DOGE", "bear", -1.4)]:
        rows.append({"coin": coin, "base": "USDT", "timeframe": "1d",
                     "direction": direction, "strength": strength})
    rows.append({"coin": "BTC", "base": "USDT", "timeframe": "1d",
                 "direction": "bull", "strength": 1.0})
    return matrix_df(rows)


def test_sector_strength_aggregates():
    cfg = load_config()
    agg = sectors.sector_strength(_df(), cfg, base="USDT")
    l1 = agg[agg["sector"] == "L1"]
    assert not l1.empty
    # L1 aggregate strength should be positive (SOL+ETH bullish)
    assert l1["mean_strength"].iloc[0] > 0


def test_add_sector_rank_columns():
    cfg = load_config()
    out = sectors.add_sector_rank(_df(), cfg)
    assert "sector" in out.columns and "sector_rank" in out.columns
    sol = out[out["coin"] == "SOL"].iloc[0]
    assert sol["sector"] == "L1"


def test_regime_btc_season_when_breadth_low():
    # BTC bull but only 1 of 3 alts bull -> breadth < 50 -> btc_season
    df = _df()
    reg = regime.assess(df, quote="USDT", anchor_tf="1d")
    assert reg.btc_trend.get("1d") == "bull"
    # SOL, ETH bull, DOGE bear -> breadth ~66% -> risk_on
    assert reg.label in (regime.RISK_ON, regime.BTC_SEASON)


def test_breadth_computation():
    df = _df()
    # SOL, ETH, DOGE, BTC vs USDT on 1d: 3 bull / 4 -> 75%
    assert abs(regime.breadth(df, "USDT", "1d") - 75.0) < 1e-6
