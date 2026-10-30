# SMC research log

Smart Money Concepts (SMC) on Binance USDT coins, traded as perpetual futures,
long and short. Brief from the trader (2026-10-29): short-term timeframes
(15m, 1h, 4h, 1d), multi-timeframe — higher timeframe (HTF) for direction,
lower timeframe (LTF) for the entry. Both trend continuation and reversals.
Target a respectable win rate at about 1:3 risk to reward.

Read this before the next round. Each round says what was tried, what the
numbers were, and what the next round should do because of it.

Code: [smc.py](smc.py) (engine), [smc_loop.py](smc_loop.py) (rounds).
Results: `research/results/smc_<round>.jsonl` and `.txt` (gitignored).

---

## Rules of the loop

1. **Two coin halves.** FIT and HOLDOUT are the md5 split from campaign.py.
   Pick on FIT. A config counts only if HOLDOUT agrees.
2. **A dial is real only if its effect points the same way on both halves**
   and its neighbours agree. A single best cell is noise until shown otherwise.
3. **No lookahead.** Pivots are known k bars late. HTF bars are used only
   after they close. The risk filter uses the signal close, not the next open.
   [smc_lookahead.py](smc_lookahead.py) truncates the data at 3 points and checks that
   every earlier trade is identical (passed 21/21 after every engine change, last 2026-10-30).
4. **Costs are in.** 0.06% per side (futures taker + slippage) as the base.
   Stress at 0.10% before believing anything.
5. **Final exam = coins never used.** In this repo, out-of-sample in time was
   not enough — a strategy fell from 49% to ~15% CAGR on unseen coins. Run
   the winner on the ~200 other coins on disk before calling it real.

## Definitions (as coded)

| term | rule in smc.py |
|---|---|
| swing high/low | fractal pivot, k bars each side; known at bar i+k |
| BOS | close beyond the last unbroken swing point, WITH the trend |
| CHoCH | the same break AGAINST the trend (trend flips) |
| origin | the extreme the breaking leg started from; the stop goes beyond it |
| order block (OB) | last opposite-colour candle at or just before the origin |
| FVG | 3-candle gap inside the breaking leg, nearest the origin |
| OTE | limit at 70.5% retracement of the breaking leg |
| swept | the origin candle wicked through the prior swing point and closed back |
| HTF sweep | an HTF candle wicks through a live HTF swing point and closes back; stays live 6 HTF bars unless price closes beyond it |
| discount | the LTF pullback low sits below the middle of the HTF dealing range |
| continuation | LTF break in the HTF trend direction |
| reversal | LTF break whose leg starts inside or after a live HTF sweep |

Fills: market = next LTF open. Limits fill at the limit; the fill bar only
tests the stop. Stop before target on every later bar. One trade per coin at a
time; a newer setup replaces a resting limit.

---

## What works / what does not (running summary)

**The answer so far:** one setup survives — [SMC Sweep-Break](STRATEGY_SMC_SweepBreak.md):
daily structure bias, a 4h break whose origin swept the previous 4h swing,
market entry, stop beyond the sweep, exit on the opposite 4h CHoCH or 6R.
On 203 never-used coins: +0.245R a trade, win 36%, PF 1.49. On all 279 at
0.5% risk and 10 slots: 22.6% CAGR at a 15% drawdown.

**Works**
- Daily bias + 4h entry. Nothing on 15m or 1h survived the new coins.
- A liquidity sweep before the break: it doubles the edge (+0.15 -> +0.31R).
- Market entry at the next candle after the break.
- Exit on the opposite 4h CHoCH with a far target (6-10R), not a fixed 3R.
- Both sides. Shorts led on the 76; longs led on the 203.

**Does not work (do not re-test without a new reason)**
- Any 15m entry: costs, and the one 15m survivor was a ridge.
- Limit entries at OB / FVG / OTE: fine on the 76, gone on the 203.
- Moving the stop to breakeven: worse on all 6 families.
- Partial profit at 1-2R: raises the win rate to 50%+ but lowers avg R.
- Filters picked from feature buckets (leg size, volume, daily SMA): looked
  good on the 76, added nothing on the 203.
