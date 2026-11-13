# Support and Resistance Levels with Breaks [LuxAlgo] — tested 2026-11-13

**Verdict: LuxAlgo's own signal (the volume-confirmed "B") adds nothing. One
plain variant is a weak but steady CANDIDATE: 4h break, stop at support, hold
up to 7 days. Not proven. Weaker per trade than SMC sweep-break.**

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

Next, if wanted: correlation with SMC sweep-break (a diversifier?), a time-stop
and stop-distance plateau check on the old 76 only, then a freqtrade
cross-check.
