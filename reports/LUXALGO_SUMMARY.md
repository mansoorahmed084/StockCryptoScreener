# LuxAlgo indicators — full summary

Research and tests run 2026-11-13. Crypto only. Fees included.

## Bottom line

- **No LuxAlgo indicator beats our SMC sweep-break.** Keep sweep-break as it is.
- **None of the 3 tested indicators needs the paid LuxAlgo plan.** They are all free and open-source.
- **Refund:** if you do not use the paid tools, ask for the refund before about **2026-12-12**. Turn off auto-renew.

## Step 1 — what people say online

- I found **no independent crypto backtest** of any LuxAlgo indicator, free or paid.
- Reddit blocks my tools. I read Reddit posts that other sites quote. They say three things:
  - The paid Signals & Overlays "repaints". This means a signal changes or goes away while the candle is still open.
  - Live results are close to 50/50.
  - The free scripts are about as good as the paid ones.
- Most review sites earn money from sign-ups, or they sell a competing product. Do not trust their win-rate numbers.
- Most-used free LuxAlgo scripts on TradingView: Smart Money Concepts (#2 of all scripts) and Support and Resistance Levels with Breaks (#11).

Details: [LUXALGO_RESEARCH_2026-11-13.md](LUXALGO_RESEARCH_2026-11-13.md)

## Step 2 — the 3 indicators we rebuilt and tested

**How we tested:**
- Each indicator was rebuilt in Python and has unit tests.
- Fees: 0.06% per side, with a stress test at 0.10%.
- Signals come from closed candles only. Entry is at the next candle's open.
- The real exam uses **203 coins** that we never used to pick any rule.
- The target to beat is **SMC sweep-break: +0.245R per trade on the 203 coins.**

### 1. SuperTrend AI (Clustering) — no edge

- 40 setups on 1h, 4h and 1d.
- 1h always lost money.
- The best daily setup made +0.16R per trade. But it lost money without its best 1% of trades.
- The daily setups made their money in 2021 only.
- LuxAlgo's signal score works backwards: a high score did worse than a low score.
- One bug was caught: a single OG trade with a 0.02% stop booked +11,095R. Fix: skip stops closer than 0.5%.

Details: [SUPERTREND_AI_RESEARCH.md](../freqtrade-lab/research/SUPERTREND_AI_RESEARCH.md)

### 2. Liquidity Swings — no edge, and no help to sweep-break

- LuxAlgo does not show the code for this one. It was rebuilt from their written description.
- **On its own** (trade the sweep reversal): all 72 setups lost money, −0.08 to −0.18R per trade.
- **Inside sweep-break** (use its zones as the swept level): every version was worse.

| Sweep level used | Avg R per trade (203 coins) | Profit a year |
|---|---|---|
| **Our current swing (no change)** | **+0.245** | **15.4%** |
| LuxAlgo default zone (length 14) | +0.11 | 2% |
| Both together | +0.23 | 14.4% |

Details: [LIQUIDITY_SWINGS_RESEARCH.md](../freqtrade-lab/research/LIQUIDITY_SWINGS_RESEARCH.md)

### 3. Support and Resistance Levels with Breaks — small edge, no help to sweep-break

- 96 setups on 1h, 4h and 1d.
- LuxAlgo's volume rule (the "B" tag) made results worse every time.
- One plain setup works a little:
  - Trade a 4h break of resistance, long or short.
  - The stop is at the support level, about 11% away.
  - Exit at 3R, or after 7 days.
- On the 203 coins it made **+0.083R per trade**, and all 7 years were positive.
- The result stayed steady when each setting was changed.
- **But it moves with sweep-break.**
  - The monthly correlation is 0.66 (1.0 means they move exactly together).
  - They lose in the same months.

Shared account on all 279 coins, 0.5% risk, 10 slots:

| | Profit a year | Worst drop | Profit per unit of drop |
|---|---|---|---|
| **Sweep-break alone** | **22.6%** | **18.4%** | **1.23** |
| S&R alone | 22.2% | 32.6% | 0.68 |
| Both together | 27.1% | 27.1% | 1.00 |

Running both makes more money, but the drops get bigger by a larger amount, so the profit per unit of drop gets worse.

Not done: a cross-check of S&R in freqtrade (a second backtest engine).

Details: [SR_BREAKS_RESEARCH.md](../freqtrade-lab/research/SR_BREAKS_RESEARCH.md)

## Step 3 — Signals & Overlays, our own build (2026-11-16)

- LuxAlgo's Signals & Overlays is paid and closed. No clean copy exists online. The copies on Scribd, Pastebin and GitHub are leaks; we did not use them.
- We built our own from LuxAlgo's public docs: the same features and settings, our own formulas. **The test below is of our build, not of LuxAlgo's signals.**
- The Pine file and the Python file give the same values on every bar.
- 210 setups on 1h, 4h and 1d, on the 76 old coins and the 203 unseen coins.

What came out on the 203 unseen coins:

- **1h: all dead.** Best +0.008R.
- **Contrarian signals: dead** on 1h and 4h. Near zero on 1d.
- **Exit crosses: they hurt.** They win more often, but they cut the winners.
- **Autopilot and the Trend Strength filter: no gain.**
- **One thing works a little:** the confirmation signal **with the trend**, closed at a fixed 3R.

| Setup (confirmation, long and short, 3R exit) | Avg R per trade | Profit a year | Worst drop |
|---|---|---|---|
| 4h with the Smart Trail filter | +0.147 | 27.6% | 36.8% |
| 4h, classifier classes 3–4 | +0.117 | 41.0% | 43.2% |
| 1d, all signals | +0.251 | 8.5% | 25.2% |
| 1d, sensitivity 8 | +0.268 | 14.1% | 16.8% |
| **SMC sweep-break (target)** | **+0.245** | **15.4%** | **17.6%** |

- The old coins and the new coins agree on these rows. That is a good sign.
- But the profit per unit of drop is the same as sweep-break or worse. The 4h setups have drops of 37–44%.
- Not done: the check that it does not lose in the same months as sweep-break.

Details: [SIGNALS_OVERLAYS_RESEARCH.md](../freqtrade-lab/research/SIGNALS_OVERLAYS_RESEARCH.md)

## Skipped, and why

| Indicator | Reason |
|---|---|
| Smart Money Concepts | Already tested. Only 4h sweep-break survived. |
| Price Action Concepts | Already rebuilt (Price Action page). |
| Nadaraya-Watson Envelope | The default mode repaints. LuxAlgo says it has no data that it beats normal bands. |
| Signals & Overlays (LuxAlgo's real one) | Closed code. It has the most repaint complaints. We tested our own build instead (step 3). |

## Files

| What | Where |
|---|---|
| SuperTrend AI code | `freqtrade-lab/research/supertrend_ai.py` |
| Liquidity Swings code | `freqtrade-lab/research/liquidity_swings.py` |
| S&R Breaks code | `freqtrade-lab/research/sr_breaks.py` |
| S&R round-2 checks | `freqtrade-lab/research/sr_check.py` |
| Signals & Overlays own build (Python) | `freqtrade-lab/research/signals_overlays.py` |
| Signals & Overlays own build (Pine) | `tradestation-pine/signals_overlays_own.pine` |
| Tests | `tests/test_supertrend_ai.py`, `tests/test_liquidity_swings.py`, `tests/test_sr_breaks.py` |
| Dead-ideas list | `freqtrade-lab/research/HANDOVER.md`, section 3 |

To run the tests:

```bash
freqtrade-lab/.venv/Scripts/python.exe -m pytest tests/test_supertrend_ai.py tests/test_liquidity_swings.py tests/test_sr_breaks.py -q -p no:cacheprovider --noconftest
```