- The 1h reversal family: tight stops, 62-76% account drawdown.
- A 4h bias for a 1h entry: about zero.

**Method lessons**
- The FIT/HOLDOUT hash split passed configs that then lost 2/3 of their edge
  on new coins. Only the new-coin test is a real test.
- 15m data starts late (2022-2024 for most coins). Build every timeframe from
  1h data so the 2020-2021 bull market is in the sample.
- Win rate here counts any net-positive exit. Read `hit_tp` for "reached
  the target".

---

## Round log

### Round 1 — 2026-10-29: which SMC structure has any edge? (480 configs)

Grid: 5 timeframe pairs (15m/1h, 15m/4h, 1h/4h, 1h/1d, 4h/1d) x 4 entries
(market, OB, FVG, OTE) x CHoCH-only or any break x LTF sweep required or not
x HTF discount or not (continuation) x min stop 0.5% or 1%. Target fixed 3R,
stop 0.1 ATR beyond the origin, both sides, 76 coins.

**Result: almost all of SMC loses after costs.** Median config is -0.05R per
trade. 51 of 472 cells are positive on both halves. Win rates 23-40% at 3R
(median 28%), which is about break-even at 3R once fees are in.

| finding | numbers (median HOLDOUT avg R) |
|---|---|
| higher timeframe is better | entry on 15m -0.074, 1h -0.034, 4h -0.005 |
| daily bias is better | HTF 1h -0.080, 4h -0.046, 1d -0.023 |
| **shorts beat longs in 85% of cells** | longs -0.09, shorts -0.02 (cont) / +0.05 (rev) |
| reversal beats continuation (median) | rev -0.027, cont -0.051 |
| OTE (70.5% retrace) is the best entry | -0.030 vs -0.046..-0.050; and it is best inside the top cells |
| a liquidity sweep before the CHoCH helps ONLY with OTE on 4h/1d | OTE+swept +0.232 vs OTE alone +0.032 |
| min stop 1% beats 0.5% | -0.037 vs -0.050 (costs) |

Best cells, positive on BOTH halves (FIT / HOLDOUT avg R, n per half):

| # | config | FIT | HOLD | n | win% | note |
|---|---|---|---|---|---|---|
| B1 | 4h/1d cont, OTE, CHoCH, swept, min 1% | +0.131 | +0.226 | ~240 | 31 | shorts +0.35, longs -0.07 |
| B2 | 15m/4h cont, OTE, CHoCH, swept, discount, min 1% | +0.115 | +0.107 | ~290 | 30 | longs +0.12 AND shorts +0.11 |
| B3 | 1h/1d cont, FVG, CHoCH, discount, min 1% | +0.059 | +0.063 | ~1700 | 30 | big sample, 6/7 years |
| B4 | 1h/4h rev, OB, CHoCH, min 1% | +0.044 | +0.057 | ~2560 | 31 | the reversal family |
| B5 | 4h/1d cont, market, any break, swept, min 0.5% | +0.104 | +0.080 | ~910 | 37 | highest win rate |
| B6 | 1h/1d cont, OB, CHoCH, swept, discount, min 1% | +0.049 | +0.073 | ~760 | 30 | |

**Warning on shorts.** 2021-2026 was a long bear market for most alts
against USDT. Shorts winning may be that drift, not SMC. Check per year and
on BTC/ETH alone before leaning on it.

**Next (round 2):** one-dial-at-a-time sweeps around B1-B6: pivot widths,
stop buffer, target R, breakeven, partial take-profit, exit on opposite CHoCH,
limit expiry, sweep life, min/max stop, long-only vs short-only.

### Round 2 — 2026-10-30: one dial at a time around B1-B6 (243 configs)

