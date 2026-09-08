# Handover — crypto strategy research, as of 2026-09-09

Read this first in a fresh session. It is the state of play, what is proven,
what is dead, and what to do next.

**Goal as stated by the trader:** consistent automated money from crypto, not
"meagre returns". Explicitly willing to take higher risk and then work the
drawdown down. Earlier briefs asked for ~60% accuracy at 1:3 R:R and 15m/1h
short-term trading; both were tested and are addressed below.

---

## 1. The one number that governs everything

Position sizing multiplies return **and** drawdown equally, so it cancels:

```
CAGR  ≈ annual_R × risk%          maxDD ≈ maxDD_R × risk%
```

What you actually own is the **ratio annual_R / maxDD_R**. Risk% only picks a
point on that line — you cannot size your way out of a bad ratio.

| book | annual_R | maxDD_R | **ratio** | CAGR at 30% DD | at 50% DD |
|---|---|---|---|---|---|
| daily long + structure break (best) | 3.74 | 6.7 | **0.56** | 17% | 28% |
| VmcCapitulation (repo's original) | 3.9 | 9.96 | 0.39 | 12% | 20% |
| long + short combined | 4.3 | 20.8 | 0.21 | 6% | 10% |
| daily long, no trigger | 5.1 | 29.2 | 0.17 | 5% | 9% |

**To beat ~17% CAGR at a tolerable drawdown, the ratio must rise.** Only two
things move it, and neither is a parameter tweak:

1. **More independent trades** — annual_R rises faster than maxDD_R when the
   trades are genuinely uncorrelated.
2. **Stacking uncorrelated books** that each have positive expectancy.

`annual_R = trades_per_year × avg_r`. Every phase before 7 optimised `avg_r`,
which measures whether an edge exists but not how much money it makes.

---

## 2. What is PROVEN (survived held-out coins + two engines)

**DailyDivBreakout** — documented in
[STRATEGY_DailyDivBreakout.md](STRATEGY_DailyDivBreakout.md).

Daily candles, 76 Binance USDT pairs, long only. VMC bullish divergence with
WT2 ≤ −30 at the pivot (confirmed 3 closes later), then within 8 days a close
above a falling line fitted through the highs since the pivot. Void if price
loses the pivot low. Stop = setup low − 1×ATR(14), skip if > 15% away. Target
3R, 60-day time stop.

| | value |
|---|---|
| CAGR at 1% risk | 7.4% (portfolio sim) to 10.5% (freqtrade) |
| profit factor | 1.59–1.73 |
| win rate | 37% at 3R |
| max drawdown | 17.2–18.6% |
| trades/year | ~20 |

Evidence: held-out coins **beat** fit (+32.94% vs +25.21%); two independent
engines agree within 2 points; positive at all 6 oversold/trigger settings
(a plateau, not a ridge).

### Ingredients that are individually supported
| ingredient | effect | where |
|---|---|---|
| structure break entry | ~3× expectancy, drawdown 30R → 6.7R | phase 6–7 |
| money-flow green filter | +0.10R on both baskets (1h) | phase 6 |
| daily regime gate | +0.20R vs −0.17R ungated (1h) | phase 2 |
| deep oversold at the pivot | ~3× the drift of shallow | phase 1 |
| volatile mid-caps over majors | ~2× bar range, halves cost drag | phase 6 |
| longer timeframe | cost/R 18% on 15m → ~3% on daily | phase 4 |

---

## 3. What is DEAD (do not re-test without a new reason)

| idea | result |
|---|---|
| 60% accuracy at a **fixed** 3R | does not exist; best strict rate found is 41% |
| 1%/day target | 1.01^365 = 37×/yr; 7× the best fund ever recorded |
| 15m anything | fee eats 18% of every R; **even at 0.02% maker fees, 1h is −2.18 annual R** |
| shorts (mirror of any entry) | −0.19 to −0.24R held out, PF 0.66–0.72 |
| market breadth as a filter | no bucket positive out of sample; flips sign between baskets |
| shallow-breach re-entry | −0.196R, no better than deep breaches |
| exit re-engineering | 3R already optimal; all shorter targets and 4 scale-out shapes worse |
| ETH-only optimisation (~5,300 configs) | every result lost money on other coins |
| blow-off fade on one coin | −0.42R; needed the basket |
| ATR volatility floor | harmful at every threshold |
| 1h WT cross-up continuation | −0.12R over 1198 trades |
| lower fees as the fix | tested; changes almost nothing on daily, insufficient on 1h |

**Long + short combined:** shorts have negative expectancy but win in exactly
the years longs lose (2021, 2022, 2025). Combining gives **0 losing years out of
7** and cuts best-year concentration from 69% to 40%, at the cost of 0.34 CAGR
points and 3.5 drawdown points. The ratio gets *worse* (0.56 → 0.21). Keep as a
smoothing option, not a return driver.

---

## 4. Methodology that must not be dropped

These were learned the hard way; each caught a result that looked real.

1. **Held-out COINS, not just dates.** Phase 3: ~5,300 configs tuned on ETH all
   lost money on the other 28 coins while passing every date-split test.
   Out-of-sample in time is not out-of-sample in instrument. The universe is
   split by hashing the coin name so membership carries no market information.
2. **Neighbour agreement.** A real effect is a plateau; a ridge with negative
   neighbours is noise. This killed the phase-6 "+0.093R" result.
3. **Trace which bars the entry decision used.** Phase 5 produced a +0.709R,
   PF 2.59, 16/16-coins result that was pure lookahead — a bucket classified by
   bars *after* its own entry. `lookahead-analysis` missed it, the held-out
   protocol would have passed it, and per-coin agreement made it look *more*
   trustworthy. Only reading the code caught it.
4. **Sanity-check arithmetic.** A 3R-capped strategy winning 29% cannot average
   +2.02R. That impossibility exposed the detail-coverage bug below.
5. **Cross-check in freqtrade** before believing the harness.

### Harness bugs found and fixed (all in `harness.py`)
- **Detail coverage.** `searchsorted` returns 0 for a timestamp before the detail
  frame starts, pricing a 2021 entry against 2024 candles. `simulate()` now
  refuses signals outside detail coverage.
- **Frame identity.** `load()` is cached and returned by reference; indicator
  caches key on `id(df)`, so re-reading defeated them. Do not mutate results.
- **freqtrade gotcha:** `use_exit_signal = False` silently disables
  `custom_exit()`. Keep it `True` and emit nothing from `populate_exit_trend`.

---

## 5. UNFINISHED — the grid, and how to run it

A 12,960-config grid was launched and **did not finish**. Workers only write
output at the end, so there are no partial results. Re-run it:

```bash
cd freqtrade-lab
# 6 workers, ~13 minutes total
for w in 0 1 2 3 4 5; do
  ./.venv/Scripts/python.exe research/optimize.py 1d $w 6 > research/results/opt1d_$w.log 2>&1 &
done; wait

# then
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe research/opt_report.py 1d 15
```

Grid dimensions in [optimize.py](optimize.py): side × wt2_max(5) × trigger(3) ×
wait_bars(3) × atr_mult(3) × mfi_min(2) × gate(3) × target(4) × require_hold(2).
Ranked by **HOLDOUT annual_R**, with marginals and neighbour scores in
[opt_report.py](opt_report.py).

**What to look for:** a config with annual_R well above 3.74 whose maxDD_R does
not rise proportionally — i.e. a better ratio. Ignore any winner whose
neighbours are negative.

---

## 6. Next steps, ranked by expected value

1. **Finish the grid** (above). It is the only systematic search of the frequency
   dimension, which is the safe lever on the ratio.
2. **Expand the universe to 150+ coins.** More independent trades is the
   highest-confidence way to raise annual_R without raising maxDD_R. Current
   universe is 76 (listed in [campaign.py](campaign.py)). This is a download
   plus a re-run — no new research.
3. **Find a second uncorrelated positive-expectancy book.** The long+short work
   proved uncorrelated books flatten the equity curve; the problem was that the
   short book loses money. A second *positive* book would raise the ratio rather
   than lower it. Untried mechanisms: funding-rate carry, cross-sectional
   relative strength (the repo's own core feature, which this work never used),
   BTC-dominance rotation.
4. **Walk-forward the oversold dial** instead of fixing it at −30.
5. **Paper trade DailyDivBreakout** in parallel with all of the above. 2023
   produced 69% of its profit and no amount of backtesting can settle whether
   that was luck — only forward evidence can.

### Explicitly do NOT
- Re-optimise on a single coin.
- Chase 15m or 1h without a genuinely new mechanism; costs are measured and fatal.
- Report any result before checking neighbours and tracing entry-vs-information ordering.

---

## 7. File map

| file | purpose |
|---|---|
[harness.py](harness.py) | R-multiple backtest engine, conservative fills, stop-first |
[breakout.py](breakout.py) | `divergence_breakout` — the working entry, long and short |
[strategies.py](strategies.py) | VMC divergence, WT cross, Bollinger, regime gates |
[hf_strategies.py](hf_strategies.py) | six high-frequency families (all negative) |
[user_setup.py](user_setup.py) | the trader's stoch/RSI reset setup |
[confluence.py](confluence.py) | reset filters on a pullback trigger |
[pattern.py](pattern.py) | impulse → pullback → divergent double bottom |
[breadth.py](breadth.py) | universe-wide oversold breadth (rejected as a filter) |
[portfolio.py](portfolio.py) | chronological, slot-capped, compounding account sim |
[campaign.py](campaign.py) | 76-coin universe, hash split, stack/breadth/exit modes |
[optimize.py](optimize.py) | the 12,960-config grid |
[opt_report.py](opt_report.py) | grid ranking with all four overfit guards |
[scan_divergence.py](scan_divergence.py) | live multi-timeframe divergence scan |
[breach_test.py](breach_test.py) | shallow vs deep breach test |
[ETH_RESEARCH_LOG.md](ETH_RESEARCH_LOG.md) | full derivation, 50 numbered findings |
[STRATEGY_DailyDivBreakout.md](STRATEGY_DailyDivBreakout.md) | the strategy spec |

Freqtrade strategies live in `../user_data/strategies/`. `DailyDivBreakout.py`
is the one that matters.

**Configs are gitignored** (they hold the API-server password and would hold
exchange keys). Rebuild from `config.example.json`; whitelists are in
[campaign.py](campaign.py). `config-big.json` = the 76-coin universe.

**Data on disk:** 76 coins at 1d (from 2018) and 1h (from 2020); ~60 coins at
15m; ~45 at 5m. Everything Binance spot.
