# ETH/USDT 1h + 4h — strategy research log

**Goal:** ~60% accuracy at 1:3 risk/reward on ETH/USDT, 1h and 4h.
**Data:** Binance spot, 2020-10 → 2026-09 (~5.9 years). 4h signals resolved on
1h detail candles, 1h signals on 5m detail candles.
**Costs:** 0.15% per side (0.1% fee + 0.05% slippage), matching STRATEGY_RESEARCH.md.
**OOS split:** 2026-01-27, the same boundary the repo's earlier research used.

Harness: [harness.py](harness.py) · signals: [strategies.py](strategies.py) ·
driver: [sweep.py](sweep.py) · ranking: [aggregate.py](aggregate.py).
Signal code imports `backend.indicators.vumanchu` directly, so the oscillator is
the screener's own.

---

## Reading the two win-rate columns

The brief says "60% accuracy with 1:3". Those can mean two different things and
they give very different numbers, so every table reports both:

- **win_net%** — the trade closed net positive. With a scale-out exit this is
  driven by the probability of reaching +1R before the stop.
- **win_3R%** — the trade actually reached the full +3R target.

The repo's own Iteration F established that no exit structure can beat the
entry's 1R-first probability, and that 70% at a *fixed* 2R "does not exist in
this signal family". A fixed 3R is harder still. So the reachable reading of the
brief is **win_net ≥ 60% with a 1:3 runner** — the G3 shape. Both columns are
reported so the strict reading is never hidden.

---

## Batch 1 — baselines (12 runs)

Port the repo's two concluded strategies to ETH alone at a fixed 3R, plus two
deliberately known-bad control arms.

| strategy | tf | exit | n | win_net% | win_3R% | avgR | PF | OOS n |
|---|---|---|---|---|---|---|---|---|
| 4h capitulation, BTC gate | 4h | 3R | 20 | 45.0 | 45.0 | +0.72 | 2.22 | 1 |
| 4h capitulation, no gate | 4h | 3R | 59 | 30.5 | 30.5 | +0.16 | 1.22 | 4 |
| 4h capitulation, wt2≤−60 | 4h | 3R | 10 | 60.0 | 60.0 | +1.32 | 4.09 | 0 |
| 4h blow-off fade, BTC gate | 4h | 3R | 8 | 12.5 | 12.5 | −0.57 | 0.39 | 1 |
| 4h blow-off fade, no gate | 4h | 3R | 64 | 17.2 | 14.1 | −0.42 | 0.51 | 5 |
| 1h capitulation, BTC gate | 1h | 3R | 110 | 30.9 | 29.1 | +0.10 | 1.13 | 11 |
| 1h capitulation, 4h gate | 1h | 3R | 37 | 29.7 | 29.7 | +0.03 | 1.04 | 3 |
| 1h blow-off fade | 1h | 3R | 75 | 21.3 | 18.7 | −0.29 | 0.67 | 9 |
| CONTROL 1h WT cross-up | 1h | 3R | 1198 | 24.8 | 24.2 | −0.12 | 0.86 | 127 |
| CONTROL 4h Bollinger rev. | 4h | 3R | 97 | 17.5 | 15.5 | −0.35 | 0.58 | 19 |
| 4h capitulation, G3 scale-out | 4h | 1R+3R | 20 | **60.0** | 40.0 | +0.42 | 2.00 | 1 |
| 4h fade, G3 scale-out | 4h | 1R+3R | 8 | 25.0 | 12.5 | −0.51 | 0.36 | 1 |

**Findings**

1. **The 4h capitulation long is the only live edge on ETH.** Everything else is
   flat or negative.
2. **The blow-off fade does not survive on a single coin.** It was the repo's
   short-side winner across 25 alts; on ETH alone it is −0.42R. The fade needed
   a basket to find enough euphoric extremes.
3. **Controls behaved as predicted.** The 1h WT cross-up came in at −0.12R over
   1198 trades, independently confirming the repo's "1h mean-reverts, cross-up
   continuation is an anti-edge" finding. A control arm that reproduces a known
   negative is evidence the harness is wired correctly.
4. **Scale-out is the win-rate lever**, exactly as Iteration F said: identical
   entries went 45% → 60% win_net when half the position books at 1R.
5. **Everything good had n≈20.** Not tradeable, not significant. Frequency became
   the problem to solve.

---

## Batch 2 — 4h capitulation grid (1008 runs)

Dials: `wt2_extreme` × `atr_mult` (stop width) × `pivot_lookback` × regime gate
× exit shape. Filters: n ≥ 40 and OOS n ≥ 4. **120 of 1008 survived.**

**Best by net-win rate**

| config | n | /yr | win_net% | win_3R% | avgR | PF | maxDD_R | IS win% | OOS n |
|---|---|---|---|---|---|---|---|---|---|
| wt2≤−45, atr×1.5, piv3, no gate, **G3** | 48 | 8.1 | **62.5** | 22.9 | +0.271 | 1.70 | 5.2 | 65.1 | 5 |
| wt2≤−40, atr×1.5, piv2, no gate, G3 | 60 | 10.1 | **61.7** | 21.7 | +0.252 | 1.64 | 7.2 | 63.6 | 5 |
| wt2≤−35, atr×1.5, piv2, no gate, G3 | 67 | 11.3 | **61.2** | 20.9 | +0.230 | 1.58 | 7.2 | 62.9 | 5 |

**Best by expectancy**

| config | n | win_net% | win_3R% | avgR | PF |
|---|---|---|---|---|---|
| wt2≤−40, atr×1.5, piv3, no gate, **fix 3R** | 57 | 40.4 | 33.3 | **+0.446** | 1.72 |
| wt2≤−45, atr×1.5, piv3, no gate, fix 3R | 48 | 39.6 | 33.3 | +0.424 | 1.68 |

**Marginal analysis — which dials are real**

| dial | trend across values | verdict |
|---|---|---|
| `atr_mult` | 0.25: +0.127 · 0.5: +0.131 · 1.0: +0.166 · **1.5: +0.204** | real, monotonic, still rising at the grid edge |
| `exit` | G3: +0.134 · G3b: +0.137 · **fix3R: +0.211** | real, and it is the win-rate/expectancy trade-off |
| `wt2` | −30: +0.106 · −35: +0.190 · **−40: +0.202** · −45: +0.159 · −50: +0.185 | plateau −35…−50, only −30 is clearly worse |
| `pivot` | 2: +0.161 · **3: +0.200** · 4: +0.067 | 3 best, 4 clearly worse |
| `gate` | only `nogate` survived at all | see below |

**Findings**

6. **Every regime gate starves ETH of signals.** Not one gated config cleared
   n ≥ 40. The BTC gate is the single most valuable filter in the repo's daily
   strategy, but that strategy ran 25 coins in parallel; one coin cannot afford
   the frequency. This is a universe-size effect, not a defect in the gate.
7. **Wider stops are better, monotonically.** avgR rose at every step up to the
   1.5 grid edge. Batch 4 pushes past it.
8. **60% net-win is reachable and it is a plateau, not a spike.** The top six
   configs by win_net all sit at 59.7–62.5% across neighbouring `wt2` and
   `pivot` values, which is what a real effect looks like.
9. **But win_3R% is only ~23%.** The 62.5% headline comes from booking half at
   1R. Under the strict "reach 1:3" reading the rate is 23%, and the best strict
   number anywhere in 1008 runs is 33.3% at a fixed 3R.
10. **OOS is 5 trades.** It says nothing yet, in either direction.

---

## Batch 3 — 1h capitulation grid (864 runs)

Same dials as batch 2 plus an ATR-percentile volatility floor. 420 of 864 cleared
the sample floor — 1h has far more signals than 4h, so filters are affordable.

**Best by expectancy — and this is the best strict-3R result found anywhere**

