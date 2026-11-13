# LuxAlgo indicators for crypto — research, 2026-11-13

## What the feedback says

- **No independent backtest exists.** I found no third-party crypto test of any LuxAlgo indicator, free or paid. Every "win rate" number online is from a vendor or an affiliate page.
- **Reddit is blocked for my tools.** I could only read Reddit posts quoted on other sites. These say the same things again and again:
  - Paid Signals & Overlays "repaints" — buy/sell flips on the live candle.
  - Live results near 50/50.
  - The free scripts are almost as good as the paid ones.
- **Review sites are mostly affiliates or competitors** (Quantzee, theindicatorlab, lunefi). Trustpilot is mixed. Many 5-star reviews come by invite. Auto-renew and refund complaints repeat.
- **LuxAlgo itself says** of Nadaraya-Watson that there is "no data supporting the performance" over classic bands.

## Most used free LuxAlgo scripts (TradingView boosts)

| Script | Boosts | Source |
|---|---|---|
| Smart Money Concepts | 78.2K (#2 on all of TradingView) | open |
| Support and Resistance Levels with Breaks | 33.8K (#11) | open |

## Shortlist to rebuild in Python

All are free and open-source. We can read the Pine code and port it. We do not need the paid plan for any of them.

| # | Indicator | Why test it | Repaint risk | Status here |
|---|---|---|---|---|
| 1 | **SuperTrend AI (Clustering)** | Adaptive SuperTrend. Runs factors 1.0–5.0, k-means groups them into best/avg/worst, uses the best group. New family for us (trend follow). | Low — uses only past bars | **Tested 2026-11-13: no edge** ([results](../freqtrade-lab/research/SUPERTREND_AI_RESEARCH.md)) |
| 2 | **Support & Resistance Levels with Breaks** | 2nd most popular LuxAlgo script. Pivot S/R + volume oscillator must confirm the break. | Low — pivots are confirmed late, which adds lag | **Tested 2026-11-13: LuxAlgo's volume "B" signal adds nothing; one plain 4h variant is a weak, steady candidate** ([results](../freqtrade-lab/research/SR_BREAKS_RESEARCH.md)) |
| 3 | **Liquidity Swings** | Marks swing-high/low liquidity zones, counts touches and volume. Can give better levels to our 4h sweep-break (the only setup that survived). | Low | **Tested 2026-11-13: no edge, no gain in sweep-break** ([results](../freqtrade-lab/research/LIQUIDITY_SWINGS_RESEARCH.md)) |
| 4 | Trendlines with Breaks | Short pivot trendlines, slope from ATR. | **High** unless "backpaint" is off | Our TrendlineBreakout is a different, long-term line |

## Skip

- **Smart Money Concepts** — already tested. Only 4h sweep-break on daily bias survived.
- **Price Action Concepts** — already rebuilt (`frontend/pages/8_Price_Action.py`).
- **Nadaraya-Watson Envelope** — default mode repaints. Non-repaint mode is just a normal band.
- **Signals & Overlays** — closed code, most repaint complaints.

## Test rules (same as always)

- Fees in. Closed-bar signals only.
- Out-of-sample = the 203 unseen coins, not dates.
- Baseline to beat: 4h sweep-break, +0.245R/trade.

## Note on the paid plan

Every indicator above is free. If none of the paid tools earn their place, ask for the refund before about **2026-12-12**.

## Sources

- https://thegodfunded.com/en/tools/luxalgo/
- https://quantzee.com/luxalgo-alternative/ (competitor)
- https://theindicatorlab.com/reviews/luxalgo/ (affiliate)
- https://lunefi.com/blog/best-luxalgo-alternatives-2026-tradingview-indicators
- https://coincodecap.com/luxalgo-review
- https://blog.pickmytrade.io/top-free-indicators-and-strategies-on-tradingview/
- https://www.luxalgo.com/library/indicator/nadaraya-watson-envelope/
- https://www.luxalgo.com/library/indicator/supertrend-ai-clustering/
- https://www.luxalgo.com/library/indicator/trendlines-with-breaks/
- https://www.tradingview.com/script/Iko0E2kL-Nadaraya-Watson-Envelope-LuxAlgo
