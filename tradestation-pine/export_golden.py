"""Export bars and the Python LuxAlgo rebuilds' values for a Pine comparison."""
import sys
from pathlib import Path

RESEARCH = Path(r"C:\temp\AI\StockCryptoScreener\freqtrade-lab\research")
sys.path.insert(0, str(RESEARCH))

import numpy as np  # noqa: E402
import smc  # noqa: E402
import supertrend_ai  # noqa: E402
import sr_breaks  # noqa: E402
import liquidity_swings  # noqa: E402

out = Path(sys.argv[1])
coin, tf, n = sys.argv[2], sys.argv[3], int(sys.argv[4])
df = smc.bars(coin, tf, "1h").tail(n).copy()
st = supertrend_ai.indicator(df)
sr = sr_breaks.indicator(df)
ls = liquidity_swings.zones(df)
g = df[["open", "high", "low", "close", "volume"]].copy()
g.insert(0, "time", (df.index.astype("int64") // 1_000_000).astype(np.int64))
g["st_ts"], g["st_os"], g["st_factor"], g["st_score"] = st["ts"], st["os"], st["factor"], st["score"]
for c in ("res", "sup", "osc", "x_up", "x_dn", "b_up", "b_dn"):
    g[f"sr_{c}"] = sr[c].astype(float)
for c in ("lo_any", "hi_any", "lo_last", "hi_last", "lz_btm", "lz_top", "hz_btm", "hz_top"):
    g[f"ls_{c}"] = ls[c].astype(float)
g.to_csv(out, index=False)
print(f"{len(g)} bars of {coin} {tf} -> {out}")