Each base config, every alternative value of one dial, the rest fixed.

| dial | what it did (FIT / HOLDOUT, all 6 bases) | verdict |
|---|---|---|
| **side = shorts only** | B1 +0.30/+0.41, B3 +0.14/+0.13, B4 +0.11/+0.18, B5 +0.12/+0.16. Longs ~0 or negative. B2 and B6 equal | strongest dial found; regime risk (see below) |
| target R | 4-5R ≥ 3R on B1, B2, B4, B5; 2R is worst everywhere | aim further, not closer |
| breakeven move | worse or equal on all 6 | **dead** — do not move the stop to entry |
| partial at 1-2R | win rate 37-58% but avg R lower on all 6 | **dead for expectancy**; only buys a nicer win rate |
| exit on opposite CHoCH | mixed, ±0.03 | no effect |
| stop buffer 1 ATR | helps the 4h entries (B1, B5), hurts the 1h/15m ones | wider stop on 4h only |
| bigger LTF pivot (k=5-8) on B5 | +0.28/+0.17 at k5 (win 42%), +0.33/+0.13 at k8 (win 45%) | bigger swings = better trades |
| limit expiry 4 bars | worse on 5 of 6 | give limits 12+ bars |
| HTF sweep life | 2 bars slightly best for the reversal family | keep sweeps fresh |
| min stop | B1, B3, B6 like 1.5-2%; **B2 (15m) flips sign at 0.5% and at 1.5%** | B2 is a ridge, not a plateau |

**15m is dead again.** B2 (the only 15m survivor) is positive at exactly one
min-stop value and one pivot width, and negative around it. That is the
noise signature. Same conclusion as HANDOVER.md: costs kill 15m.

**B1 is a plateau.** Every value of k_htf, stop buffer, target 2.5-5R,
min stop, max stop and expiry stays positive on HOLDOUT. Small sample
(~230 trades a half).

**Short side, per year (B1, all coins):** 2022 +0.25, 2023 +0.58, 2024 +0.14,
2025 +0.32, 2026 +0.76 avg R; 2021 (bull) -0.54 on 8 trades. Longs lost in
2022, 2023 and 2025. So far this looks like "trade WITH the coin's daily
trend, and most alts were in a daily downtrend". The 15m data only starts
2020-10 to 2024 depending on the coin, so the 2021 bull market is thin.

**Next (round 3):** joint grids on the four robust families using 1h data
as the base (history back to 2020 for every coin, so the 2021 bull is in).
Drop 15m. Then features on the leaders.

### Round 3 — 2026-10-30: joint grids on 1h data, history from 2020 (432 configs)

Base data switched from 15m to 1h, so 49 of the 76 coins reach back to 2020
and the 2021 bull market is in. 15m dropped.

**353 of 381 cells positive on both halves** (round 1: 51 of 472). Medians:
4h entry +0.157 / +0.149, 1h entry +0.080 / +0.112. With 2020-2021 in the
sample, **longs turn positive too** on the 4h families (A: longs +0.23,
shorts +0.30). The short-only edge in rounds 1-2 was partly the 15m data
starting in the alt bear market.

| dial | effect | verdict |
|---|---|---|
| target | 3R +0.112, 4R +0.138, 5R +0.168 (HOLDOUT median) | further is better |
| shorts only | +0.185 vs +0.111 both sides | still better, but longs now positive |
| 4h stop buffer 1 ATR | wins more (44-58%) but hits the target less | win rate up, expectancy about the same |
| reversal: max stop 2% | best F4 cells all use it | keep the 1h reversal stop tight |

Leaders (FIT / HOLDOUT avg R, both sides):