| config | n | /yr | win_net% | **win_3R%** | avgR | PF | maxDD_R | OOS n | OOS win% |
|---|---|---|---|---|---|---|---|---|---|
| wt2≤−45, atr×1, piv5, **eth1d gate**, fix 3R | 82 | 13.8 | 40.2 | **40.2** | +0.521 | 1.80 | 12.9 | 9 | 55.6 |
| wt2≤−50, atr×1, piv4, eth1d gate, fix 3R | 73 | 12.3 | 41.1 | 38.4 | +0.514 | 1.78 | 12.8 | 10 | 60.0 |
| wt2≤−55, atr×1, piv4, eth1d gate, fix 3R | 60 | 10.1 | 41.7 | 38.3 | +0.531 | 1.81 | 8.8 | 8 | 50.0 |

**Marginal analysis**

| dial | trend | verdict |
|---|---|---|
| `gate` | **eth1d: +0.115** · btc1d: +0.030 · nogate: **−0.170** | the largest single effect in the whole study |
| `vol` floor | None: +0.052 · 0.5: −0.116 · 0.7: −0.243 | actively harmful, dropped |
| `pivot` | 3: −0.128 · **4: +0.010** · 5: −0.021 | wider pivots beat 3 on 1h |
| `atr_mult` | 0.5: −0.086 · **1.0: −0.016** · 1.5: −0.054 | shallow optimum near 1.0 |

**Findings**

11. **The gate result inverts between timeframes.** On 4h every gate starved the
    signal; on 1h the ETH daily gate is the strongest dial there is, worth
    +0.29R against ungated. The difference is signal supply: 1h produces enough
    candidates to pay for a filter, 4h does not. Batch 2's finding 6 was a
    frequency constraint, not a statement about gates.
12. **ETH's own daily regime beats BTC's** (+0.115 vs +0.030) for trading ETH.
    The repo's daily strategy uses the BTC gate because it trades 25 alts; for a
    single coin its own trend is the better filter.
13. **The volatility floor is an anti-filter.** Every threshold made things
    worse. Capitulation setups happen *in* high volatility; screening for it
    again just removes trades that already passed.

---

## Batch 4 — wide stops and exit shapes, 4h (840 runs)

**Best by net-win rate — the whole top of the table is one exit shape**

| config | n | /yr | win_net% | win_3R% | avgR | PF | maxDD_R | IS win% |
|---|---|---|---|---|---|---|---|---|
| wt2≤−45, atr×2, piv3, **G075** | 47 | 7.9 | **72.3** | 14.9 | +0.239 | 1.84 | 5.1 | 76.2 |
| wt2≤−45, atr×1.5, piv2, G075 | 54 | 9.1 | **72.2** | 16.7 | +0.235 | 1.83 | 5.8 | 76.0 |
| wt2≤−50, atr×3, piv3, G075 | 43 | 7.3 | **72.1** | 11.6 | +0.213 | 1.83 | 4.1 | 74.4 |
| wt2≤−40, atr×1.5, piv2, G075 | 60 | 10.1 | **71.7** | 18.3 | +0.263 | 1.90 | 5.8 | 74.5 |

`G075` = book half at +0.75R, stop to breakeven, runner to +3R.

**Best by expectancy**

| config | n | win_net% | win_3R% | avgR | PF |
|---|---|---|---|---|---|
| wt2≤−40, atr×2, piv3, fix 3R | 56 | 41.1 | 32.1 | **+0.487** | 1.84 |

**Findings**

14. **The stop-width optimum is bracketed now.** Extending past 1.5 made things
    worse at every step (1.5: +0.220 → 4.0: +0.135). Batch 2's monotonic rise
    was the grid edge, not a trend. Optimum is **1.5–2.0 × ATR**.
15. **72% net-win is reachable on 4h, and it is a wide plateau** — the top nine
    configs are all 70.2–72.3% across different `wt2`, `atr_mult` and `pivot`
    values. That is a structural property of the exit shape, not a lucky cell.
16. **The win rate is bought with reward.** G075 lifts net-win to 72% but drops
    win_3R% to 12–18% and avgR to +0.24. The fixed 3R keeps +0.49R but wins 41%.
    You cannot have both; this is the same trade-off Iteration F documented.

---

## Freqtrade cross-check

The harness is only a screen. The batch-2 winner was rebuilt as a real freqtrade
strategy ([EthVmcScaleOut.py](../user_data/strategies/EthVmcScaleOut.py), with
partial exits via `adjust_trade_position`) and run on the same candles with 1h
detail fills.

| variant | harness win% | freqtrade win% | harness n | freqtrade n |
|---|---|---|---|---|
| G3 scale-out | 62.5 | **61.9** | 48 | 42 |
| fixed 3R | 39.6 | **41.5** | 48 | 41 |

Two independent engines within 2 points on both readings. The trade counts
differ because freqtrade is capped at one open ETH position and so drops
overlapping signals. **The harness is trustworthy.**

---

## Batch 5 — refined 1h gated grid (1120 runs)

Both gates × `wt2` −40…−55 × `atr_mult` 0.75…2.0 × `pivot` 4…7 × seven exit
shapes. **All 1120 cleared the sample floor** — 1h has the signal supply that 4h
lacks.

**Best strict 1:3 anywhere in the study**

| config | n | /yr | win_net% | **win_3R%** | avgR | PF | maxDD_R | OOS n | OOS win% |
|---|---|---|---|---|---|---|---|---|---|
| wt2≤−50, atr×0.75, piv4, btc1d, fix 3R | 83 | 14.0 | 42.2 | **41.0** | **+0.574** | 1.90 | 6.0 | 9 | 55.6 |
| wt2≤−50, atr×0.75, piv4, eth1d, fix 3R | 70 | 11.8 | 41.4 | 40.0 | +0.540 | 1.84 | 8.1 | 10 | 60.0 |
| wt2≤−45, atr×0.75, piv4, btc1d, fix 3R | 104 | 17.6 | 40.4 | 39.4 | +0.506 | 1.77 | 7.0 | 11 | 54.5 |

**Best all-round — high net-win AND real expectancy AND frequency**

| config | n | /yr | win_net% | win_3R% | avgR | PF | maxDD_R | OOS n | OOS win% |
|---|---|---|---|---|---|---|---|---|---|
| wt2≤−50, atr×2, piv4, **eth1d**, **G075** | 71 | 12.0 | **67.6** | 26.8 | **+0.300** | 1.86 | 9.0 | 10 | **80.0** |

**Findings**

17. **The 1h gated entry beats the 4h one on every axis that matters.** 12–14
    trades/year against 8, higher expectancy (+0.30 vs +0.24R), and the only
    config in the study with a double-digit OOS sample that held up (10 trades,
    80%). The 4h G075 wins on headline net-win (72.3%) but trades less than
    two-thirds as often and earns less per trade.
18. **`pivot` 4–5 clearly beats 6–7** (+0.198/+0.200 vs +0.105/+0.144). Wider
    pivots are not automatically better; there is a genuine optimum at 4–5 on 1h.
19. **`atr_mult` is U-shaped** (0.75: +0.172, 1.25: +0.122, 2.0: +0.207), which
    is a warning sign, not a finding. A real dial trends. This one says stop
    width barely matters on 1h once the gate is on, and the ends are noise.
    Do not tune it finely.

---

## Freqtrade cross-check, round 2

| variant | harness | freqtrade | harness n | freqtrade n |
|---|---|---|---|---|
| 1h gated, G075 scale-out | 67.6% | **65.6%** | 71 | 64 |
| 1h gated, fixed 3R | 42.2% | **39.2%** | 83 | 79 |
| 4h ungated, G3 scale-out | 62.5% | **61.9%** | 48 | 42 |
| 4h ungated, fixed 3R | 39.6% | **41.5%** | 48 | 41 |

Four comparisons, all within 3 points. Two independent engines, same answer.

---

# VERDICT

**3832 configurations tested across five batches.**

### The target is met on the net-win reading

| strategy | tf | n | /yr | **win_net%** | avgR | PF | maxDD | freqtrade |
|---|---|---|---|---|---|---|---|---|
| **Eth1hVmcGated** (recommended) | 1h | 71 | 12.0 | **67.6** | +0.300 | 1.86 | 9.0R | 65.6% |
| Eth4h G075 | 4h | 47 | 7.9 | **72.3** | +0.239 | 1.84 | 5.1R | — |
| EthVmcScaleOut | 4h | 48 | 8.1 | 62.5 | +0.271 | 1.70 | 5.2R | 61.9% |

