# Refining the trendline entry on lower timeframes — 600 permutations

**The question:** the daily strategy takes the next daily open and stops out
under a 20-day low, roughly 21% away. Can 1h candles time the entry better, or
place the stop closer, or both?

**The answer:** the stop, yes — decisively. The entry timing, no. Waiting for a
1h confirmation, a retest of the broken line, or an EMA pullback all scored
*worse* than simply taking the next daily open. And the stop only pays off once
the exit stops being measured in R.

Code: [refine.py](refine.py) · [rf_grid.py](rf_grid.py) ·
[rf_report.py](rf_report.py) · [rf_final.py](rf_final.py)
Raw: [rf_grid_report.md](results/rf_grid_report.md) ·
[rf_final.md](results/rf_final.md)

---

## What was tested

The daily breakout signal is held **fixed** at the validated config in
[STRATEGY_TrendlineBreakout.md](STRATEGY_TrendlineBreakout.md). Only what
happens *after* the daily close varies, so every difference is attributable to
the refinement.

| dial | values |
|---|---|
| entry timing | `next_open` (control), `ltf_break`, `retest`, `pullback_ema` |
| stop placement | `daily` (control), `ltf_swing`, `line`, `tighter` |
| how long to wait for the trigger | 24h, 72h, 168h |
| ATR buffer under the 1h stop | 0.5, 1.0, 2.0 |
| exit | trail 3R, 6R, 9R, or trail 15%, 25%, 35% of the high |

**600 cells**, scored on a FIT basket and a HOLDOUT basket of coins split by
hashing the coin name. `next_open` + `daily` is the control and sits inside the
grid, so it is measured by the same engine as everything else.

**600 of 600 cells are positive on held-out coins.**

---

## 1. Entry timing: waiting does not help

Each cell averages over every wait, ATR and exit setting, so no cell can be a
lucky corner. Numbers are the holdout ratio (annual_R / maxDD_R).

| entry timing → | `next_open` | `ltf_break` | `retest` | `pullback_ema` |
|---|---|---|---|---|
| **marginal ratio** | **1.97** | 1.77 | 1.01 | 1.00 |

Taking the next daily open beats every mode that waits. `retest` and
`pullback_ema` are barely half as good, and they also lose a third of the
trades — `retest` fills 100 of 162 signals, because price often never comes
back.

**Why:** these breaks tend to go immediately. Waiting for a pullback
systematically filters out the ones that run, which are the ones that pay for
everything else.

## 2. Stop placement: this is where the gain is

| stop → | `daily` | `ltf_swing` | `line` | `tighter` |
|---|---|---|---|---|
| **marginal ratio** | 1.13 | **1.53** | 1.00 | **1.53** |

Median stop distance falls from about **21% to 6%**. `tighter` scores
identically to `ltf_swing` because the 1h swing low is almost always the nearer
of the two, so `max()` picks it every time — they are the same rule in practice.

The broken line itself (`line`) is no better than the daily stop.

## 3. The exit has to be decoupled from the stop

| exit → | 3R | 6R | 9R | 15% | 25% | 35% |
|---|---|---|---|---|---|---|
| **marginal ratio** | 0.89 | 1.54 | **1.68** | 0.90 | **1.65** | 1.34 |

An R-based trail **scales with the entry stop**. Tighten the stop and the trail
tightens with it in price terms, so the tighter stop buys nothing. That is why
3R is the worst R setting here even though it was the best on the daily
strategy — and why the percent trail, which is scale-free, matters.

A 15% trail is as bad as 3R: too tight either way. The move needs room.

## 4. Which change did the work — a clean 2x2

Holdout coins, everything else identical:

| | trail 3R | trail 25% |
|---|---|---|
| **daily stop** | **0.98** ← the old strategy | 1.75 |
| **1h stop** | 1.72 | **2.54** |

Both changes help on their own by about the same amount (+0.77 and +0.74), and
together they roughly add (+1.56). There is no interaction trickery.

Note the middle cells: the 1h stop with a 3R trail *lowers* average R (+0.96 vs
+1.08) and still improves the ratio, because the drawdown halves. Only when the
exit is freed does average R jump — from **+1.08 to +1.96**.

---

## The winner

`next_open` entry · `ltf_swing` stop, 1.0 x ATR(1h) · **25% trailing exit**

Chosen on FIT ratio (2.37, the highest in the family), with the marginals
agreeing on every dial independently.

