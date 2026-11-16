# Signals & Overlays (our own build) — tested 2026-11-16

**Verdict: the 1h signals, the contrarian signals and the exit crosses are
dead. The confirmation signal taken WITH the trend and closed at a fixed 3R
has a real-looking edge on 4h (+0.11 to +0.15R) and on 1d (+0.25R), the same
on the old halves and on the 203 unseen coins. Alone, neither beats SMC
sweep-break as an account.**

**Round 2 (same day): the daily candidate moves with sweep-break and makes the
shared account worse — drop it. The 4h Smart Trail candidate does not move
with sweep-break (monthly correlation 0.20 to 0.33) and earns in sweep-break's
losing months. Added at half risk it lifts the shared account a little on the
unseen coins (21.2% a year / 21.5% worst drop, against 15.4% / 17.6% for
sweep-break alone). It is the first tested idea that adds to sweep-break
instead of copying it. The gain is small and it is not cross-checked in
freqtrade.** See "Round 2" at the end.

**This is NOT LuxAlgo's Signals & Overlays.** That script is paid and closed.
We built the same feature list from LuxAlgo's public docs with our own
formulas. The result says what a SuperTrend flip plus trend filters does. It
says nothing about LuxAlgo's real signals.

Code: [signals_overlays.py](signals_overlays.py) (indicator + simulator +
grid). Pine twin: `tradestation-pine/signals_overlays_own.pine`; Python and
Pine match on every bar for 21 settings on BTC 4h, ETH 1h and SOL 1d
(`tradestation-pine/compare_signals_overlays.py`). Tests:
`tests/test_signals_overlays.py` (25: no lookahead, signal and exit rules,
filters, classifier, tie-breaks, R booking). Raw rows:
`research/results/signals_overlays.jsonl` (not tracked).

## The build

- **Confirmation signal** = ATR band flip (SuperTrend), band = hl2 ±
  sensitivity × 0.25 × ATR(10). Sensitivity 12 = a 3 ATR band. **Strong (+)**
  = the flip agrees with the 200 EMA.
- **Contrarian signal** = RSI (length = sensitivity) leaves 30 / 70.
  Strong (+) = it went past 20 / 80 first.
- **Exit cross**: confirmation = RSI(14) falls back under 70 (over 30 for a
  short) while in profit. Contrarian = RSI back at 50 while in profit.
- **Autopilot** = the sensitivity with the best 250-bar result drives the
  signals (short 5–10, medium 10–20, long 20–30).
- **Classifier** = class 1–4 from where (close − EMA200) / ATR sits among its
  last 200 values. For a confirmation signal, 3–4 = with the main trend.
- **Filters**: Smart Trail (ATR trailing stop), Trend Tracer (step line),
  Trend Catcher (Kaufman average), Neo Cloud (two Donchian mid-lines), Trend
  Strength (2 × ADX above 50).

## The grid

210 configs. Entry next open, 0.06% per side, stop = signal close ∓ 2 ATR(14),
stops under 0.5% or over 15% skipped, 400 warm-up bars.

- Base, 72 configs: 1h / 4h / 1d × confirmation or contrarian × long or both ×
  all signals or strong only × exit **flip** (opposite signal) / **cross**
  (exit cross or opposite signal) / **3R** (3R target, 42-bar time stop).
- Round of dials, 138 configs, 4h and 1d, both sides, all three exits, one
  dial at a time: each filter, each Autopilot range, classes 1–2 or 3–4,
  sensitivity 8 / 16 / 20, a 4 ATR stop.

## What came out (203 unseen coins)

| timeframe | configs | avg R > 0 | still > 0 without top 1% of trades | range of avg R |
|---|---|---|---|---|
| 1h | 24 | 1 | **0** | −0.086 to +0.008 |
| 4h | 93 | 37 | 15 | −0.114 to +0.194 |
| 1d | 93 | 73 | 56 | −0.211 to +1.045 (215 trades) |

**Dead:**

- **1h, everything.** Fees eat it, as in every earlier test.
- **Contrarian signals on 1h and 4h.** All 4h rows −0.01 to −0.09R; the
  both-sides rows are positive in 1 of 7 years. Daily both-sides is near zero
  (flip −0.004R, cross −0.058R, 3R +0.109R).
