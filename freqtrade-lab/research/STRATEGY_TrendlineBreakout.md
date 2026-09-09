# TrendlineBreakout — the long-term line, mechanised

**Status:** the best result this project has produced. Positive on held-out
coins in **468 of 468** grid cells. On the same freqtrade command as
[DailyDivBreakout](STRATEGY_DailyDivBreakout.md) it earns **14.5% CAGR against
10.7%**, at 21.0% drawdown against 18.5% — better, but not by a wide margin.
Read [Known weaknesses](#known-weaknesses) before sizing anything on it: the
signals are heavily correlated, two of seven years lost money, and freqtrade's
mark-to-market drawdown metric reads far worse than the closed-trade one.

Code: [trendline.py](trendline.py) ·
[TrendlineBreakout.py](../user_data/strategies/TrendlineBreakout.py)
Results: [tl_grid_report.md](results/tl_grid_report.md) ·
[tl_final.md](results/tl_final.md)

---

## Where it came from

Two daily charts, TAO/USDT and STX/USDT. Both show the same thing: one falling
line anchored at a major high, resting on every lower high for the better part
of a year, and a break that ran far — STX went from about 0.13 to 0.29.

That is **not** what [DailyDivBreakout](STRATEGY_DailyDivBreakout.md) trades.
There the line is fitted over the handful of bars since a divergence pivot, and
the trade is closed at 3R. Here the line spans months, no divergence is
required, and the trade is left to run.

---

## The rules

**Universe:** 76 liquid Binance USDT spot pairs. **Timeframe:** daily candles.
**Direction:** long only.

### Drawing the line

A hand-drawn trendline is picked with hindsight. A mechanical one must not be,
so at every candidate bar `i` the line is rebuilt from bars **strictly before**
`i`:

```
a = index of the highest high in the previous 200 bars      (the anchor)
s = max over k in (a, i) of (high[k] - high[a]) / (k - a)    (the slope)
```

`s` is the shallowest slope from the anchor that still keeps every intervening
high at or below the line — exactly the line a trader draws down across the
lower highs, touching at least two and cut by none. It needs no future bar, so
acting on it at bar `i` is possible in real time.

### Entry — all six

1. **The line must fall.** `s < 0`. A flat or rising line is a range, not a
   downtrend.
2. **It must be long term.** At least **60 days** from the anchor to the break.
3. **The downtrend must be real.** Price must have fallen at least **25%**
   beneath the anchor high.
4. **Highs must actually sit on it.** At least **3** highs within **3%** of the
   line, the anchor included.
5. **The break.** Today closes **above** the line and yesterday closed below
   it. One signal per anchor, and a 20-day cooldown, so a single event does not
   fire four entries.
6. **Volume confirms.** Break-bar volume ≥ **1.5×** its own 20-day mean. This
   is the single most valuable filter — see [Evidence](#evidence).

Enter at the **next daily open** after the breakout close.

### Risk and exit

| | |
|---|---|
| Stop | lowest low of the last **20 days** − **1.5 × ATR(14)** |
| Skip if | that stop sits further than **25%** from entry |
| Exit | **trailing stop 3R behind the running high**, once 1R in front |
| Time stop | **365 days** |
| Size | **1%** of equity risked per trade |
| Concurrency | max **10** open positions |
| Costs assumed | **0.15% per side** (0.1% fee + 0.05% slippage) |

The trailing exit is not a detail. It is the strategy.

---

## Measured performance

76 coins, 2020-01 → 2026-09 (6.7 years), 1% risk, compounding, max 10 open,
1h detail candles for intrabar fills. **Both strategies run through the same
freqtrade command, same config, same period**, so the comparison is fair.

| freqtrade, identical config | TrendlineBreakout | DailyDivBreakout |
|---|---|---|
| CAGR | **14.54%** | 10.71% |
| Total return | +147.9% | +97.4% |
| Max drawdown (closed trades) | 21.04% | 18.53% |
| CAGR per unit of drawdown | **0.69** | 0.58 |
| Profit factor | **1.82** | 1.75 |
| Win rate | 37.7% | 37.1% |
| Trades | 162 | 132 |
| Average hold | 55 days | 24 days |
| Best trade | DOGE **+236%** | — |

The research harness, sizing corrected (see below), independently gives **17.4%
CAGR at 20.1% drawdown** — within 3 points of freqtrade, which is the agreement
standard this project uses.

So: **about 35-60% more CAGR than the previous best, at 2-3 more points of
drawdown.** Better, clearly. Not double.

Held-out coins beat fit coins (16.9% vs 11.0% CAGR, corrected sizing), which is
the pattern that matters: the rules were never tuned on those coins.

### A flaw found in the repo's own account simulator

[portfolio.py](portfolio.py) walks trades in ENTRY order and credits each
trade's whole profit to equity immediately, so a trade opened in January and
closed in December funds the size of a trade opened in February. It is
compounding money the account does not have yet.

It barely matters for a strategy holding a few days. It matters here: winners
average 74 days. Correcting it ([tl_account.py](tl_account.py), an event queue
that sizes at entry and banks at exit) moves this strategy from a reported
22.0% CAGR to **17.4%**. Every earlier number in this project that came from
`portfolio.py` is optimistic by some smaller amount for the same reason.

## Evidence

### 1. The move is the edge — a fixed target throws it away

Same entries, same coins, held-out basket only:

| exit | holdout annual_R | maxDD_R | ratio |
|---|---|---|---|
| fixed 3R | 5.53 | 39.7 | **0.14** |
| fixed 5R | 13.51 | 24.8 | 0.54 |
| fixed 8R | 15.37 | 31.4 | 0.49 |
| trail 2R | 6.37 | 35.1 | 0.18 |
| **trail 3R** | 19.46 | 25.0 | **0.78** |
| trail 4R | 16.84 | 26.6 | 0.63 |

Capping at 3R destroys five sixths of the result. The trader's claim that these
breaks run far is what the numbers say too.

### 2. It is a plateau, not a ridge

A 468-cell grid over lookback × min_span × volume × ATR × trail
([tl_grid.py](tl_grid.py), ranked by [tl_report.py](tl_report.py)):

**468 of 468 cells are positive on held-out coins.** Median holdout ratio 1.86
against the 0.56 this project had to beat. Every cell in the top ranking scores
100% neighbour agreement. A result that survives every setting of every dial
does not depend on the settings.

The chosen config was taken from the grid **marginals** — the average over
every setting of the other dials — not from the top of the fit ranking, because
a marginal is far harder to reach by luck than one good cell.

| dial | best value | mean holdout ratio across the grid |
|---|---|---|
| volume | **1.5×** | None 1.47 → 1.25× 1.99 → **1.5× 2.41** → 2.0× 1.91 |
| ATR stop | **1.5** | 0.5 → 1.96, 1.0 → 1.71, **1.5 → 2.17** |
| lookback | **200** | 130 → 2.68, **200 → 2.29**, 260 → 1.78, 400 → 1.48 |
| min_span | 60–120 | 30 → 1.91, **60 → 2.04**, 120 → 2.08, 200 → 1.62 |
| trail | 2.5–4.0 | 2.5 → 1.97, **3.0 → 2.02**, 4.0 → 1.84 (flat: robust) |

### 3. It does not use the future

Every signal was re-derived on a frame with all later bars **physically
deleted**. 147 signals checked, 147 survived. This is the test that phase 5's
fake +0.709R result would have failed, and `lookahead-analysis` would not have
caught it.

### 4. No single coin or trade carries it

62 coins traded. Best coin (DOGE) contributes 21% of total R, top three 41%,
best single trade 8%. Best year is 42% of total R — better than
DailyDivBreakout's 69%.

---

## Known weaknesses

**The signals are one bet, not thirty.** Alts break their trendlines together.
The live scan ([scan_trendline.py](scan_trendline.py)) shows almost every
current line anchored in the same month — the whole market topped together. A
10-slot account fills only **54%** of whole-universe signals; the other 46%
arrive with no slot free. Raising to 20 slots lifts the reported CAGR but also the
drawdown, which is the same bet at higher size, not a better one.

**Unrealised drawdown is much worse than realised drawdown.** freqtrade reports
21.04% "underwater" on closed trades but **76.05%** on the mark-to-market wallet
balance — against 18.53% and 32.09% for DailyDivBreakout. Positions are held 55
days on average, up to ten at once, behind a stop that sits a full 3R behind the
high. So the equity a trader actually watches swings far harder than the closed
-trade figure suggests. **This gap is not fully explained and should be the
first thing checked before risking money.**

**Two of seven years lost money**, and the calendar is lumpy (corrected sizing,
whole universe, max 10 open):

| year | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| return | +57.1% | +4.5% | −7.2% | +36.6% | +38.4% | −10.5% | +13.1% |

2021 is nearly flat on 4 trades, and mechanically so: a bull market has no
long-standing descending lines to break. **This strategy needs a market that
has been falling**, which is also why 2020 and 2023 are so large.

**Survivorship bias.** The 76 coins are ones listed on Binance today. Coins
that were delisted are absent, so the absolute CAGR is optimistic. The
comparison with DailyDivBreakout is fair — same universe — but the number
itself is not what a live account would have made.

**Six and a half years, ~166 filled trades.** Two bull cycles. That is not
enough to settle whether 2023 and 2024 were the strategy or the market.

---

## What to do next

1. **Explain the 76% mark-to-market drawdown** before anything else. If it is
   real rather than an artifact of open positions at the backtest's end, the
   trailing stop needs tightening or the slot count needs cutting.
2. **Paper trade it.** The scan already names the watchlist. Forward evidence is
   the only thing that separates edge from a well-fitted 2023.
3. **Expand the universe past 150 coins.** Correlation is the binding
   constraint, and more coins is the only lever on it that does not need new
   research.
4. **Stack it with DailyDivBreakout.** They share a universe but not a trigger,
   and both are positive. Two positive books is the one combination
   [HANDOVER.md](HANDOVER.md) §3 identified as raising the ratio rather than
   lowering it.
5. **Do not raise the slot count to chase the 37.5% number.** That is leverage
   wearing a disguise.