| name | config | FIT | HOLD | n/half | win | years + |
|---|---|---|---|---|---|---|
| A_ote4h | 4h/1d cont, OTE limit, CHoCH, swept, k 3/5, 4R, exit on CHoCH | +0.247 | +0.288 | ~380 | 28% | 6/7 |
| B_mkt4h | 4h/1d cont, market, any break, swept, k 5/2, 4R | +0.258 | +0.219 | ~460 | 43% | 6/7 |
| C_rev1h | 1h/4h reversal, OB limit, CHoCH, k 2/3, 4R, stop 1-2%, sweep life 2 | +0.087 | +0.131 | ~1340 | 26% | 7/7 |
| D_fvg1h | 1h/1d cont, FVG limit, CHoCH, discount, 3R, min stop 1.5% | +0.099 | +0.106 | ~1700 | 31% | 5/7 |

### Round 4 — 2026-10-30: filters from the feature study (392 configs)

`smc_features.py` bucketed every leader's trades by things known at the
signal. Three looked real on both halves; round 4 tested them as filters.

| filter | A_ote4h | B_mkt4h | C_rev1h | D_fvg1h |
|---|---|---|---|---|
| **session: signal bar opens 12:00-24:00 UTC** | mixed | mixed | **+0.13/+0.19 -> +0.35/+0.24** | hurts |
| ...the mirror, 00:00-12:00 only | | | -0.06 / +0.07 | |
| **volume ≥ 0.9x its 96-bar mean** | helps FIT | **helps both** | **helps both** | hurts |
| **breaking leg ≤ 3.5 ATR** (not over-extended) | **helps both** | **helps both** | equal | hurts |
| trade the side of the daily 50 SMA | slight + | mixed | mixed | hurts |

The session effect on the 1h reversal is the cleanest thing found: it is
monotone across the hour buckets on both halves, and it has a known cause
(London close / New York session is when liquidity sweeps resolve).

D_fvg1h gets worse with every filter — dropped.

Finalists, filtered (FIT / HOLDOUT avg R, both sides):

| name | filters | FIT | HOLD | n/half | win | hit 4R | longs / shorts |
|---|---|---|---|---|---|---|---|
| C_rev1h_ny_vol | 12-24 UTC, vol ≥ 0.9x | +0.381 | +0.341 | ~360 | 31% | 25% | +0.31 / +0.40 |
| A_ote4h_leg | leg ≤ 3.5 ATR | +0.309 | +0.326 | ~310 | 29% | 25% | +0.29 / +0.34 |
| B_mkt4h_leg_vol | leg ≤ 3.5 ATR, vol ≥ 0.9x | +0.358 | +0.363 | ~185 | 44% | 12% | +0.20 / +0.49 |

**Next:** the exam (smc_oos.py) — the 203 coins never used, costs at 0.10%
per side, and an account with 1% risk, 10 slots, 5x notional cap.

### The exam — 2026-10-30: 203 coins never used, 0.10% cost, an account

Account = 1% risk per trade, 10 slots, notional cap 5x, profit banked at exit.

| finalist | old 76 avg R | **new 203 avg R** | new at 0.10% cost | new account CAGR / DD | verdict |
|---|---|---|---|---|---|
| C_rev1h_ny_vol | +0.360 | +0.131 | +0.077 | 17.6% / 62% | fell by 2/3, DD unusable |
| C_rev1h_raw | +0.109 | +0.051 | -0.002 | -1.5% / 76% | **dead** |
| A_ote4h_leg | +0.318 | +0.092 | +0.057 | 0.2% / 70% | **dead** |
| A_ote4h_raw | +0.267 | +0.072 | +0.040 | -2.1% / 80% | **dead** |
| B_mkt4h_leg_vol | +0.360 | +0.211 | +0.197 | 15.8% / 30% | holds, filters add nothing |
| **B_mkt4h_raw** | **+0.238** | **+0.220** | **+0.206** | **37.4% / 34% (39% worst case)** | **survives intact** |

**Lessons:**

1. **The hash split is not enough.** A and C passed FIT and HOLDOUT
   comfortably and still lost two thirds of their edge on new coins. Same
   lesson as TrendlineBreakoutLTF. Everything tuned on the 76 coins is
   suspect until the 203 agree.