Entry: VMC bullish divergence on 1h, WT2 ≤ −50 at the pivot confirmed 4 bars
later, ETH daily regime not bear. Stop at pivot low − 2×ATR(14). Book half at
+0.75R, stop to breakeven, runner to +3R, 240-bar time stop. Risk 1% per trade.

### The target is NOT met on the strict reading

The best rate at which trades actually reach a clean 1:3 is **41.0%**, from
83 trades. Not one of 3832 configurations exceeded it. That is still a strong
strategy — 41% at 3R is +0.57R per trade, PF 1.90 — but it is not 60%.

### Why the strict reading tops out around 40%

60% of trades reaching 3R before a 1R stop is +1.4R per trade. Nothing in this
signal family comes near it, which is what the repo's own Iteration F predicted:
win rate and payoff trade off, and no exit structure can beat the entry's
own probability of reaching its first target. The G075 shape reaches 67.6% by
booking half the position at 0.75R — earlier and therefore likelier — while the
runner keeps the 1:3 tail. That is the honest way to have both numbers, and it
is what the recommended strategy does.

### What did not work

- **Blow-off fade on ETH alone** — −0.42R. Needs a basket of coins.
- **Regime gates on 4h** — starve a single-coin universe below n=40.
- **Volatility floor** — actively harmful at every threshold tested.
- **1h WT cross-up continuation** — −0.12R over 1198 trades, independently
  reproducing the repo's existing finding.
- **4h Bollinger reversion** — −0.35R.
- **Stops wider than ~2×ATR** — expectancy falls away steadily past 2.0.

### Honest caveats

- OOS is 9–11 trades on the best configs. Encouraging (55–80%) but not proof.
- 3832 configurations is a lot of searching. The guards used were a hard n ≥ 40
  floor, marginal analysis per dial, and neighbour scoring — every headline
  config sits on a plateau, not a spike. That reduces overfitting risk; it does
  not eliminate it.
- One coin, one venue, ~5.9 years covering roughly two full cycles.
- Next honest step is forward paper trading, not more optimisation.


---

# PHASE 2 — the frequency brief

Brief updated: 12 trades a year is not tradeable. Minimise drawdown, keep hard
stops, go out of the way to make it short-term tradeable. New selection floor:
**>= 40 trades/year**, and results are now ranked by **R/DD** (total R earned per
unit of peak drawdown) rather than raw expectancy. Two new metrics: `R/DD` and
`worst_streak`, the longest run of consecutive losers.

## Batch 6 — six high-frequency families (144 runs)

Divergence entries need a confirmed pivot PAIR, which is why they cap at 12-18
trades/year. These fire on single-bar conditions instead.

| config | n | /yr | win_net% | avgR | PF | maxDD_R | **R/DD** | streak | OOS n | OOS win% |
|---|---|---|---|---|---|---|---|---|---|---|
| donchian_break 4h, eth1d, fix3R | 471 | 79.4 | 33.1 | +0.228 | 1.33 | 44.6 | **2.40** | 29 | 43 | 23.3 |
| **ema_pullback 4h, eth1d, G05** | 495 | 83.5 | **68.7** | +0.078 | 1.25 | **21.8** | **1.77** | 13 | **78** | **62.8** |
| ema_pullback 4h, eth1d, G3 | 495 | 83.5 | 54.5 | +0.128 | 1.28 | 36.3 | 1.74 | 20 | 78 | 48.7 |
| ema_pullback 4h, **nogate**, G3 | 559 | 94.3 | 53.0 | +0.096 | 1.21 | **60.1** | 1.21 | — | 78 | 48.7 |

**Findings**

20. **Frequency is solved.** The EMA pullback runs 83 trades/year against the
    divergence strategy's 12, and it is the first configuration in this study
    with a properly sized out-of-sample window: **78 OOS trades at 62.8%**.
21. **The daily gate is a drawdown tool, not just an edge tool.** Same entry,
    same exit: 60.1R drawdown ungated, 21.8R gated. It nearly cuts the pain in
    three. This is the single most effective drawdown control found.
22. **Donchian scores best on R/DD but is untradeable.** A 29-trade losing
    streak, and its OOS win rate collapses from 33% to 23%. R/DD alone is not a
    sufficient ranking metric; `worst_streak` has to be read next to it.
23. **Frequency was bought with quality.** avgR fell from +0.30 (divergence) to
    +0.078. 83 trades a year at +0.078R is +6.5R/year — better than 12 trades at
    +0.30R (+3.6R/year), but the drawdown is far worse.

---

## Batch 7 — ABLATION of the trader's own setup (768 runs)

The observed setup: on 4h, oscillator resets and crosses up from below, RSI
under 30 and turning up, overall trend up. Divergence makes it stronger. Expect
a 2-3% move. Mirror for shorts.

**Correction made while building it.** Reading "overall trend is up" as a
same-chart EMA200 filter produced **n=1 in six years** — on 4h, price above its
own EMA200 and RSI under 30 are near-contradictory. The higher-timeframe daily
regime is the correct reading, so the trend condition is applied as the daily
gate.

**Does each condition earn its place?** Matched pairs: identical configs with
exactly one condition switched.

| condition | matched pairs | median avgR with | without | **contribution** | n with | n without |
|---|---|---|---|---|---|---|
| stochastic cross | 160 | −0.156 | −0.183 | **+0.027** | 150 | 576 |
| RSI threshold | 160 | −0.156 | −0.170 | **+0.014** | 150 | 1135 |
| **VMC divergence** | 8 | −0.191 | −0.098 | **+0.093** | 866 | 50 |

**The trader's instincts check out directionally.** Every condition contributes
positively, and the one flagged as "even more a good buying signal" — the
divergence — contributes more than the stochastic cross and the RSI filter put
together. It is also the most expensive: it cuts the sample from 866 to 50.

**Best full-bundle configurations**

| config | n | /yr | win_net% | hit_tgt% | avgR | PF | maxDD_R | OOS n |
|---|---|---|---|---|---|---|---|---|
| 4h long, rsi30, st30, no gate, fix 3R | 31 | 5.2 | 35.5 | 25.8 | **+0.255** | 1.38 | 9.3 | 1 |
| 4h short, rsi40, st20, eth1d, fix 3R | 44 | 7.4 | 31.8 | 31.8 | +0.229 | 1.32 | 8.7 | 4 |
| **4h long, rsi30, st20, no gate, 3% target** | 31 | 5.2 | **71.0** | **71.0** | +0.119 | 1.40 | **3.5** | 1 |
| 4h long, rsi35, st20, no gate, fix 3R | 73 | 12.3 | 31.5 | 26.0 | +0.154 | 1.22 | 7.6 | 4 |

**Findings**

24. **The 2-3% observation is measurably correct.** The tight version of the
    setup wins **71% of the time** going for a 3% move, with a 3.5R drawdown —
    the lowest of anything tested. The observation was accurate.
25. **But it fires 5 times a year.** The tight bundle that produces 71% is rare.
    Loosening the thresholds to get frequency drives expectancy negative: the
    family's median avgR across all 768 runs is **−0.156**.
26. **The 2-3% target loses money in general** (pct2 −0.174, pct3 −0.169 vs
    fix3R −0.124 median avgR). It wins often, but the stop is wider than the
    target in most configurations, so the rare losses outweigh the frequent
    small wins. High win rate, negative expectancy — the classic trap.
27. **4h beats 1h decisively for this setup** (median avgR −0.080 vs −0.194).
    The trader's choice of 4h was right.
28. **Long and short are near-identical** (−0.170 vs −0.159). The mirror works;
    there is no long-only bias in this setup.

---

## Batch 8 — the reset filters on a high-frequency trigger (720 runs)

Batch 6 gave frequency without quality. Batch 7 gave quality without frequency.
This bolts the trader's reset conditions onto the EMA pullback.

