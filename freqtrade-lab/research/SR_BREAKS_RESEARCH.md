# Support and Resistance Levels with Breaks [LuxAlgo] — tested 2026-11-13

**Verdict: LuxAlgo's own signal (the volume-confirmed "B") adds nothing. One
plain variant (4h break, stop at support, hold up to 7 days) has a small,
stable edge, but round 2 shows it moves with SMC sweep-break (monthly
correlation 0.66) and adding it does not improve return per unit of
drawdown. Not worth trading next to B_final.** See "Round 2" at the end.

Code: [sr_breaks.py](sr_breaks.py). Tests: `tests/test_sr_breaks.py` (no
lookahead, level shows one bar after the pivot confirms, break rules, Pine
EMA seed, R booking). Raw rows: `research/results/sr_breaks.jsonl` (not
tracked).

## The rebuild

LuxAlgo's free v4 script, defaults: resistance / support = the latest pivot
high / low with 15 bars each side, usable one bar after it confirms; volume
oscillator 100 × (EMA5 − EMA10) / EMA10 of volume; a "B" break = a close
crossing the level with osc > 20 and no long wick against the break.

## The grid

96 configs: 1h / 4h / 1d × long or both × volume rule on/off × wick rule
on/off × stop at the break bar (−0.1 ATR) or at the opposite level (−0.1 ATR)
× exit at 3R (42-bar time stop) or at a close through the opposite level.
Entry next open, 0.06% per side, stops 0.5%–15% wide.

## What came out (203 unseen coins)

- **1h: nothing.** Best +0.02R. Bar stops lose −0.04 to −0.11R.
- **The "sr" exit (ride until support breaks) looks big and is not.** 4h long
  bar-stop sr exit: +0.33R, but −0.29R without its top 1% trades, 14% win
  rate, and the account loses (−17% CAGR, 97% drawdown).
- **Daily rows with the support stop have 4–49 trades.** Ignore them.
- **LuxAlgo's volume rule does not help.** It cuts trades and lowers CAGR in
  every like-for-like pair. The wick rule is neutral.
- **The candidate: 4h, both sides, wick rule on, no volume rule, stop at
  support, 3R / 42 bars.**

| set | n | avg R | PF | win | notes |
|---|---|---|---|---|---|
| old 76, fit half | 2,905 | +0.094 | 1.26 | | |
| old 76, hold half | 2,931 | +0.093 | 1.26 | | |
| **new 203** | **9,068** | **+0.083** | **1.21** | **46%** | +0.054R without top 1%; 133/203 coins positive; **7/7 years positive**; cost 0.10% → +0.075R |
| new 203, account at 0.5% risk | | | | | 16.6% CAGR, 25.4% worst-case DD |
| *SMC sweep-break, same coins and risk* | *1,053* | *+0.245* | *1.49* | *36%* | *15.4% CAGR, 17.6% DD* |

Why it is only a candidate:

- The edge per trade is thin (+0.08R). It lives on volume of trades.
- The stop is wide (median 11.5% away). 62% of trades leave on the 7-day time
  stop, 31% on the stop, only 7% reach 3R. In practice this is "buy a 4h
  resistance break, hold a week".
- It was picked after seeing the new coins. Its old-coin halves agree with
  the new coins (+0.09 / +0.09 / +0.08), which is the good sign the others
  lacked, but it still needs a fresh check.

## Round 2 — plateau and the SMC book ([sr_check.py](sr_check.py))

**Plateau, old 76 coins only (one dial at a time):** every neighbour stays
positive and the two hash halves agree. Pivot width 10 / 15 / 20: +0.074 /
+0.093 / +0.116R. Target 2 / 3 / 4 / 6R: +0.090 to +0.103R. Time stop 24 / 42
/ 84 bars: +0.087 / +0.093 / +0.100R. Stop buffer 0 / 0.1 / 0.5 ATR: +0.095 /
+0.093 / +0.088R. Long only: +0.108R. So the edge is real-looking, not a
spike. It is just small.

**Against SMC sweep-break (B_final):**

| | all 279 coins | new 203 coins |
|---|---|---|
| monthly R correlation | **0.66** | **0.65** |
| months both lose / months S&R loses | 23 / 31 | 19 / 32 |
| S&R total R in sweep-break's losing months | −17.6 | −6.2 |

Shared account, 0.5% risk per trade, 10 slots (CAGR / worst-case DD):

| | all 279 coins | new 203 coins |
|---|---|---|
| sweep-break alone | 22.6% / 18.4% (ratio 1.23) | 15.4% / 17.6% (0.88) |
| S&R alone | 22.2% / 32.6% (0.68) | 16.6% / 25.4% (0.65) |
| both | 27.1% / 27.1% (1.00) | 22.8% / 26.7% (0.85) |
| sweep-break alone, 20 slots | 32.9% / 29.4% (1.12) | 17.8% / 25.0% (0.71) |

Adding S&R raises CAGR, but drawdown rises as much or more. The ratio gets
worse on all coins and stays flat on new coins. They lose in the same months,
so S&R is not a diversifier. S&R also skips most of its signals (11,527 of
14,904 on all coins) because 10 slots fill up, so its account result depends
on which signals happen to come first.

Not done: a freqtrade cross-check. Not worth it unless the user wants a second
book for more signals (sweep-break had no signal above $5M from 7–11 Nov).
