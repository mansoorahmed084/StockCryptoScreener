# Liquidity Swings [LuxAlgo] — tested 2026-11-13

**Verdict: no edge on its own, and no gain inside SMC sweep-break. Keep
B_final as it is.**

Code: [liquidity_swings.py](liquidity_swings.py). Tests:
`tests/test_liquidity_swings.py` (no lookahead, sweep + touch count, a close
through kills the zone, fractal mode = B_final trade for trade).
Raw rows: `research/results/liquidity_swings.jsonl` (not tracked).

## The rebuild

LuxAlgo shows no code for this one, so it follows the published description
and defaults: pivot length 14, wick zone (pivot extreme to the nearer body
edge), live until a candle closes beyond it, count = candles that touched the
live zone. A sweep = a wick beyond the zone extreme and a close back inside.

## Test A — trade the sweep reversal on its own

72 configs: 1h / 4h / 1d × latest zone or any live zone × count ≥ 0 / 3 / 6 ×
2R / 3R target × daily structure bias on/off. Entry next open, stop 0.1 ATR
beyond the sweep wick, 42-bar time stop, 0.06% per side.

**All 72 lose on both coin sets.** 203 unseen coins: −0.08 to −0.18R per
trade, PF 0.76–0.90. A high touch count does not help. The daily bias does not
help. Same finding as the dead SMC reversal modes: a sweep alone is not a
signal.

## Test B — Liquidity Swings zones as the sweep inside B_final

B_final needs the origin candle of the 4h break to sweep the last k=5 fractal
swing. Here that swing is replaced by a Liquidity Swings zone.

| sweep rule | old 76: n / avg R | new 203: n / avg R | PF | account (new, 0.5%) |
|---|---|---|---|---|
| **B_final (fractal k=5)** | 681 / +0.310 | 1,053 / **+0.245** | 1.49 | 15.4% CAGR, 17.6% DD |
| latest zone, len 5 | 562 / +0.278 | 856 / +0.213 | 1.42 | 11.5%, 17.9% |
| latest zone, len 5, count ≥ 3 | 162 / +0.364 | 224 / +0.292 | 1.60 | 4.9%, 6.9% |
| latest zone, len 5, count ≥ 6 | 54 / +0.033 | 68 / +0.057 | 1.11 | 0.4% |
| latest zone, len 14 | 131 / +0.142 | 221 / +0.115 | 1.26 | 2.0% |
| any live zone, len 5 | 735 / +0.202 | 1,085 / +0.190 | 1.38 | 9.7%, 21.9% |
| any live zone, len 14 | 160 / +0.092 | 250 / +0.106 | 1.24 | 2.0% |
| fractal OR any zone, len 14, count ≥ 6 | 716 / +0.290 | 1,099 / +0.235 | 1.47 | 14.4%, 17.7% |

Read:

- Swapping the fractal swing for a Liquidity Swings zone is worse every time.
  The LuxAlgo default length 14 is much worse (+0.11R): those swings are too
  far apart, so few breaks start with a sweep of one.
- Adding zones on top of the fractal (union) adds trades at a lower R. CAGR
  does not rise.
- Count ≥ 3 at length 5 shows +0.29R, but on 224 trades (SE ≈ 0.13R) and
  count ≥ 6 collapses to +0.06R. The count does not rise in a straight line,
  so this is noise, not a filter. It also cuts the account to 4.9% CAGR.

B_final was reproduced exactly (+0.245R on the new coins), so the hook is
sound.