A modelling correction went in first: the trader describes a **sequence**
(reset, then cross, then turn up), and demanding all of it on one candle gives
n=0. Each reset condition may now be satisfied anywhere in the last `within`
bars, with only "RSI turning up" required on the trigger bar itself.

**The headline comparison — the same entry, with and without the stochastic cross**

| | without cross | **with the trader's cross** |
|---|---|---|
| trades/year | 115.3 | **48.6** |
| win_net% | 35.1 | **37.5** |
| avgR | +0.255 | **+0.285** |
| PF | 1.39 | **1.46** |
| max drawdown | 68.6R | **40.5R** |
| **worst losing streak** | **38** | **15** |
| OOS n | 97 | 35 |
| OOS win% | 44.3 | **51.4** |

**Full ranking by R/DD**

| config | n | /yr | win_net% | avgR | PF | maxDD_R | R/DD | streak | OOS n | OOS win% |
|---|---|---|---|---|---|---|---|---|---|---|
| 4h ema20, no cross, eth1d, fix 3R | 684 | 115.3 | 35.1 | +0.255 | 1.39 | 68.6 | **2.54** | 38 | 97 | 44.3 |
| **4h ema20, cross, eth1d, fix 3R** | 288 | 48.6 | 37.5 | **+0.285** | 1.46 | 40.5 | **2.03** | **15** | 35 | 51.4 |
| 4h ema50, no cross, eth1d, fix 3R | 377 | 63.6 | 33.7 | +0.191 | 1.29 | 46.7 | 1.54 | 39 | 58 | 39.7 |
| 1h ema20, sto30, cross, rsi45, eth1d, fix 3R | 239 | 40.3 | 33.5 | +0.213 | 1.31 | 51.6 | 0.99 | 16 | 33 | 51.5 |
| 4h ema50, no cross, eth1d, G05 | 377 | 63.6 | **66.8** | +0.059 | 1.18 | **23.9** | 0.93 | **11** | 58 | **69.0** |

**Findings**

29. **The trader's stochastic cross is primarily a DRAWDOWN tool.** It was
    pitched as an entry-quality filter, and it does raise expectancy — but the
    bigger effect is that it halves peak drawdown (68.6R → 40.5R) and cuts the
    worst losing streak from 38 to 15. Against a brief that names drawdown as
    the thing to minimise, this is the most valuable single filter found in
    phase 2. It costs a little over half the trades.
30. **The stochastic cross also improves out-of-sample behaviour** (44.3% →
    51.4%), which is what a real filter does rather than a curve-fit one.
31. **Scale-out does not work on this entry.** Rows 9-10 of the raw batch: the
    same config with G05 cuts drawdown to 21.8R but collapses expectancy to
    +0.01R. This entry needs the full 3R run to pay; the divergence entry did
    not. Exit shape is not transferable between entry types.
32. **R/DD alone is a misleading ranking.** The no-cross config ranks first on
    R/DD (2.54) while carrying a 38-trade losing streak. No one trades through
    that. `worst_streak` has to be read alongside it.
33. **Frequency and drawdown trade against each other directly.** 115/yr costs
    68.6R of drawdown; 49/yr costs 40.5R; 12/yr (phase 1) cost 9R. There is no
    configuration in 4600+ runs that is simultaneously frequent, low-drawdown
    and high-expectancy.

---

## Batch 9 — drawdown refinement (640 runs)

Sweeps the batch-8 leader on stop width, swing lookback, reset lag, EMA length,
gate and target.

**Two dials turned out to be real, and one killed a whole side of the book**

| dial | median avgR / maxDD / streak | verdict |
|---|---|---|
| `within` (reset lag) | **2: +0.119 / 28R / 14** · 5: +0.072 / 59R / 28 | the drawdown lever — halves DD and streak |
| `atr_mult` | 0.5: +0.003 · 1: +0.076 · 1.5: +0.127 · **2: +0.181** | monotonic, wider stop better |
| `side` | **long: +0.220** · short: **−0.003** | the short mirror has no edge on this entry |
| `ema` | 20: +0.100 / 45R · 34: +0.089 / **34R** | 34 trades less, hurts less |
| `gate` | btc1d: +0.098 · eth1d: +0.095 | indistinguishable now |
| `target` | fix3R: +0.179 / streak 25 · G1: +0.032 / **streak 14** | expectancy vs streak, pick one |

**Findings**

34. **Requiring the reset to be RECENT is the drawdown fix.** Allowing the
    stochastic cross to be up to 5 bars stale doubles drawdown (28R → 59R) and
    doubles the worst losing streak (14 → 28). Two bars is the setting. This is
    the trader's own "and THEN it tries to go up" — the sequence has to be
    tight, and the data agrees emphatically.
35. **The short side is dead on this entry** (−0.003R vs +0.220R). The mirror
    worked for the pure stoch/RSI setup in batch 7; it does not survive on the
    pullback trigger.

---

# THE FREQUENCY CEILING — a correction that changes the answer

The freqtrade cross-check of the batch-9 leader disagreed with the harness on
trade count by 4x: harness 46/year, freqtrade 12.3/year. The harness was wrong,
and the reason matters more than the strategy.

**The harness simulates every signal independently.** It assumed you could hold
many overlapping ETH longs at once. On one pair with one position you cannot.

Measured directly on the leading config, 2021 onward:

| | |
|---|---|
| signals the entry fires | 255 |
| dropped because a position was already open | **186** |
| actually takeable, one at a time | **69** (12.2/yr) |

Freqtrade independently arrived at 70 trades. The two engines agree once the
harness is asked the same question.

**Every trades/year figure in batches 6, 8 and 9 above is inflated for this
reason.** The win rates, expectancy and R/DD are sound — they are per-trade
measures — but the frequency column assumed overlapping positions.

**The one-position-at-a-time numbers are better on drawdown, not worse:**

| | overlapping (harness) | sequential (real) |
|---|---|---|
| trades/year | 46.0 | **12.2** |
| win_net% | 45.4 | 43.5 |
| avgR | +0.513 | +0.253 |
| **max drawdown** | 20.4R | **7.4R** |
| **worst streak** | 14 | **6** |

Overlapping positions compound drawdown, because correlated ETH longs lose
together. Taking one at a time nearly triples the drawdown efficiency.

## Freqtrade cross-check, round 3

| variant | trades | /yr | win% | total profit | max DD | avg hold |
|---|---|---|---|---|---|---|
| **Eth4hPullback** (3R) | 70 | 12.3 | 42.9 | +17.02% | **9.72%** | 10.0 d |
| Eth4hPullbackLowDD (1R+3R) | 106 | 18.7 | 49.1 | +9.79% | 15.57% | **4.1 d** |

---

# WHERE PHASE 2 LANDS

**Drawdown: solved.** 9.72% at 1% risk, worst losing streak 6, against 40R
(≈40%) before batch 9. The two things that did it were the daily gate and
requiring the reset within 2 bars.

**Frequency: structurally capped, not solved.** On one coin holding one
position, average hold time sets the ceiling:

| avg hold | max trades/year | measured |
|---|---|---|
| 10 days (3R target) | ~36 | **12.3** |
| 4 days (1R+3R) | ~90 | **18.7** |

Signal clustering eats the rest. **No entry filter can raise this** — only
shorter holds, a shorter timeframe, or more coins can.

Three honest routes past it, none of them free:

1. **Shorter holds.** The LowDD variant already gets 18.7/yr by exiting at 4
   days instead of 10. It costs expectancy (+0.16%/trade vs +1.80%).
2. **Drop to 15m.** Data is downloaded. Holds shrink, trade count rises, but
   costs (0.3% round trip) eat a larger share of every move.
3. **More coins.** The single most effective option, and the one the repo's own
   daily strategy already uses — but the brief says ETH/USDT.

**Caveat on the leaders.** The best in-sample config (btc1d gate, ATR×2, fixed
3R) scores 31.6% over 19 out-of-sample trades; the best out-of-sample config
(eth1d gate, ATR×0.5, book half at 1R) scores 66.7% over 33. They are not the
same configuration. That gap is unresolved and is the first thing to settle.