- **The exit crosses.** Worse than both other exits in every like-for-like
  pair (1d confirmation: flip +0.370, 3R +0.251, cross +0.147; 4h: +0.051 /
  +0.048 / −0.007). They raise the win rate (47% vs 30%) and cut the winners.
- **The flip exit on 4h.** Positive avg R, but −0.08 to −0.19R without the top
  1% of trades. The base rows' accounts lose or draw down 64–98%.
- **Autopilot.** No steady gain over the fixed sensitivity (1d 3R: +0.251
  fixed, +0.283 / +0.223 / +0.104 short / medium / long; 4h: +0.048 fixed,
  +0.021 / +0.042 / +0.052).
- **Trend Strength filter** (+0.032R on 4h, account −15.5%) and the **4 ATR
  stop** (+0.022R on 4h; on 1d it is over the 15% limit, 54 trades).

**What works a little: the confirmation signal WITH the trend, closed at 3R.**
Three ways to say "with the trend" all help, on both halves of the old coins
and on the new coins:

| config (confirmation, both sides, 3R) | fit half | hold half | **new 203** | n new | PF | without top 1% | years + | account at 0.5% risk (CAGR / worst DD) |
|---|---|---|---|---|---|---|---|---|
| 4h, all signals | +0.089 | +0.081 | +0.048 | 28,952 | 1.08 | +0.018 | 6/7 | 16.1% / 53.9% |
| 4h, strong (+) only | +0.144 | +0.159 | +0.111 | 17,763 | 1.18 | +0.082 | 6/7 | 32.7% / 44.1% |
| 4h, classes 3–4 | +0.152 | +0.149 | +0.117 | 20,301 | 1.19 | +0.088 | 7/7 | 41.0% / 43.2% |
| 4h, classes 1–2 | −0.008 | −0.010 | −0.041 | 11,302 | 0.94 | −0.071 | 2/7 | −17.9% / 76.1% |
| **4h, Smart Trail filter** | **+0.220** | **+0.210** | **+0.147** | 11,664 | 1.24 | +0.118 | 6/7 | 27.6% / 36.8% |
| **1d, all signals** | **+0.271** | **+0.290** | **+0.251** | 1,602 | 1.40 | +0.223 | 4/6 | 8.5% / 25.2% |
| 1d, strong (+) only | +0.305 | +0.352 | +0.357 | 618 | 1.63 | +0.331 | 6/6 | 5.1% / 21.3% |
| 1d, classes 3–4 | +0.465 | +0.394 | +0.361 | 996 | 1.60 | +0.337 | 4/6 | 11.6% / 17.5% |
| 1d, classes 1–2 | −0.017 | +0.082 | +0.075 | 681 | 1.11 | +0.049 | 3/6 | 6.0% / 23.6% |
| 1d, sensitivity 8 | +0.235 | +0.219 | +0.268 | 2,220 | 1.44 | +0.241 | 4/6 | 14.1% / 16.8% |
| *SMC sweep-break, same coins and risk* | | | *+0.245* | *1,053* | *1.49* | | | *15.4% / 17.6%* |

Cost 0.10% per side lowers these by about 0.014R (4h) and 0.007R (1d).

Other daily rows that look good and are thin: long-only contrarian 3R (+0.350R,
788 trades, 3/6 years, 7.0% / 20.6%); long-only strong flip (+1.045R on 215
trades).

## Why it is only a candidate

- **Per trade it matches sweep-break; as an account it does not.** The best
  ratios of CAGR to worst drawdown are 0.95 (4h classes 3–4) and 0.84 (1d
  sensitivity 8) against 0.88 for sweep-break on the same coins (1.23 on all
  279). The filtered 4h rows carry 37–44% drawdowns. The plain daily row is
  0.34.
- **Daily loses in 2022 and is flat in 2025.** 1d all-signals 3R by year on new
  coins: 2021 +0.99 (few trades), 2022 −0.44, 2023 +0.72, 2024 +0.20,
  2025 −0.04, 2026 +0.26.
- **210 configs were run and these rows were named after seeing the new
  coins.** The old halves agree with the new coins, which is the good sign
  S&R Breaks also had, but it needs a fresh check. Picking on the old coins
  by avg R alone picks flip-exit rows; on new coins those keep their avg R
  (+0.32 to +0.48R on 1d) and live on a few runners (+0.04 to +0.13R without
  the top 1%, 2–5 of 6 years).
