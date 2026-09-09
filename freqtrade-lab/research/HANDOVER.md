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

Every maxDD_R below is measured **in date order**. Until 2026-09-09 none of
them were: `metrics()` walked the trade list in the order it was handed, and a
pooled basket is built coin by coin, so the drawdown described the coin loop
rather than the passage of time. It understated the real figure by two to
three times. The fix and the evidence are in section 4.

| book (HOLDOUT coins) | annual_R | maxDD_R | **ratio** | was printed as | CAGR at 30% DD | at 50% DD |
|---|---|---|---|---|---|---|
| **long-term trendline break (best)** | 26.11 | 26.5 | **0.99** | 3.26 | — see note | — |
| **2xATR stop + 4R target** (grid, section 5) | 11.80 | 22.9 | **0.52** | 2.33 | 16% | 26% |
| daily long + structure break | 3.74 | 10.3 | 0.36 | 0.56 | 11% | 18% |
| long + short combined | 2.72 | 10.6 | 0.26 | 0.21 | 8% | 13% |
| daily long, no trigger | 4.20 | 33.7 | 0.12 | 0.17 | 4% | 6% |
| VmcCapitulation (repo's original) | 3.9 | *not re-run* | — | 0.39 | — | — |

Only the structure-break row's annual_R reproduces exactly against current
code. The combined and no-trigger rows were rebuilt from the grid's dials and
land near, not on, their old values — re-derived rather than restored.
VmcCapitulation has not been re-run at all.

**Nothing about the rankings changed.** annual_R, avg_r, PF and the win rates
do not depend on trade order, so every search in this repo selected on sound
numbers. Only maxDD_R, r_per_dd and worst_streak were wrong, and only where a
basket was pooled across coins. What changed is the size of the prize: the best
ratio on the board is 0.99, not 3.26.

*Note on the trendline row:* that pooled ratio assumes every signal could be
taken. It cannot — the signals cluster. The honest account number is **CAGR
14.5% at a 21.0% drawdown** in freqtrade (17.4% in the harness once the sizing
flaw below is fixed), against **10.7% at 18.5%** for the strategy beneath it on
the identical freqtrade run. Better, not double. See
[STRATEGY_TrendlineBreakout.md](STRATEGY_TrendlineBreakout.md).

**To beat ~17% CAGR at a tolerable drawdown, the ratio must rise.** Only two
things move it, and neither is a parameter tweak:

1. **More independent trades** — annual_R rises faster than maxDD_R when the
   trades are genuinely uncorrelated.
2. **Stacking uncorrelated books** that each have positive expectancy.

`annual_R = trades_per_year × avg_r`. Every phase before 7 optimised `avg_r`,
which measures whether an edge exists but not how much money it makes.

---

## 2. What is PROVEN (survived held-out coins + two engines)

**TrendlineBreakout** (best) — documented in
[STRATEGY_TrendlineBreakout.md](STRATEGY_TrendlineBreakout.md).

Daily candles, long only. A descending line anchored at the highest high of the
last 200 days, sloped so no later high pokes through it; the break must be 60+
days after the anchor, price must have fallen 25% beneath it, 3 highs must sit
on it, and break volume must be 1.5x its 20-day mean. Stop = 20-day low
- 1.5xATR(14). **Exit is a 3R trailing stop, not a target** — a fixed 3R
measured a holdout ratio of 0.14 against 0.78 for the trail.

| | value |
|---|---|
| CAGR, freqtrade, max 10 open | 14.54% (vs 10.71% for DailyDivBreakout, same run) |
| CAGR, harness, sizing corrected | 17.4% |
| max drawdown, closed trades | 21.0% (vs 18.5%) |
| max drawdown, mark-to-market | **76%** — unexplained, check this first |
| profit factor | 1.82 (vs 1.75) |
| win rate | 37.7% |
| filled trades/year | ~24 |

Evidence: **468 of 468 grid cells positive on held-out coins**, median holdout
ratio 1.86; 100% neighbour agreement on every top cell; 147/147 signals survive
having the future physically deleted; holdout coins beat fit coins.
Weaknesses are real and listed in the strategy doc — the signals are heavily
correlated, 2 of 7 years lost money, and 2021 was flat because a bull market
has no long descending lines to break.

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
| exit re-engineering (divergence family) | 3R already optimal; all shorter targets and 4 scale-out shapes worse |
| a fixed target on the TRENDLINE family | opposite result: 3R gives ratio 0.14 vs 0.78 trailing. Do not carry the divergence family's exit across |
| ETH-only optimisation (~5,300 configs) | every result lost money on other coins |
| blow-off fade on one coin | −0.42R; needed the basket |
| ATR volatility floor | harmful at every threshold |
| 1h WT cross-up continuation | −0.12R over 1198 trades |
| lower fees as the fix | tested; changes almost nothing on daily, insufficient on 1h |
| stacking the two proven books | correlation +0.300, same losing years; ratio helped in 1 of 9 combinations and reversed on the slot limit |

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
4. **`portfolio.py` compounds too early.** It walks trades in ENTRY order and
   credits each trade's profit immediately, so a long hold funds positions
   opened before it closed. Worth ~4.6 CAGR points on a 74-day-hold strategy,
   less on short holds, but every number it produced is optimistic.
   `tl_account.py` has the corrected event-queue version.
5. **Sanity-check arithmetic.** A 3R-capped strategy winning 29% cannot average
   +2.02R. That impossibility exposed the detail-coverage bug below.
6. **Cross-check in freqtrade** before believing the harness. It caught the
   sizing flaw above: the harness said 22.0% CAGR and freqtrade said 14.5%.

### Harness bugs found and fixed (all in `harness.py`)
- **Drawdown measured the coin loop, not time.** `metrics()` walked the trade
  list as handed to it, and every basket runner builds that list coin by coin
  (`pooled += tr`). So max_dd_r, r_per_dd and worst_streak described the order
  the universe was iterated in. The understatement is large and it is not a
  constant factor: the daily long book reads 6.7R by coin order and 10.3R by
  date, the trendline book 8.0R and 26.5R. `metrics()` now sorts by exit time
  before it measures. Order-independent numbers were never affected, so no
  ranking or selection in this repo was wrong — only the stated cost of it.
- **Detail coverage.** `searchsorted` returns 0 for a timestamp before the detail
  frame starts, pricing a 2021 entry against 2024 candles. `simulate()` now
  refuses signals outside detail coverage.
- **Frame identity.** `load()` is cached and returned by reference; indicator
  caches key on `id(df)`, so re-reading defeated them. Do not mutate results.
- **freqtrade gotcha:** `use_exit_signal = False` silently disables
  `custom_exit()`. Keep it `True` and emit nothing from `populate_exit_trend`.

---

## 5. The grid — finished, and what it found

All 12,960 cells scored, 2,255 of them clearing FIT n>=30 and HOLDOUT n>=20.
Results in `research/results/opt_1d_*.jsonl`, ranking in
`research/results/GRID_REPORT_1d.md`, verification in
`research/results/VERIFY_1d.txt`.

```bash
cd freqtrade-lab
# two workers at a time. Six exhausts a 7 GB box; that is what killed the
# first two attempts. Workers append and resume, so a kill costs only the
# cell in flight.
for w in 0 1 2 3 4 5; do
  ./.venv/Scripts/python.exe research/optimize.py 1d $w 6 >> research/results/opt1d_$w.log 2>&1 &
  [ $((w % 2)) -eq 1 ] && wait
done; wait

PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe research/opt_report.py 1d 20
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe research/verify_grid.py 3
```

**The finding: a wider stop and a further target.** The winning cell is
`wt2_max -20, trigger slope, wait_bars 16, atr_mult 2.0, mfi none, gate none,
target 4R, require_hold False` — quote it in full. "2xATR + 4R" is the headline
but not the config: it also moves wt2_max from -30, wait_bars from 8 and
require_hold from True. Changing only the stop and target gives 15 fit signals
instead of 84 and a negative book. Two dials move the result
and both trend monotonically across every value they take, which is the
signature of a real effect rather than a lucky cell:

| dial | marginal HOLDOUT annual_R |
|---|---|
| atr_mult | 0.5: +0.58 · 1.0: +1.67 · **2.0: +2.47** |
| target | 2R: +0.78 · 3R: +1.45 · **4R: +1.90** · G1_3R scale-out: +0.49 |

Against DailyDivBreakout, on held-out coins, both in date order:

| | baseline (1xATR, 3R) | 2xATR + 4R |
|---|---|---|
| annual_R | 3.74 | **11.80** |
| maxDD_R | 10.3 | 22.9 |
| **ratio** | 0.36 | **0.52** |
| trades/year | 10.9 | 12.1 |
| losing years | 3 of 7 | **1 of 6** |
| holdout coins positive | 15/28 | **19/27** |
| worst losing streak | 9 | 10 |

The six cells around it score +9.0 to +11.8 holdout, so it is a plateau. It
also passes the arithmetic check that matters: it reaches its target **less**
often than the baseline (27% at 4R against 30% at 3R), which is what a further
target must do. The gain comes from the wider stop cutting stop-outs from 62%
to 49%. Five trades were still open at the data end, all five winners; drop
them and holdout annual_R is +10.38 rather than +11.80.

**Do not read the maxDD_R column in `GRID_REPORT_1d.md`.** Those cells were
scored before the drawdown fix and still describe the coin loop. The ranking
column, HOLDOUT annual_R, is order-independent and stands. `verify_grid.py`
re-simulates the leaders and reports the honest drawdown, per-year and per-coin
splits.

**Not yet done:** DailyDivBreakout still ships 1xATR and 3R. Changing it is a
one-line edit in `user_data/strategies/DailyDivBreakout.py` plus a freqtrade
backtest to confirm the second engine agrees, which is the repo's own rule
before believing the harness.

---

## 6. Next steps, ranked by expected value

0. **Paper trade TrendlineBreakout.** It is the best thing here and the least
   forward-tested. `research/scan_trendline.py` prints the current watchlist
   and anything that has already broken.
1. **Ship the grid's finding** (section 5). Move DailyDivBreakout to a 2xATR
   stop and a 4R target, then confirm it in freqtrade. The harness says the
   ratio goes 0.36 -> 0.52 on held-out coins; nothing is banked until the
   second engine agrees.
2. **Expand the universe to 150+ coins.** More independent trades is the
   highest-confidence way to raise annual_R without raising maxDD_R. Current
   universe is 76 (listed in [campaign.py](campaign.py)). This is a download
   plus a re-run — no new research.
3. ~~**Stack TrendlineBreakout with DailyDivBreakout.**~~ **DONE — it does not
   work.** Monthly R correlation +0.300; both books lose in 2022 and in 2025;
   the ratio improves in 1 of 9 coin-set x slot-limit combinations and that one
   reverses when the slot limit moves. Not slot contention — raising the cap to
   20 and 40 does not rescue it. Both are long-only daily breakouts on the same
   76 coins, so different indicators are not different exposures. Findings
   51-52 in the research log; `research/stack.py` reproduces it.
4. **Find a second book that differs in EXPOSURE, not in indicator.** Now the
   top research priority, and finding 52 constrains it: another long-only
   breakout on the same universe will fail exactly as the stack did, however
   good its trigger. It must not be long crypto beta. Candidates:
   **funding-rate carry** (paid by position imbalance, not price direction),
   **cross-sectional relative strength** — long strong against short weak, so
   the market component nets out, and it is the repo's own core feature that no
   work here has used — or any market-neutral construction.
5. **Walk-forward the oversold dial** instead of fixing it at −30.
6. **Paper trade DailyDivBreakout** in parallel with all of the above. 2023
   produced 69% of its profit and no amount of backtesting can settle whether
   that was luck — only forward evidence can.

### Explicitly do NOT
- Raise TrendlineBreakout's slot count to chase its 20-slot CAGR of 37.5%.
  That is the same bet at higher size, not a better bet.
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
[optimize.py](optimize.py) | the 12,960-config grid (divergence family) |
[trendline.py](trendline.py) | `trendline_breakout` — the long-term descending line |
[tl_campaign.py](tl_campaign.py) | single-dial sweeps: exits, line, quality, weekly |
[tl_grid.py](tl_grid.py) | the 468-config trendline grid, checkpointed |
[tl_report.py](tl_report.py) | marginals, fit ranking, neighbour agreement |
[tl_portfolio.py](tl_portfolio.py) | account sim for the trendline book |
[tl_final.py](tl_final.py) | the chosen config: slot cost, years, concentration |
[scan_trendline.py](scan_trendline.py) | live: what broke, what is pressing the line |
[opt_report.py](opt_report.py) | grid ranking with all four overfit guards |
[verify_grid.py](verify_grid.py) | re-simulates the leaders: date-ordered drawdown, per-year and per-coin splits, against the proven book |
[scan_divergence.py](scan_divergence.py) | live multi-timeframe divergence scan |
[breach_test.py](breach_test.py) | shallow vs deep breach test |
[ETH_RESEARCH_LOG.md](ETH_RESEARCH_LOG.md) | full derivation, 50 numbered findings |
[STRATEGY_DailyDivBreakout.md](STRATEGY_DailyDivBreakout.md) | the strategy spec |
[STRATEGY_TrendlineBreakout.md](STRATEGY_TrendlineBreakout.md) | the best strategy's spec |

Freqtrade strategies live in `../user_data/strategies/`. `TrendlineBreakout.py`
is the one that matters; `DailyDivBreakout.py` is the previous best.

**Harness note:** `ExitPlan` now supports a trailing stop (`trail_r`,
`trail_start_r`), off by default so every earlier result is unchanged. The trail
is raised from a bar's extreme only AFTER that bar's stop has been tested, so a
single bar can never both extend and protect a trade.

**Configs are gitignored** (they hold the API-server password and would hold
exchange keys). Rebuild from `config.example.json`; whitelists are in
[campaign.py](campaign.py). `config-big.json` = the 76-coin universe.

**Data on disk:** 76 coins at 1d (from 2018) and 1h (from 2020); ~60 coins at
15m; ~45 at 5m. Everything Binance spot.