2. **The round 4 filters mostly did not travel.** Leg-size and volume made B
   look better on the 76 (+0.36) and slightly worse on the 203 (+0.21 vs
   +0.22). The New York session filter is the one partial exception: it
   lifted C on the new coins from +0.05 to +0.13.
3. **Limit-order entries (OTE, OB) did not generalise; the market entry did.**
   The limit families depend on exactly where price retraces, which is the
   kind of detail that fits the sample.
4. **Tight stops make account drawdown explode.** C's 1-2% stops mean big
   positions; 95R of drawdown at 1% risk is a 62% account loss.

B_mkt4h_raw on the new coins: win 42%, PF 1.41, 6 of 7 years positive,
109 of 193 coins positive, longs +0.33 and shorts +0.16. Only 9% of trades
reach the 4R target; most winners leave on the 7-day time stop. So the next
round tests its EXIT (target, hold time, trail), picked on the old 76 only.

### Round 5 — 2026-10-30: the exit of B_mkt4h_raw (192 configs, 76 coins only)

Target 3/4/6/10R x hold 3.5/7/14/28 days x trail none/1.5R/2.5R x exit on
opposite 4h CHoCH or not x stop buffer 0.1/0.5 ATR.

| dial | median FIT / HOLDOUT avg R |
|---|---|
| target | 3R +0.226/+0.178, 4R +0.246/+0.219, 6R +0.274/+0.227, 10R +0.286/+0.237 |
| hold | 3.5d +0.17/+0.16, 7d +0.26/+0.24, 14d +0.28/+0.21, 28d +0.28/+0.23 |
| exit on opposite CHoCH | ratio 0.64/0.51 -> **0.74/0.69** |
| stop buffer 0.5 ATR | +0.26/+0.24 vs +0.22/+0.20 |
| trailing stop | no help |

Plateau: stop 0.5 ATR + exit on CHoCH + target 6-10R + hold 14-28 days, all
cells +0.27..+0.37 with drawdown about half of the base. Picked the middle:
**6R, 28 days, CHoCH exit, 0.5 ATR** = `B_final`.

New coins, looked at once after the pick: +0.220 -> **+0.245R**, ratio
0.94 -> 1.02, account 37.4% CAGR / 33.9% DD -> 29.2% / 28.7%. Same edge,
smoother.

### Controls — is it SMC, or just trend following?

| change to B_final | 76 old | 203 new |
|---|---|---|
| none | +0.310 | +0.245 |
| no liquidity sweep | +0.153 | +0.116 |
| CHoCH only (no BOS) | +0.327 | +0.251 (half the trades) |
| 3-bar 4h swings | +0.185 | +0.136 |
| 8-bar 4h swings | +0.215 | +0.215 |
| 1h entry, 4h bias | +0.041 | +0.028 |

The sweep is worth about +0.13 to +0.16R per trade on both sets. Trend
following alone (no sweep) is positive but half as good.

### Where to go next

1. **Cross-check B_final in freqtrade** (the repo rule). Needs a strategy
   file with the 4h/1d structure, informative daily pairs, custom stop and
   custom exit.
2. **Paper trade it.** DONE 2026-10-30: [scan_smc.py](scan_smc.py) prints
   NEW / OPEN / CLOSED from live futures candles, and
   [scan_smc_check.py](scan_smc_check.py) shows it matches the backtest
   (4,329 checks, 0 mismatches). Since 2026-10-30 a scheduled task runs it
   every 4h and keeps a paper journal: [journal/SMC_PAPER.md](../../journal/SMC_PAPER.md).
   Judge it after 30+ closed on-time trades.
3. **Fix 2022.** Every SMC family was flat or negative in 2022 (a choppy
   bear). A regime switch on BTC volatility is the untested idea.
4. **Stack with TrendlineBreakoutLTF.** Different holding period (5 days vs
   ~70) and both sides, so the correlation may actually be low this time.
