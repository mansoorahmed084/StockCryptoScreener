# SuperTrend AI (Clustering) [LuxAlgo] — tested 2026-11-13

**Verdict: no edge. Do not trade it.** Nothing beats the 4h sweep-break
baseline (+0.245R/trade on the 203 unseen coins).

Code: [supertrend_ai.py](supertrend_ai.py) (indicator + simulator + grid).
Tests: `tests/test_supertrend_ai.py` (no lookahead, line side, final line =
SuperTrend on the chosen factor, R booking).
Raw rows: `research/results/supertrend_ai.jsonl` (not tracked).

## The rebuild

LuxAlgo's free open-source script with its default settings: nine SuperTrends
(ATR 10, factors 1.0–5.0 step 0.5), each scored by an EMA(10) of signed
close-to-close change, k-means k=3 seeded at the quartiles, mean factor of the
best cluster drives one final SuperTrend. Its flip is the signal. The signal
score = int(10 × best-cluster score / EMA(10) of |Δclose|).

## The grid

40 configs: TF 1h / 4h / 1d × long or both × exit flip (next open after the
line flips) or touch (stop order on the line) × score ≥ 0 or ≥ 3 × daily
SuperTrend AI bias on/off (1h, 4h only). Cost 0.06% per side, stress 0.10%.
Entry next open. Stops closer than 0.5% are skipped.

## Results — 203 unseen coins

| config | n | avg R | PF | win | avg R without top 1% | account at 0.5% risk |
|---|---|---|---|---|---|---|
| 1h, any | 23k–252k | −0.04 to −0.08 | 0.85–0.92 | 30–33% | −0.13 to −0.21 | — |
| 4h both flip s≥3 +1d bias | 13,651 | +0.048 | 1.09 | 36% | −0.075 | 12.1% CAGR, 42% DD |
| 1d long flip s≥3 (best on the old 76) | 2,323 | +0.126 | 1.21 | 28% | −0.144 | 6.0% CAGR, 54% DD |
| 1d long touch s≥3 (best on new) | 2,323 | +0.156 | 1.33 | 29% | −0.093 | 3.6% CAGR, 56% DD |
| 1d both flip s≥3 | 4,298 | +0.080 | 1.15 | 36% | −0.114 | 11.1% CAGR, 35% DD |
| *baseline: 4h SMC sweep-break* | — | *+0.245* | *1.49* | *36%* | — | *22.6% CAGR, 15% DD (all coins)* |

What kills it:

- **Every positive row turns negative without its top 1% of trades.** The
  "edge" is a few giant runners.
- **Daily longs live on 2021 alone** (+3.1R avg per trade in 2021; negative in
  2020, 2022, 2025, 2026). 3 of 7 years positive.
- **The old 76 coins flatter it 2–4×** (1d long flip: +0.57R old vs +0.13R
  new) — the same hindsight-universe effect as TrendlineBreakoutLTF.
- **LuxAlgo's signal score does not work.** On new coins a high score is
  worse, not better: 1d long flip score 3 = +0.22R, score 6+ = negative;
  4h score 8+ = −0.22R.
- The daily bias helps 4h a little (+0.05R), not enough.

## Bug caught on the way

The first run showed 4h long flip s≥3 at +0.67R on new coins. One OG trade
had a 0.02% stop (price gapped onto the line) and booked +11,095R. Without it
the row was +0.007R. Fixed with a 0.5% minimum stop distance.