- **Funding is not counted.** Daily trades hold up to 42 days; at 0.03% a day
  that is up to about 0.1R on a full hold.
- **It is a SuperTrend flip.** SuperTrend AI's flips were tested dead on
  2026-11-13 with the flip exit. The new part here is the fixed 3R exit, the
  2 ATR stop and the trend agreement.

## Round 2 — plateau and the SMC book ([so_check.py](so_check.py))

Two candidates: **4h + Smart Trail filter** and **1d all signals** (both:
confirmation, long and short, 2 ATR stop, 3R, 42-bar time stop).

**Plateau, old 76 coins only (one dial at a time).** Every neighbour stays
positive and the two hash halves agree.

| dial | 4h + Smart Trail (avg R) | 1d all signals (avg R) |
|---|---|---|
| sensitivity 8 / 12 / 16 / 20 | +0.146 / **+0.215** / +0.104 / +0.081 | +0.227 / **+0.280** / +0.220 / +0.261 |
| target 2 / 3 / 4 / 6R | +0.163 / +0.215 / +0.250 / +0.305 | +0.176 / +0.280 / +0.389 / +0.503 |
| time stop 21 / 42 / 84 bars | +0.137 / +0.215 / +0.236 | +0.277 / +0.280 / +0.223 |
| stop 1.5 / 2 / 3 ATR | +0.179 / +0.215 / +0.197 | +0.217 / +0.280 / +0.749 (392 trades) |
| long only | +0.151 | +0.323 |
| strong (+) only | +0.262 | +0.329 |
| Smart Trail period 2 / 3 / 4 | +0.093 / +0.215 / +0.236 | — |

The 4h candidate is positive in 7 of 7 years on almost every row. One warning:
sensitivity 12 is the top of its dial; 8 and 16 give half to two thirds of it.

**Against SMC sweep-break (B_final):**

| | 4h + Smart Trail | 1d all signals |
|---|---|---|
| monthly R correlation, all 279 / new 203 | **0.20 / 0.33** | 0.41 / 0.37 |
| months both lose, of sweep-break's losing months (all coins) | 13 of 34 | 20 of 34 |
| its total R in sweep-break's losing months, all / new | **+792 / +165** | −324 / −46 |

Shared account, 10 slots (CAGR / worst-case DD, ratio):

| | all 279 coins | new 203 coins |
|---|---|---|
| sweep-break alone, 0.5% risk | 22.6% / 18.4% (1.23) | 15.4% / 17.6% (0.88) |
| 4h + Smart Trail alone, 0.5% | 35.5% / 48.7% (0.73) | 27.6% / 36.8% (0.75) |
| sweep-break + 4h, 0.5% | 56.3% / 40.5% (1.39) | 41.6% / 40.8% (1.02) |
| **sweep-break + 4h, 0.25%** | **27.7% / 21.8% (1.27)** | **21.2% / 21.5% (0.99)** |
| 1d alone, 0.5% | 9.0% / 25.1% (0.36) | 8.5% / 25.2% (0.34) |
| sweep-break + 1d, 0.5% | 17.3% / 24.1% (0.72) | 14.2% / 21.2% (0.67) |
| all three, 0.25% | 24.2% / 16.7% (1.45) | 22.8% / 15.1% (1.51) |

- **1d: not a second book.** It loses when sweep-break loses, and the shared
  account is worse than sweep-break alone on both coin sets.
- **4h + Smart Trail: adds a little.** At the same risk it doubles the profit
  and more than doubles the drawdown. At half risk the drawdown is close to
  sweep-break's and the profit is higher: +5 points a year on all coins, +6 on
  the unseen coins. The ratio moves from 1.23 to 1.27 and from 0.88 to 0.99.
- **All three in one account has the best ratio, and it is fragile.** With 10
  slots, 18,027 of 22,702 signals are skipped (all coins), so the result
  depends on which signals arrive first. With 20 slots the ratios are 2.08
  (all) and 1.56 (new) at 0.25% risk.
- The 4h book alone lost in 2026 (−16.6% on all coins, −1.9% on new coins).
- The 4h book skips two thirds of its own signals because the slots are full.

## Not done

A freqtrade cross-check of the 4h candidate (a second engine, real funding and
fees). A walk-forward or paper test: the candidate was named after the unseen
coins were seen. The dashboard cells (Volatility, Squeeze, Volume Sentiment)
are not in the Python twin; they do not make signals.