### Pooled R, held-out coins, 15m fills

| | control (daily stop, 25% trail) | **refined** |
|---|---|---|
| trades | 127 | 126 |
| win rate | 48.0% | 36.5% |
| average R | +1.111 | **+2.074** |
| profit factor | 4.17 | **4.35** |
| maxDD_R | 13.1 | 18.6 |
| **ratio** | 1.61 | **2.10** |

Fewer wins, much bigger wins.

### The account — and the capital problem

Position size is risk divided by stop distance. A 1% risk behind a **6% stop is
a 17% position**, and ten of those is 167% of the account — which spot cannot
do. The research measured a peak exposure of **178%** unconstrained. So the
account simulation caps total notional at 100% of equity; a trade that does not
fit is sized down, and skipped if less than a quarter of it fits.

The daily strategy is untouched by that cap (its stops are wide, so its
positions are small, peaking at 62%). The refined one is not.

15m fills, max 10 open, 1% risk, profit banked at exit, spot cap 100%:

| | coins | fills | win% | **CAGR** | PF | **maxDD** | peak exposure |
|---|---|---|---|---|---|---|---|
| control | HOLDOUT | 106 | 46.2 | 19.7% | 4.48 | 9.1% | 57% |
| control | ALL | 163 | 41.7 | 21.4% | 3.11 | 16.5% | 62% |
| **refined** | HOLDOUT | 108 | 33.3 | **34.6%** | 4.32 | 17.3% | 102% |
| **refined** | ALL | 174 | 29.9 | **48.3%** | 3.81 | 21.1% | 103% |

Uncapped the refined figure is 62.4% at 23.1% drawdown; the cap costs 14 CAGR
points and is not optional.

---

## Checks that were run

**Lookahead — 0 of 98 signals used the future**, in every entry mode, with the
1h frame truncated at the decision bar so not even the entry bar exists.

This check earned its place twice. It caught a genuine bug — the risk filter
was reading the *next* bar's open, the price the fill lands on, which is not
known when the decision is made. And it caught an over-strict guard that
required the entry bar to exist in the frame. Both are fixed; the numbers above
are post-fix.

**Fill resolution — not an artifact.** A 6% stop is far more sensitive to
intrabar sequencing than a 21% one, so the same trades were re-walked on 1h,
15m and 5m candles over one fixed window and coin set:

| detail | refined holdout avgR |
|---|---|
| 1h | +0.437 |
| 15m | +0.475 |
| 5m | +0.425 |

They agree. (An earlier 1h-vs-15m gap turned out to be the *date range* — 15m
data starts 2020-10, which drops the large 2020 trades — not the resolution.)

---

## Caveats, in order of how much they should worry you

**1. The recent 18 months are flat.** On the 40 coins with 5m data, from
2025-04 onward, there are only 67 trades and the FIT basket is *negative* for
both variants (refined holdout +0.437R, fit −0.012R). The year table says the
same: 2025 was −0.4%, and 2023 and 2024 carry almost everything. Small sample,
but it is the most recent evidence there is.

**2. A 17% position in a mid-cap alt on a breakout day.** The backtest assumes
0.05% slippage. That is optimistic at this size, and the refined version is
three times larger per position than the daily one. This is the most likely
place the live result underperforms.

**3. The capital cap binds.** Peak exposure is 103% even after capping, meaning
the account is essentially always fully invested during clusters. Any entry
arriving then is refused. More slots does not fix it — there is no capital.

**4. Win rate drops to 30%.** Seven losses in ten. The old version won 42%.
That is a much harder thing to sit through for the same money.

**5. Everything downstream of the daily signal inherits its weaknesses** —
correlated signals, survivorship bias in the 76-coin universe, and 6.7 years
covering two cycles. See
[STRATEGY_TrendlineBreakout.md](STRATEGY_TrendlineBreakout.md#known-weaknesses).

---

## What is dead (do not re-test without a new reason)

| idea | result |
|---|---|
| waiting for a 1h break of the daily bar's high | marginal 1.77 vs 1.97 for not waiting |
| waiting for a retest of the broken line | 1.01; also loses a third of the trades |
| waiting for a 1h EMA pullback | 1.00 |
| the broken trendline as the stop | 1.00, no better than the daily stop |
| an R-based trail on a tightened stop | it scales with the stop and cancels the gain |
| a tight trail of any kind (3R or 15%) | 0.89 / 0.90; the move needs room |