---

# PHASE 3 — the multi-coin test, and what it proved

The plan was to lift returns by running the ETH strategies over the repo's
29-coin universe, on the reasoning that more coins buys more independent bets.
Projected 17% CAGR. **That projection was wrong, and the way it was wrong is the
most important result in this whole study.**

29 coins, 2021-01 to 2026-09, 1% risk per trade, 0.15% costs per side, 4h
signals with 1h detail fills, position limit swept at 3 / 6 / 10.

| strategy | designed on | trades | win% | total | CAGR | max DD |
|---|---|---|---|---|---|---|
| **VmcCapitulation** (daily, 1.5R) | **29-coin basket** | 65 | 60.0 | **+39.55%** | **+6.05%** | **9.96%** |
| VmcCapitulation1R (daily) | 29-coin basket | 65 | 66.2 | +24.31% | +3.91% | 8.58% |
| Multi4hPullbackBtcGate | ETH only | 393 | 31.0 | −9.95% | −1.83% | 45.39% |
| EthVmcFixed3R | ETH only | 539 | 26.9 | −16.89% | −3.21% | 48.52% |
| EthVmcScaleOut | ETH only | 589 | 42.1 | −30.68% | −6.26% | 44.23% |
| Multi4hPullback | ETH only | 453 | 30.5 | −35.55% | −7.45% | 59.26% |

Raising the position limit from 3 to 10 made the ETH-derived strategies worse,
not better — drawdowns reached 83%.

## Finding 36 — the ETH strategies were overfit, and this is the proof

Every strategy tuned on ETH **loses money** on the other 28 coins, with
drawdowns of 44-83%. The one strategy designed on a basket from the start
returns +39.55% with a 9.96% drawdown on the same data, same engine, same costs.

This is a clean natural experiment. The difference is not the signal family —
`VmcCapitulation` and `EthVmcScaleOut` use the *same* VMC divergence entry. The
difference is what they were fitted to.

Phases 1 and 2 searched roughly 5,300 configurations against one coin. The
guards used — n ≥ 40 floors, marginal analysis, neighbour scoring, an
independent freqtrade cross-check, out-of-sample splits — were enough to catch
noise *within* ETH. **None of them could catch the fact that the whole search
was fitted to ETH.** Out-of-sample in time is not out-of-sample in instrument.

The 6.55% CAGR reported for `EthVmcFixed3R` on ETH should now be read as an
upper bound produced by selection, not a forecast.

## Finding 37 — more coins did not multiply returns

The reasoning behind the 17% projection was that 29 coins gives roughly 4
independent bets. In practice, on the strategy that does work, going from 3 to
10 concurrent positions moved the total from +21.36% to +39.55% while drawdown
rose from 7.59% to 9.96%. Real, but a long way from 4x, because crypto
alts fall together.

## Where this leaves the numbers

Every honest measurement in this project lands in the same place:

| strategy | scope | CAGR at 1% risk | max DD |
|---|---|---|---|
| VmcCapitulation daily | 29 coins | 6.05% | 9.96% |
| EthVmcFixed3R | ETH only (likely overfit) | 6.55% | 6.13% |
| EthVmcScaleOut | ETH only (likely overfit) | 5.55% | 3.21% |

**5-6.5% CAGR at 1% risk is the measured ceiling**, and the only strategy that
has survived an instrument-level out-of-sample test is the repo's own
pre-existing `VmcCapitulation` from STRATEGY_RESEARCH.md. Nothing built in
phases 1 or 2 beat it.

The only remaining lever is risk per trade, which scales return and drawdown
together:

| risk/trade | CAGR | on 1 lac | worst drawdown |
|---|---|---|---|
| 1% | 6.1% | ₹6,054 | −₹9,960 |
| 2% | 10.8% | ₹10,825 | −₹19,920 |
| 3% | 14.8% | ₹14,794 | −₹29,880 |
| 5% | 21.2% | ₹21,219 | −₹49,800 |

## What should happen next

Not more optimisation. The lesson of finding 36 is that more searching against
fixed history produces better backtests and no better strategies. The two
things that would actually add information:

1. **Forward paper trading** of `VmcCapitulation` on the 29-coin basket. It is
   the only candidate with an instrument-level out-of-sample result.
2. **Instrument-level validation built into the workflow** — any future search
   should fit on one subset of coins and test on a held-out subset, not just
   split by date.


---

# PHASE 4 — the impulse / pullback / divergent double bottom

The trader supplied an ARB/USDT 15m chart of a setup they trade: a large run
up, a pullback, a VMC bullish divergence, then a retrace that forms a DOUBLE
BOTTOM, with the second bottom as the entry. Reported as high accuracy and high
reward:risk.

Coded in [pattern.py](pattern.py) as `impulse_double_bottom`. The neat property
is that the divergence and the double bottom are the *same two points*: two
price lows at roughly equal levels with the oscillator making a higher low
between them. So it is one object, detectable in one pass. Signals are emitted
on the bar that confirms the second low, so nothing looks forward.

**This is the first phase validated on HELD-OUT COINS**, per finding 36. Eight
coins to fit on (BTC, ETH, ADA, DOGE, LINK, DOT, ATOM, XLM), eight the search
never sees (BNB, XRP, SOL, AVAX, LTC, ETC, NEAR, UNI).

## The ETH-only result, which looked promising

| tf | selectivity | signals/yr | win% | avgR | PF |
|---|---|---|---|---|---|
| 15m | loose | 1364 | 27.4 | −0.189 | 0.76 |
| 15m | strict | 4 | 21.7 | −0.407 | 0.48 |
| 1h | loose | 473 | 27.9 | −0.051 | 0.93 |
| 4h | loose | 83 | 29.3 | +0.086 | 1.12 |
| 4h | mid | 20 | 32.8 | +0.205 | 1.30 |
| **4h** | **strict** | **4** | **39.1** | **+0.440** | **1.70** |

On ETH the pattern looked real on 4h and improved monotonically with
selectivity — the signature of a genuine effect.

## Finding 38 — why 15m cannot work, whatever the pattern

| timeframe | median 1R | round-trip cost | **cost as share of 1R** |
|---|---|---|---|
| 15m | 1.71% | 0.30% | **18%** |
| 1h | 2.34% | 0.30% | 13% |
| 4h | 3.53% | 0.30% | **9%** |

At zero cost the 15m version scores −0.029R — essentially breakeven. Real fees
take it to −0.213R. **The pattern is not wrong on 15m; the stop is simply too
close for the fee to be survivable.** This applies to any 15m strategy stopping
~1.7% away, not just this one.

## Finding 39 — it does not survive held-out coins, at any setting

52 configurations across three timeframes, three selectivity levels, divergence
on and off, gated and ungated, two exit shapes.

| | |
|---|---|
| positive on the FIT coins | 3 of 52 |
| positive on the HELD-OUT coins | 2 of 52 |
| **positive on BOTH** | **0 of 52** |
| **correlation, FIT avgR vs HOLDOUT avgR** | **−0.01** |

A correlation of −0.01 is the whole result. Tuning this pattern on one basket
carries **zero** information about another basket. The two configs that scored
positive on holdout were the two *worst* on fit (−0.384R, −0.497R), which is
what sign-flipping noise looks like, not an edge.

The ETH 4h strict result (+0.440R) did not survive. Its nearest multi-coin
equivalent scored +0.203R on fit and **−0.288R** on holdout.

| median HOLDOUT avgR | |
|---|---|
| 15m | −0.198 |
| 1h | −0.145 |
| 4h | −0.212 |
| with divergence | −0.186 |
| without divergence | −0.150 |

The divergence made results slightly *worse* here, contradicting the phase-2
ETH-only finding where it was the strongest single condition. That reversal is
itself evidence for finding 36.

## What phase 4 establishes

1. The held-out-coin protocol works, and it is cheap. It killed in one run a
   pattern that three separate ETH-only analyses would have endorsed.
2. Short timeframes carry a structural cost penalty that is independent of the
   signal. 18% of every R on 15m is not recoverable by better entries.
