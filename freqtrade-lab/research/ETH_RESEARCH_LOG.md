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
