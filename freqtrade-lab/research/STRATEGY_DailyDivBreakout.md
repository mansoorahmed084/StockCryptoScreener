# DailyDivBreakout — promising, not finished

**Status:** the only strategy developed in this repo's `freqtrade-lab/research`
work that is positive on coins it was never tuned on, in two independent
engines, at every parameter setting tested. Recorded here as a baseline to
improve on, **not** as a finished system. Read [Known
weaknesses](#known-weaknesses) before doing anything with it.

Full derivation: [ETH_RESEARCH_LOG.md](ETH_RESEARCH_LOG.md) phases 6–7.
Code: [breakout.py](breakout.py) · [DailyDivBreakout.py](../user_data/strategies/DailyDivBreakout.py)

---

## The rules

**Universe:** 76 liquid Binance USDT spot pairs — majors plus volatile mid-caps.
**Timeframe:** daily candles. **Direction:** long only.

### Entry — all four, in this order

1. **VMC bullish divergence.** Price sets a lower low while WT2 sets a higher
   low, both pivots below zero. The pivot counts only once confirmed by **3
   later daily closes** — this lag is what makes the signal knowable rather than
   hindsight.
2. **Oversold at the pivot:** WT2 ≤ **−30** on the divergence pivot bar.
3. **Structure break.** Within **8 days** of confirmation, a daily close above a
   falling line least-squares fitted through the highs since the pivot. If the
   fitted slope is positive, the level falls back to the highest high instead.
   *This condition came from the trader's own charts and is the single most
   valuable ingredient — see [Evidence](#evidence).*
4. **The low must hold.** If price trades below the divergence pivot low before
   the break, the setup is dead. No re-entry, no tolerance
   ([finding 40](ETH_RESEARCH_LOG.md) measured shallow breaches at −0.196R,
   no better than deep ones).

Enter at the **next daily open** after the breakout close.

### Risk and exit

| | |
|---|---|
| Stop | lowest low of the setup − **1 × ATR(14)** |
| Skip if | that stop sits further than **15%** from entry |
| Target | **3R**, single exit |
| Time stop | **60 days** |
| Size | **1%** of equity risked per trade |
| Concurrency | max **10** open positions |
| Costs assumed | **0.15% per side** (0.1% fee + 0.05% slippage) |

---

## Measured performance

76 coins, 2020-01 → 2026-09 (6.7 years), 1% risk per trade, freqtrade with 1h
detail candles for intrabar fills.

| | DailyDivBreakout | VmcCapitulation (the repo's prior best) |
|---|---|---|
| CAGR | **10.53%** | 5.12% |
| Total return | +95.24% | +39.55% |
| Profit factor | **1.73** | 1.66 |
| Win rate | 37.1% at 3R | 60% at 1.5R |
| Max drawdown | 18.61% (32.19% balance) | 9.96% |
| Trades / year | 19.8 | 9.7 |
| Avg hold | 23.9 days | 7.0 days |

On ₹1,00,000 at 1% risk: about **₹10,500 a year**, with a worst drawdown of
about **₹18,600**.

---

## Evidence

### It survives coins it never saw

The 76-coin universe is split by **hashing the coin name**, so fit/holdout
membership carries no market-cap, listing-age or sector information.

| coin set | trades | win% | profit | max DD |
|---|---|---|---|---|
| FIT (40 coins) | 64 | 37.5 | +25.21% | 11.52% |
| **HELD OUT (36 coins)** | **69** | **37.7** | **+32.94%** | **9.30%** |

Held out beat fit. This matters because phase 3 established that a strategy
tuned on one instrument can lose money on every other one while passing every
date-split out-of-sample test.

### It is a plateau, not a spike

Every setting of the oversold dial is positive out of sample, and the structure
break improves every pairing:

| WT2 ≤ | structure break | HELD-OUT avgR | PF | maxDD_R |
|---|---|---|---|---|
| −30 | no | +0.133 | 1.19 | 29.2 |
| **−30** | **yes** | **+0.342** | **1.54** | **6.7** |
| −40 | no | +0.030 | 1.04 | 31.6 |
| −40 | yes | +0.266 | 1.41 | 6.7 |
| −50 | no | +0.149 | 1.22 | 12.3 |
| −50 | yes | +0.301 | 1.48 | 4.1 |

The break roughly triples expectancy and cuts drawdown by 4–5×, consistently.

### Two engines agree

The fast research harness and freqtrade produce win rates within 2 points of
each other on both baskets. Given how many bugs this project has surfaced
(lookahead in a bucket definition, detail-coverage mispricing, an exit callback
silently disabled), agreement between independent implementations is doing real
work here.

---

## Known weaknesses

**1. 2023 produced 69% of all profit.** Per ₹1 lac, by year:

| Year | Result |
|---|---|
| 2020 | +14,010 |
| 2021 | −1,160 |
| 2022 | −13,390 |
| **2023** | **+65,860** |
| 2024 | +20,480 |
| 2025 | −3,420 |
| 2026 | +12,850 |

Four up years, three down. **The held-out-coin test cannot detect this** — both
baskets lived through 2023. Only forward evidence can distinguish "works, and
2023 was a good year for it" from "needed 2023".

**2. Drawdown is 18.6% closed, 32.2% on a balance basis.** Higher than
VmcCapitulation at roughly double the return, so the improvement is partly just
more risk taken.

**3. Twenty trades a year.** Daily bars work *because* the 0.15% cost is small
against a multi-percent stop — and that is the same reason they are slow. On 15m
the fee eats 18% of every R; on daily, ~3%.

**4. Long only.** Short mirrors of related entries measured at −0.003R against
+0.220R for longs in phase 2 and were never rescued.

**5. Survivorship bias.** The 76 coins are today's listings. Coins that
delisted are absent, which flatters any long-biased strategy.

---

## How to run it

```bash
cd freqtrade-lab
.venv/Scripts/freqtrade.exe download-data --config config-big.json --timeframes 1d 1h --timerange 20180101-
.venv/Scripts/freqtrade.exe backtesting --config config-big.json --strategy DailyDivBreakout \
    --timeframe 1d --timeframe-detail 1h --timerange 20200101- --fee 0.0015 --max-open-trades 10
```

`config-big.json` is gitignored; build it from `config.example.json` with the
76-pair whitelist listed in [campaign.py](campaign.py).

---

## Improvement ideas, ranked by what the evidence suggests

1. **Forward paper trading.** Not an improvement, a prerequisite. The 2023
   concentration is unresolvable from history.
2. **Reduce the drawdown.** The gate cut drawdown 3× on other entries but was
   never tuned here. A market-wide BTC filter is untested on this entry.
3. **Raise frequency without leaving daily** — more coins is the only lever
   that does not touch the cost economics. 76 → 150 would roughly double trades.
4. **Walk-forward the oversold dial** rather than fixing it at −30.
5. **Model funding and test a real short side** on futures data, rather than
   the price-inversion approximation.

---

## The short mirror

Built by price inversion — a short on X is a long on 1/X with high and low
swapped — which is the technique `backend/research/strategy.py` already uses.
WaveTrend is odd-symmetric in price, so a bull divergence on the inverted series
*is* a bear divergence on the original. **Funding is not modelled.**

Thresholds are symmetric: −30 means WT2 ≤ −30 for longs, WT2 ≥ +30 for shorts.

| side | wt2 | trigger | FIT avgR | **HELD-OUT avgR** | PF | coins + |
|---|---|---|---|---|---|---|
| long | −30 | break | +0.455 | **+0.342** | 1.54 | 4/4 |
| long | −40 | break | +0.574 | **+0.266** | 1.41 | 4/4 |
| long | −50 | break | +0.804 | **+0.301** | 1.48 | 1/2 |
| short | −30 | none | −0.052 | **−0.222** | 0.68 | 1/5 |
| short | −40 | none | +0.151 | **−0.237** | 0.66 | 0/5 |
| short | −50 | none | +0.031 | **−0.193** | 0.72 | 1/4 |

### Finding 49 — the short mirror does not work on its own

Negative on held-out coins at every threshold, profit factor 0.66–0.72, positive
on at most 1 coin in 5. The structure-break trigger could not even be tested on
the short side: it starved the sample below 30 trades, because falling-line
breaks are common in crypto and rising-line breakdowns are not.

This repeats phase 2, where the short mirror of the pullback entry measured
−0.003R against +0.220R for longs. Two different entries, same answer. The
likely cause is structural: the universe rose over 2020–2026, and it is today's
listings, so anything that failed and delisted is absent. Both facts flatter
longs and punish shorts.

### Finding 50 — but shorts win in exactly the years longs lose

Portfolio simulation, ₹1,00,000, 1% risk per trade, max 10 concurrent, walked in
chronological order so overlapping signals contend for slots
([portfolio.py](portfolio.py)):

| year | LONG pnl | SHORT pnl | **COMBINED pnl** | combined return |
|---|---|---|---|---|
| 2020 | +17,900 | −8,904 | **+7,402** | +7.4% |
| 2021 | **−1,193** | **+4,222** | **+3,840** | +3.6% |
| 2022 | **−5,379** | **+9,678** | **+8,059** | +7.2% |
| 2023 | +24,640 | −17,078 | **+2,705** | +2.3% |
| 2024 | +15,731 | −3,114 | **+10,647** | +8.7% |
| 2025 | **−3,544** | **+3,422** | **+2,128** | +1.6% |
| 2026 | +13,001 | +2,983 | **+23,090** | +17.1% |

The three years the long book lost money — 2021, 2022, 2025 — are three of the
four years the short book made money. The correlation is strongly negative, and
the consequence is the interesting part:

| | LONG only | SHORT only | COMBINED |
|---|---|---|---|
| CAGR | **+7.41%** | −1.37% | +7.07% |
| profit factor | **1.59** | 0.90 | 1.31 |
| max drawdown | **17.24%** | 26.34% | 20.78% |
| **losing years** | **3 of 7** | 3 of 7 | **0 of 7** |
| worst year | −5,379 | −17,078 | **+2,128** |
| share of profit from best year | **69%** (2023) | — | **40%** (2026) |

**Adding a losing book made the account more consistent.** Combined gives up
0.34 points of CAGR and takes 3.5 points more drawdown, and in exchange every
single year is positive and the profit concentration that was the long book's
main weakness drops from 69% to 40%.

That is a real diversification effect, not a rounding artefact — but note what
it is not. The short book has **negative expectancy**. It is being carried as a
hedge, and a hedge with negative expectancy costs money on average. Whether that
is worth paying depends on whether the smoother equity curve is what you need.

### Caveats specific to the combined result

* Shorts here are a price-inversion approximation. A real short needs futures,
  and **funding costs are not modelled** — on perpetuals those are charged every
  8 hours and would make the short book worse than shown.
* This portfolio simulation gives a lower long-only CAGR (7.41%) than the
  freqtrade run of the same rules (10.53%), because the two handle position
  sizing and slot contention differently. Treat the range 7–10% as the honest
  uncertainty, not either endpoint as the number.
* Seven years, one of them partial at each end.