3. A pattern being genuinely present on a chart, and being mechanically
   tradeable after costs across instruments, are different claims. The first
   can be true while the second is false.

Running tally across the whole project: **0 strategies developed in phases
1-4 have survived an instrument-level out-of-sample test.** The only one that
has is `VmcCapitulation`, which predates all of it.


---

# PHASE 5 — breach tolerance, and a lookahead trap worth remembering

The live scanner voids a bull divergence the moment price trades below the pivot
low that formed it. Four live cases breached by under 1%, and a breach that
shallow is arguably the *second low of a double bottom* rather than an
invalidation. Testable, so [breach_test.py](breach_test.py) tests it.

Every confirmed divergence goes into one bucket:

| bucket | entry | uses future information? |
|---|---|---|
| ALL | confirmation bar | no — the honest baseline |
| CLEAN | confirmation bar, *if* no breach followed | **YES — not tradeable** |
| SHALLOW | on the reclaim after a breach <= tol | no |
| DEEP | on the break, breach > tol | no |

## Results, 29 coins

**4h**

| bucket | n | win% | avgR | PF | maxDD_R | coins positive |
|---|---|---|---|---|---|---|
| ALL | 1922 | 24.8 | −0.135 | 0.83 | 276.3 | 7/29 |
| CLEAN *(lookahead)* | 713 | 43.5 | *+0.516* | *1.91* | *10.1* | *28/29* |
| SHALLOW | 584 | 21.9 | **−0.196** | 0.76 | 124.0 | 9/29 |
| DEEP | 643 | 21.9 | **−0.204** | 0.75 | 167.1 | 7/29 |

**1h**

| bucket | n | win% | avgR | PF | coins positive |
|---|---|---|---|---|---|
| ALL | 4952 | 25.8 | −0.195 | 0.75 | 0/16 |
| CLEAN *(lookahead)* | 1476 | 53.7 | *+0.709* | *2.59* | *16/16* |
| SHALLOW | 2339 | 23.1 | **−0.242** | 0.71 | 0/16 |
| DEEP | 1073 | 27.9 | **−0.045** | 0.94 | 6/16 |

## Finding 40 — shallow breaches are not better, so the strict rule stays

On 4h, shallow (−0.196R) and deep (−0.204R) are indistinguishable. On 1h,
shallow is *worse* (−0.242R vs −0.045R). There is no timeframe where waiting for
a shallow dip and buying the reclaim beats simply discarding the signal.

The double-bottom reading of a shallow breach is intuitive and wrong. A break is
a break. The scanner keeps voiding all of them; `MARGINAL_BREACH` now reports
breach depth as context (`marg 30b (-0.1%)`) but never promotes a marginal break
to an active signal.

## Finding 41 — measure the size of your own lookahead traps

The CLEAN bucket is the same population as ALL minus the trades that later went
against it. It scores **+0.516R on 4h and +0.709R on 1h, positive on 28/29 and
16/16 coins** — the strongest, broadest, most convincing-looking result anywhere
in this project. It is entirely an artefact. The classification reads bars that
sit *after* the entry it labels.

The illusion is worth **+0.65R on 4h and +0.90R on 1h** against the honest
baseline. That is the scale of what a single innocuous-looking filter can
manufacture. Anything in this project reporting better than roughly +0.5R with
near-universal per-coin agreement should be assumed contaminated until the
entry-versus-information ordering has been checked by hand.

Worth noting what did *not* catch it: freqtrade's `lookahead-analysis` was never
run on this, the held-out-coin protocol would have passed it (the bias is
present in every coin equally), and the per-coin agreement made it look more
trustworthy, not less. Only reading the code caught it.


---

# PHASE 6 — the trader's five charts: structure break + volatile alts

Five 15m charts supplied (STX, S, SEI, DOT, TAO). All share a shape this project
had not been testing, and two things in them turned out to matter.

**1. The entry is the STRUCTURE BREAK, not the divergence.** Every chart shows
price breaking a trendline or the swing high that capped the pullback, and the
impulsive move happening after that break. Everything tested in phases 1-5
entered at the moment the divergence confirmed. Coded in
[breakout.py](breakout.py) as `divergence_breakout`, with the hand-drawn
trendline approximated two ways: break of the highest high since the pivot
("swing"), and break of a falling line fitted through those highs ("slope").
Both are functions of bars at or before the trigger.

**2. The coins are not large caps.** STX, SEI, TAO and S are volatile mid-caps.
Measured median 15m bar range:

| | median 15m range | cost as share of it |
|---|---|---|
| ENA / FET / TIA / TAO | 0.77-0.90% | ~35% |
| the alt median | ~0.68% | ~44% |
| ETH | 0.441% | 68% |
| BTC | 0.333% | 90% |

The alts move roughly twice as much per bar as BTC, which halves the relative
cost drag. Finding 38 said 15m cannot work because the stop is too close for the
fee; picking more volatile instruments is the direct attack on that.

## Finding 42 — both of the trader's additions are real, and they stack

25 alts, 13 fit / 12 held out, 15m, 3R target, matched comparison:

| entry trigger | money flow | FIT avgR | HOLDOUT avgR |
|---|---|---|---|
| at the divergence (phases 1-5) | off | −0.278 | −0.269 |
| at the divergence | green only | −0.218 | −0.251 |
| break the swing high | off | −0.233 | −0.226 |
| break the swing high | green only | −0.180 | −0.130 |
| break a falling line | off | −0.195 | −0.248 |
| **break a falling line** | **green only** | **−0.094** | −0.183 |

Waiting for the break is worth roughly +0.05R, the money-flow filter another
+0.10R, and they compose. Both improve fit and holdout together, which is what a
real effect looks like. But on 15m the combination only halves the loss.

## Finding 43 — the same setup on 1h is the first positive held-out result

| tf | median 1R | cost/R | FIT avgR | HOLDOUT avgR | PF | holdout coins positive |
|---|---|---|---|---|---|---|
| 15m | 2.30% | 13% | −0.094 | −0.183 | 0.76 | 1/12 |
| **1h** | **5.18%** | **6%** | **+0.035** | **+0.049** | **1.07** | **6/9** |

Positive on both baskets, on the majority of held-out coins, for the first time
in this project. The mechanism is the cost ratio: the same setup on a 5.18% stop
survives a fee that a 2.30% stop does not.

## Finding 44 — but the dials do not form a plateau, so this is not tradeable yet

Sweeping on FIT and reading HOLDOUT:

| wt2 <= | atr_mult | FIT avgR | HOLDOUT avgR |
|---|---|---|---|
| −40 | 0.5 | +0.027 | −0.005 |
| −40 | 1.0 | +0.035 | **+0.049** |
| −40 | 2.0 | +0.060 | +0.015 |
| −50 | 0.5 | +0.065 | −0.033 |
| **−50** | **1.0** | **+0.082** | **+0.093** |
| −50 | 2.0 | +0.033 | −0.019 |

The best cell on FIT is also the best on HOLDOUT (+0.093R, PF 1.13, 6/8 coins) —
the first time fit has predicted holdout here. But its immediate neighbours flip
negative: atr 0.5 gives −0.033 and atr 2.0 gives −0.019 against +0.093 in
between. That is a ridge, not a plateau, and finding 8 says a real effect looks
like the latter.

**Status: promising, not proven.** The two structural additions are supported by
matched comparisons across both baskets. The specific parameter choice is not.
An honest reading of the family is "around breakeven on 1h alts, with a real
mechanism behind the improvement".

4h on this universe is untested — these alts only have history from 2023, and no
4h configuration cleared the n>=60 floor.

---

# PHASE 7 — the campaign, and the strategy that came out of it

Free hand to improvise. Method: only ingredients that already survived a
held-out-coin test were allowed in without re-litigating, everything else had to
earn its place. Universe expanded to 76 coins, split by hashing the coin name so
fit/holdout membership carries no market-cap, listing-age or sector information.

## A harness bug found first, and it mattered

The opening run reported +2.021R average on a 3R-capped strategy with a 28.9%
win rate. The arithmetic maximum there is about +0.16R, so it was wrong.

Cause: 8 of the first 24 coins have 1h history from 2020 but 15m detail only
from 2024. `simulate()` used `searchsorted`, which silently returns position 0
for a timestamp before the detail starts — pricing a 2021 entry against 2024
candles. `simulate()` now refuses any signal outside the detail coverage.
Earlier phases are unaffected, because their detail and signal frames were
downloaded over matching ranges.

## Finding 45 — the supported ingredients compose, monotonically

1h, 76 coins, on the HELD-OUT half:

| stack | avgR | PF | maxDD_R | coins positive |
|---|---|---|---|---|
| bare divergence | −0.168 | 0.79 | 826.0 | 1/36 |
| + structure break | −0.097 | 0.87 | 317.4 | 10/36 |
| + money flow green | −0.086 | 0.88 | 83.4 | 13/34 |
| + daily regime gate | **−0.002** | **1.00** | **39.1** | 8/19 |

Every ingredient improves the held-out number, and drawdown falls 826R → 39R.
But the stack tops out at breakeven on 1h.

## Finding 46 — market breadth is not a filter

The hypothesis was that a divergence printing while 60% of the universe is
oversold is a different event from one printing while 5% is — either a washout
to buy or a knife to avoid. Breadth is strongly clustered (median 4% of the
universe oversold, 90th percentile 64.7%), so the question was real.

| breadth bucket | FIT avgR | HOLDOUT avgR |
|---|---|---|
| LOW | +0.029 | −0.097 |
| MID | −0.171 | −0.178 |
| HIGH | +0.096 | −0.197 |

Neither. No bucket is positive out of sample, and HIGH flips sign between the
two baskets. Rejected.

## Finding 47 — the exit was not the problem

| target | HOLDOUT avgR |
|---|---|
| 1R | −0.121 |
| 1.5R | −0.095 |
| 2R | −0.115 |
| 2.5R | −0.045 |
| **3R** | **−0.002** |
| scale-outs (4 shapes) | −0.094 to −0.142 |

3R was already the best available. Shorter targets and every scale-out are
worse. The edge in this entry lives in the tail, not the body — so on 1h there
was nothing left to fix.

## Finding 48 — the same stack on DAILY works, at every setting

Every cost finding in this project points the same way, and the one strategy
that had ever survived a held-out test already lived on daily. So: same
ingredients, daily candles, 76 coins, history back to 2018.

| wt2 <= | trigger | FIT avgR | **HOLDOUT avgR** | PF | maxDD_R | coins + |
|---|---|---|---|---|---|---|
| −30 | none | +0.268 | **+0.133** | 1.19 | 29.2 | 11/24 |
| **−30** | **break** | +0.455 | **+0.342** | **1.54** | **6.7** | 4/4 |
| −40 | none | +0.315 | +0.030 | 1.04 | 31.6 | 6/19 |
| −40 | break | +0.574 | +0.266 | 1.41 | 6.7 | 4/4 |
| −50 | none | +0.429 | +0.149 | 1.22 | 12.3 | 5/9 |
| −50 | break | +0.804 | +0.301 | 1.48 | 4.1 | 1/2 |

**Every row is positive on held-out coins**, and the structure break improves
every single pairing while cutting drawdown from ~30R to ~6R. That is a plateau
across the `wt2` dial, not a ridge — the shape finding 8 says a real effect has.

## Freqtrade cross-check

[DailyDivBreakout.py](../user_data/strategies/DailyDivBreakout.py), independent
engine, 1h detail fills, 0.15% per side:

| coin set | trades | win% | profit | max DD |
|---|---|---|---|---|
| FIT (40 coins) | 64 | 37.5 | +25.21% | 11.52% |
| **HELD OUT (36 coins)** | **69** | **37.7** | **+32.94%** | **9.30%** |

Held out beat fit. Win rates match the harness within 2 points.

## The result

Full 76-coin universe, 2020-01 to 2026-09, 1% risk per trade, max 10 concurrent:

| | DailyDivBreakout | VmcCapitulation (previous best) |
|---|---|---|
| CAGR | **10.53%** | 5.12% |
| on 1 lac | **₹10,535/yr** | ₹5,115/yr |
| total | +95.24% | +39.55% |
| profit factor | **1.73** | 1.66 |
| win rate | 37.1% at 3R | 60% at 1.5R |
| max drawdown | **18.61%** | 9.96% |
| trades/year | 19.8 | 9.7 |

Roughly double the return of the previous best, at roughly double the drawdown.

## What is wrong with it

**2023 produced 69% of all profit.** Year by year, per lac: 2020 +14,010 ·
2021 −1,160 · 2022 −13,390 · **2023 +65,860** · 2024 +20,480 · 2025 −3,420 ·
2026 +12,850. Four up years, three down. A strategy that needs one exceptional
year to carry six is not the same thing as one that earns steadily, and the
held-out test does not protect against that — both baskets lived through 2023.

**Drawdown is 18.6% closed, 32.2% on balance.** Worse than the brief asked for.

**19.8 trades a year** is back to the frequency problem, because daily bars are
slow. The cost economics that make daily work are the same thing that makes it
infrequent.

## Standing position after seven phases

This is the first strategy developed here that is positive on coins it was never
tuned on, in two independent engines, at every parameter setting tested. That is
a real result and it is the one worth forward-testing.

It is not a solved problem. The honest next step is paper trading, not another
campaign — the profit concentration in 2023 is exactly the kind of thing that
only forward evidence can settle.

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

---

# STEP 3 — stacking TrendlineBreakout with DailyDivBreakout

Two books, one universe, different triggers, both positive on held-out coins.
Step 3 of the handover asked whether running them together raises the ratio.
[stack.py](stack.py) answers it. Sizing uses `tl_account.simulate_honest`, which
credits profit at exit, not `portfolio.py`.

## Finding 51 — the two books are NOT uncorrelated, and stacking does not help

The ratio `CAGR / maxDD` for every combination of coin set and slot limit.
Stacking has to beat the better single book to be worth running:

| coins | slots | trendline | divergence | **stacked** | verdict |
|---|---|---|---|---|---|
| FIT | 10 | 0.66 | 0.33 | **0.34** | worse |
| HOLDOUT | 10 | 1.04 | 0.62 | **1.15** | better |
| ALL | 10 | 0.87 | 0.47 | **0.64** | worse |
| FIT | 20 | 0.72 | 0.42 | **0.45** | worse |
| HOLDOUT | 20 | 0.98 | 0.54 | **0.79** | worse |
| ALL | 20 | 0.98 | 0.45 | **0.69** | worse |
| FIT | 40 | 0.46 | 0.42 | **0.48** | level |
| HOLDOUT | 40 | 0.82 | 0.54 | **0.82** | level |
| ALL | 40 | 0.88 | 0.47 | **0.57** | worse |

**One of nine comparisons favours stacking**, and it does not replicate: HOLDOUT
at 10 slots reads 1.15 against 1.04, then 0.79 against 0.98 at 20 slots and
level at 40. That is the signature of a lucky cell, and by this repo's own rule
a result that reverses when a dial moves is not a result.

**It is not slot contention.** That was the obvious alternative explanation — two
books competing for ten slots would look like this. Raising the cap to 20 and
then 40 does not rescue it, so the books are not merely crowding each other out.

## Finding 52 — they lose in the same years, which is why

| year | trendline | divergence | stacked |
|---|---|---|---|
| 2020 | +57,058 | +21,920 | +83,867 |
| 2021 | +7,097 | — | +8,309 |
| **2022** | **−23,130** | **−10,311** | **−31,170** |
| 2023 | +81,361 | +20,165 | +62,373 |
| 2024 | +82,613 | +13,035 | +97,916 |
| **2025** | **−31,721** | **−8,307** | **−47,287** |
| 2026 | +18,493 | +31,064 | +20,268 |

Both books lose in 2022 and in 2025. There is no year where one covers the
other, which is the whole thing a second book is supposed to buy. Contrast the
long+short work (findings 49–50), where the short book lost money overall but
won in exactly the years the long book lost, and delivered zero losing years.

Measured directly on monthly R booked at exit:

| | |
|---|---|
| monthly R correlation | **+0.300** |
| both up / both down / split | 14 / **16** / 15 |
| trendline sd | 16.79 |
| divergence sd | 13.46 |
| stacked sd, actual | **24.47** |
| stacked sd if perfectly uncorrelated | 21.52 |
| stacked sd if perfectly correlated | 30.26 |

Sixteen of the 45 decided months are down in both books. The realised standard
deviation sits between the uncorrelated and correlated bounds and nearer the
correlated end than a diversification story needs.

The reason is structural and should have been predicted: both books are
**long-only daily breakouts on the same 76 coins**. One buys a break of a
200-day descending line, the other a break of a short falling line after a
divergence. Different triggers, same bet — buy crypto strength after weakness.
When the universe falls, both lose. Different *indicators* are not different
*exposures*.

**What stacking does deliver** is more money at disproportionately more pain.
Whole universe, 40 slots: CAGR 28.50% → 29.01%, drawdown 32.54% → 51.18%. That
is the "same bet at higher size" the handover already warns against, arriving
through the side door.

## A documentation correction

The handover called the grid winner "2xATR stop + 4R target". That shorthand is
incomplete and cost a wasted run. The winning cell in
`results/VERIFY_1d.txt` also moves `wt2_max` from −30 to **−20**, `wait_bars`
from 8 to **16**, and `require_hold` from True to **False**. Changing only the
stop and target yields 15 fit signals rather than 84, and turns the book
negative. Section 5 of the handover has been corrected.

## What this means for step 4

Step 4 — find a second uncorrelated positive-expectancy book — is now the
priority, and finding 52 constrains it. A second book must differ in
**exposure**, not in indicator. Candidates that are structurally different
rather than cosmetically different:

* **funding-rate carry** — paid by position imbalance, not by price direction
* **cross-sectional relative strength** — long the strong against short the
  weak, so the market component is netted out. This is the repo's own core
  feature and no work here has used it.
* **short-side or market-neutral exposure** of any kind

Another long-only breakout on the same universe will fail the same way, however
good its indicator is.

---

# STEP 4 — cross-sectional relative strength, the first genuinely different exposure

Finding 52 said a second book must differ in **exposure**, not in indicator.
This is the market-neutral version: every `hold` days, rank the universe, hold
the strongest `n` coins against the weakest `n`, 0.5 gross each side so net is
zero. Whatever the whole market does that period hits both legs and drops out.

It is also the repo's own core feature. The ranking signal is
`backend/screener/rs.py`'s blended strength z-score, computed on each coin's
ratio to BTC — the thing the screener was built for and that no work in
`freqtrade-lab` had used. [xsect.py](xsect.py) is the implementation; it is a
rebalance book, not a trade list, so it needs its own simulator rather than the
R-multiple harness.

Score at date *t* uses closes to *t*; the position is entered at the next bar's
**open** and exited at the open `hold` bars later. Costs charge a full turnover
every rebalance, which is pessimistic.

## Finding 53 — the plateau is real and the exposure is genuinely different

`rs_vs_btc`, 5 legs each side, 14-day hold, positive on **both** baskets at
every lookback tested:

| lookback | FIT CAGR | HOLDOUT CAGR |
|---|---|---|
| 14 | +19.0% | +22.6% |
| 30 | +22.3% | +20.4% |
| 60 | +18.3% | +17.1% |
| 90 | +18.6% | +17.8% |

Four settings spanning a 6× range of lookback, all within a few points on both
baskets. That is a plateau, and `rs_vs_btc` beat plain trailing return and
volatility-adjusted return at nearly every setting — the repo's own score is
doing real work.

**And it is uncorrelated with the trendline book, which is the whole point:**

| | vs trendline |
|---|---|
| monthly correlation | **+0.105** |
| both up / both down / disagree | 12 / 14 / **38** |

Compare the failed stack of the two breakout books: +0.300, with only 15 of 45
months disagreeing. This is a real diversifier; that was not.

## Finding 54 — but it does not raise the ratio, only the Sharpe

79 overlapping months, whole universe:

| book | CAGR | max DD | **ratio** | **Sharpe** |
|---|---|---|---|---|
| trendline only | +17.43% | 19.24% | **0.91** | 0.82 |
| cross-sectional only | +22.69% | 54.75% | 0.41 | 0.63 |
| **blend 75/25** | **+20.98%** | **23.29%** | **0.90** | **0.99** |
| blend 50/50 | +23.00% | 32.76% | 0.70 | 0.89 |
| blend 25/75 | +23.56% | 41.83% | 0.56 | 0.74 |

The ratio does not move (0.91 → 0.90). **Sharpe rises 0.82 → 0.99**, a 21%
improvement in risk-adjusted return.

Those two disagree because they measure different things. Sharpe is driven by
typical volatility, which diversification reliably reduces. The ratio is driven
by the single worst drawdown, which only improves if the two books' worst events
do not coincide — and 2022 was bad for both (−15.3% and −42.5%). Low correlation
on average does not mean independent tails.

**The honest reading:** the 75/25 blend buys +3.5 CAGR points for +4 drawdown
points and a materially better Sharpe. Real, and modest. It is not an answer to
"single-digit returns are peanuts".

## Finding 55 — the cross-sectional edge is mostly one alt season

| basket | full CAGR | **excluding 2021** | 2021 alone |
|---|---|---|---|
| FIT | +22.2% | **+11.6%** | +83% |
| HOLDOUT | +20.3% | **+11.3%** | +68% |
| **ALL (76 coins)** | +23.2% | **−1.5%** | **+342%** |

Per year:

| year | FIT | HOLDOUT | ALL |
|---|---|---|---|
| 2020 | +111.2% | +40.3% | +81.8% |
| 2021 | +82.7% | +67.5% | **+342.4%** |
| 2022 | −45.5% | −6.2% | −42.5% |
| 2023 | +11.7% | +54.6% | +4.6% |
| 2024 | +10.8% | +2.7% | −7.0% |
| 2025 | +29.9% | +19.7% | +12.7% |
| 2026 | +12.6% | −18.3% | −20.9% |

Two things to take from this.

**The whole-universe version is worse than either half**, which sounds
impossible and is not. With a fixed 5 legs, the fraction of the universe held
shrinks as the universe grows: 5 of 38 coins is the top 13%, 5 of 76 is the top
6.6%. The bigger basket therefore holds *more extreme* names — more volatile,
and here worse. **Leg count must scale with universe size**, and no result in
this section should be read as a constant-`n_legs` finding.

**Ex-2021, the half-baskets hold up and the whole universe does not.** FIT
+11.6% and HOLDOUT +11.3% ex-2021 is a striking agreement between two disjoint
coin sets. But ALL at −1.5% means the concentrated version needs the alt season.
2020–2021 was an exceptional regime for cross-sectional dispersion in alts, and
2024 and 2026 are negative on the whole universe.

## Verdict on step 4

Partly successful. The hypothesis that motivated it is **confirmed**: a
market-neutral construction is genuinely uncorrelated with the long-only
breakout books, at +0.105 against +0.300 for another breakout. That is the first
time anything here has cleared that bar.

What it does not do is solve the returns problem. Standalone it has a 55%
drawdown and needs 2021. Blended at 25% weight it improves Sharpe by a fifth and
leaves the drawdown ratio untouched.

**Next, in order:**

1. **Scale legs with universe size** and re-run. `n_legs` was fixed while the
   universe varied, which confounds every whole-universe number above. Holding
   the top and bottom decile rather than a fixed count is the correct
   formulation and is one change to [xsect.py](xsect.py).
2. **Add a volatility target.** The book's 55% drawdown comes from unmanaged
   leg volatility, not from the signal. Scaling exposure to a target volatility
   is the standard fix and would move the ratio, which is the metric that
   matters.
3. **Re-test ex-2021 after 1 and 2.** If a decile-based, volatility-targeted
   version is positive ex-2021 on both baskets, this becomes a real second book
   rather than a Sharpe improvement.
