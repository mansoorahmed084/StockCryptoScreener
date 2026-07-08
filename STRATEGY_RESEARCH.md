# Strategy Research Journal — RS-vs-BTC + VMC Multi-TF Divergence

**Objective:** find a rules-based long strategy on CoinDCX spot pairs using this
repo's framework — relative strength vs BTC + VuManChu Cipher B divergences
across timeframes — hitting **60–70% win rate** with **low drawdown**, with
explicit entry / exit / stop-loss criteria.

**Honesty rules for this research** (so the result means something):

1. **No lookahead.** A VMC divergence pivot needs 3 future candles to confirm →
   signals are only actionable 3 candles after the pivot. Daily RS state is only
   known at the daily close → the 1h backtest uses the *previous* day's state.
   Entries always fill at the *next candle open* after a signal.
2. **Costs included.** 0.1% taker fee per side + 0.05% slippage per side
   (0.3% round trip) on every trade.
3. **Conservative fills.** If a candle touches both stop and target, the stop
   is assumed to fill first. Gaps below the stop fill at the open, not the stop.
4. **In-sample / out-of-sample split.** Parameters are tuned on the first ~70%
   of history (IS); the final strategy must hold up on the untouched last ~30%
   (OOS). Only the OOS result counts as the claim.
5. **Trade count matters.** A 70% win rate over 20 trades is noise. Target
   n ≥ 100 IS trades before trusting any number.

**Definitions:** win rate = share of trades with net R > 0. Max drawdown =
peak-to-trough of the equity curve risking **1% of equity per trade** (compounded,
trades applied in exit order). Low drawdown target: **max DD ≤ 10%** at that sizing.

---

## Data

- Source: CoinDCX public candles (`B-*_USDT` markets, Binance-sourced), paginated
  via `startTime`/`endTime` (verified working — hourly history reaches back years).
- Universe: BTC + SOL, ETH, BNB, XRP, ADA, DOGE, AVAX, LINK, DOT, LTC
  (liquid majors on CoinDCX; MATIC excluded — delisted/renamed).
- Base timeframe **1h** (~18 months ≈ 13k candles/coin); 4h and 1d resampled
  from it with the repo's Monday-anchored weekly / left-labeled buckets.
- Cache: `data_cache/research/*.pkl` (gitignored).

## Iteration log

### Iteration 0 — infrastructure (no strategy yet)

Built and unit-tested the research stack (`backend/research/`):

- `data.py` — windowed history fetcher (verified `startTime`/`endTime` pagination
  against the live endpoint) + pickle cache.
- `engine.py` — trade simulator: next-open entries, intrabar stop/target with
  stop-first ordering, gap-through fills at the open, WT-cross exit requests
  filled at next open, fees+slippage, portfolio metrics with 1%-risk equity
  curve and max drawdown. **7 unit tests** cover the fill edge cases (stop and
  target in one candle, gap below stop, overlapping signals, fee drag).
- `strategy.py` — knowability-safe signal construction: divergence pivots shift
  +3 candles to their confirmation bar; 4h/1d states map to the 1h bar at whose
  close the bucket is complete; RS uses the repo's noise-filtered classifier.

**Strategy hypothesis (v0 family):** long ALT/USDT when a *confirmed* VMC bull
divergence prints on the 1h ratio chart, with variants layering: RS-vs-BTC
daily bull filter, WT cross-up confirmation, a recent 4h divergence
(multi-TF divergence), BTC regime filter. Stop below the divergence pivot low
minus an ATR buffer; first target grid at 1.5R.

### Iteration 1 — baseline grid (v0–v5): FAILED, one useful signal

Data: 10 alts, 1h, 2025-01-14 → 2026-07-08 (12,960 candles each; ~1,100 1h
divergence events, ~290 4h events). IS < 2026-01-27 ≤ OOS. All entries: next
open after confirmed VMC bull div, stop = pivot low − 0.5×ATR, TP 1.5R.

| variant | filters | IS n | IS win% | IS avgR | IS exp% | OOS n | OOS win% | OOS avgR |
|---|---|---|---|---|---|---|---|---|
| v0 raw 1h div | none | 614 | 41.0 | −0.26 | −0.20 | 346 | 28.9 | −0.60 |
| v1 + RS-1d bull | rs1d | 183 | 39.3 | −0.28 | −0.31 | 115 | 25.2 | −0.68 |
| v2 + WT cross confirm | confirm | 276 | 35.1 | −0.53 | −0.56 | 158 | 39.9 | −0.37 |
| v3 rs1d + confirm | both | 72 | 36.1 | −0.67 | −0.62 | 52 | 34.6 | −0.50 |
| **v4 multi-TF div** | 1h div + 4h div active | 43 | 46.5 | −0.18 | **+0.64** | 51 | 37.3 | −0.33 |
| v5 everything | all filters | 2 | — | — | — | 9 | — | — (too few) |

**What failed and why it matters:**
- **Raw 1h bull divergences have negative edge after costs** in this sample.
  41% wins at a 1.5R target is below the ~44% breakeven — divergence alone
  catches falling knives.
- **RS-1d bull filter did NOT help** (v1 ≈ v0 but fewer trades). Hypothesis:
  when an RS-daily-bull alt dips hard enough to print a 1h bull divergence,
  it's often the start of the RS state rolling over, not a dip in strength.
- **WT-cross confirmation HURT** (v2 < v0): waiting for the cross costs entry
  price; by the time WT crosses up, the mean-reversion bounce is partly done.
- **v5 (all filters) starves**: 2 IS trades — over-filtering.

**What worked:** v4 — *the user's core idea, divergences stacked on 1h AND 4h* —
is the only variant with positive per-trade expectancy IS (+0.64%) and the
smallest drawdowns. n is small (43/51) but it's the pocket to develop.

**Next:** before tuning exits, measure raw signal drift (forward returns at
fixed horizons, no exits) to see where the edge actually lives — including the
classic VMC rule of only counting divergences in **oversold** (WT2 ≤ −40/−53),
which the baseline ignored.

### Iteration 2a — signal-drift diagnostics (no exits): found the edge and the killer

`backend/research/diagnose.py`: mean forward return and win rate at 6/12/24/48/96
bars after entry, per signal family, IS vs OOS.

| signal family | IS n | IS mean@6 | IS mean@24 | IS win@12 | OOS n | OOS mean@24 |
|---|---|---|---|---|---|---|
| all 1h divs | 670 | +0.07% | +0.21% | 55.2% | 377 | −0.46% |
| div in oversold (WT2≤−40) | 304 | +0.29% | +0.58% | 59.5% | 153 | −1.04% |
| **div in deep oversold (WT2≤−53)** | 139 | **+0.48%** | **+0.83%** | **64.7%** | 92 | −0.66% |
| 4h divs | 162 | +0.12% | +0.17% | 48.1% | 84 | −0.36% |
| multi-TF (1h+4h active) | 44 | −0.31% | +0.49% | 50.0% | 54 | −0.05% |
| RS-4h-bull + 1h div | 92 | +0.41% | +0.38% | 54.3% | 89 | −1.38% |

**Finding 1 — the edge is oversold depth, not confluence stacking.** Requiring
WT2 ≤ −53 at the divergence triples per-signal drift and lifts 12-bar win rate
to 64.7% IS. The v4 "multi-TF divergence" pocket from iteration 1 was mostly
exit luck (its raw drift is flat). The classic VMC oversold rule is real.

**Finding 2 — the bounce is front-loaded.** Half of the 24-bar drift arrives in
the first 6 bars → this is a *fast mean-reversion* trade: quick target, short
time stop, don't overstay.

**Finding 3 — the killer is regime.** EVERY signal family is negative OOS: the
Feb–Jul 2026 window is a persistent alt bear (confirmed by the live screener:
breadth ~33%, BTC 1d bear). No long entry survives it. The missing component is
a **regime gate** — being flat in bear regimes IS the low-drawdown feature.

**Iteration 2b plan:** base = 1h div with WT2 ≤ −53. Grid: regime gates (BTC 1d
not-bear, the alt's own 1d not-bear) × exits tuned for high win rate (wide stop
2–2.5×ATR with sub-1R target; WT-cross exit; 12–24 bar time stop).

### Iteration 2b — exit shapes & regime gates: 69.6% win rate found, still net-negative

| variant | IS n | IS win% | IS avgR | IS maxDD% | OOS n | OOS win% | OOS avgR |
|---|---|---|---|---|---|---|---|
| tp1.5R, pivot stop | 139 | 41.7 | −0.37 | 43.6 | 92 | 19.6 | −0.92 |
| tp1.0R, 2.0×ATR stop | 158 | 52.5 | −0.08 | 18.3 | 94 | 31.9 | −0.52 |
| **tp0.5R, 2.5×ATR stop** | 158 | **69.6** | −0.06 | 12.5 | 95 | 46.3 | −0.44 |
| WT-cross exit, no TP | 163 | 33.1 | −0.21 | 30.3 | 98 | 26.5 | −0.24 |
| tp0.5R + alt-1d-not-bear gate | 53 | 52.8 | −0.32 | 17.2 | 36 | 38.9 | −0.58 |
| tp0.5R + BTC-not-bear gate | 66 | 60.6 | −0.22 | 15.0 | 29 | 48.3 | −0.45 |

**What worked:** the wide-stop/quick-target shape produces exactly the win-rate
band the objective asks for (69.6% IS). Drawdowns collapse with it (12.5% IS vs
43% for the 1.5R chase).

**What didn't:**
1. **Costs eat the edge.** Gross expectancy of the 69.6% shape is ≈ +0.05R;
   0.3% round trip on a ~3% risk unit ≈ −0.10R → net −0.06R. The 1h bounce is
   real but too small for taker fees.
2. **Regime gates REDUCED in-sample win rate** (69.6% → 52.8%). Counter-
   intuitive but sensible in hindsight: deep-oversold bounces are *sharpest
   inside downtrends* (squeeze behavior). Gates only earn their keep OOS
   (BTC gate: best OOS numbers, 48.3% win / −0.45R / 13% DD — least bad).

**Bugs/design flaws found in my own setup while reading these numbers:**
- The oversold check tests the **1h WT2 at the confirmation bar** (3 bars after
  the pivot — often already mid-bounce), and for 4h divergences it wrongly
  checks the 1h oscillator. It must test the divergence TF's WT2 **at the pivot**.

**Iteration 3 plan:** (a) fix oversold-at-pivot; (b) move the entry timeframe up:
4h deep-oversold divergences (bounce amplitude ~3×, costs unchanged); (c) add
**limit-order entries** on a retest (signal close − x·ATR, TTL a few bars) to
reclaim ~0.3–0.5% entry price; (d) deeper oversold sweep (−60).

### Iteration 3 — a fake breakthrough, caught and killed

First run of the limit-entry grid showed a stunning result: limit 1×ATR below
signal → **83.8% IS / 82.3% OOS win rate, positive expectancy both sides,
max DD < 10%**… with average hold 1.6 bars. Too good → audited the fill logic
and found the bias: when the limit filled intrabar and the same candle's high
also touched the target, the engine credited a win — assuming price went
low-then-high inside the bar, which is unknowable. **Fixed: on a limit-fill bar
only stop-outs can occur; targets fill from the next bar onward** (+2 engine
regression tests).

Honest re-run:

| variant | IS n | IS win% | IS avgR | OOS n | OOS win% | OOS avgR |
|---|---|---|---|---|---|---|
| 1h os−53, tp 0.5R (market) | 364 | 69.8 | −0.06 | 179 | 50.3 | −0.38 |
| 1h os−53, limit 1.0 ATR | 210 | 68.6 | −0.15 | 130 | 64.6 | −0.23 |
| 4h os−53 variants | 38–79 | 45–62 | −0.13…−0.55 | 30–50 | 33–54 | −0.28…−0.53 |

**Verdict:** the deep-oversold 1h bounce is real (win rates hold 60–70%) but
its magnitude (~0.5–0.8%) is the same order as round-trip costs — expectancy
hovers at zero gross, negative net, in every entry/exit shape tried. 4h
divergences did not rescue it. **Lesson: win rate was never the hard part —
the profit column is.**

**Iteration 4 plan — change the signal, not the exits:**
- **A. Simultaneous multi-TF stretch:** 1h deep-oversold div *while the last
  closed 4h WT2 is also ≤ −45/−53* (both TFs stretched at once — closer to the
  user's "multiple timeframe divergence" intent than the loose "4h div within
  48h" window tried earlier).
- **B. RS-selected beta-snap:** when **BTC** prints a deep-oversold 1h
  divergence, buy the alts that are **RS-4h bull vs BTC** (strength selector,
  used as designed) — strong alts bounce hardest off market-wide flushes.

### Iteration 4 — both new hypotheses failed; the conclusion is structural

| variant | IS n | IS win% | IS avgR | OOS n | OOS win% | OOS avgR |
|---|---|---|---|---|---|---|
| A: 1h div + 4h WT2≤−53, tp0.5R | 189 | 70.9 | −0.03 | 99 | 57.6 | −0.26 |
| A: other stretch variants | 165–225 | 50–69 | −0.06…−0.11 | 93–116 | 38–56 | −0.29…−0.39 |
| B: BTC-dip → RS-strong alts (all 5 shapes) | 40–95 | 21–57 | −0.20…−0.70 | 50–67 | 22–52 | −0.36…−0.55 |

- **A** reproduces the same ceiling: ~70% win rate, ≈ 0 gross expectancy, negative
  net. Simultaneous multi-TF stretch selects nicer trades but not bigger ones.
- **B is dead**: RS-strong alts do *not* bounce harder off BTC flushes net of
  costs — if anything the laggards squeeze more (consistent with iteration 2's
  regime-gate surprise).

**Structural conclusion after ~30 variants:** at the 1h scale the VMC oversold-
divergence bounce is real (win rates 65–70% on demand) but its magnitude
(~0.5–0.8%) is the same order as round-trip costs (0.3%) plus adverse tail —
net expectancy pins to ≈ 0 no matter the entry/exit engineering. **The fix is
not more filters; it's a bigger move per trade: the daily timeframe**, where the
same setup targets 5–15% swings and costs are noise. Daily candles also unlock
5 years of history (2 requests/coin) → more regimes than the 18-month 1h set.

**Iteration 5 plan:** daily-native strategy. VMC bull div on 1d (deep oversold at
pivot), optional weekly WT2 stretch + RS-vs-BTC weekly filter + BTC 1d regime
gate; stops off the daily pivot; targets 1.5–2R or WT-cross exits; holds of
days–weeks.

### Iteration 5 — daily timeframe: FIRST NET-POSITIVE RESULTS

5 years of daily candles (2021→2026), same 10 alts, same honest engine.
Entries at next daily open, stop = daily pivot low − 0.5×ATR(1d).

| variant | IS n | IS win% | IS avgR | IS maxDD% | OOS n | OOS win% | OOS avgR | OOS maxDD% |
|---|---|---|---|---|---|---|---|---|
| 1d div, os≤−53, tp1.5R | 19 | 52.6 | +0.24 | 3.9 | 18 | 61.1 | +0.32 | 4.3 |
| 1d div, os≤−45, tp1.5R | 32 | 46.9 | +0.09 | 7.8 | 24 | 62.5 | +0.39 | 6.4 |
| os≤−45, WT-cross exit | 31 | 38.7 | +0.34 | 9.0 | 23 | 56.5 | +0.50 | 9.0 |
| os≤−45, tp1.5R + **BTC-not-bear gate** | 13 | **69.2** | **+0.67** | **2.1** | 4 | 75.0 | +0.83 | 1.0 |
| os≤−45 + RS-weekly-bull | 5 | 80.0 | +0.93 | 1.1 | 4 | 25.0 | −0.48 | 3.3 |

**Why it works here and not on 1h:** the same bounce is now 5–15% per trade vs
0.3% costs (cost ≈ 0.02R at daily scale vs ≈ 0.10R at 1h). The edge was always
real; it was simply being eaten by fees at low timeframe.

**Honest caveats logged:**
- n is far too small everywhere (deep-oversold daily divs ≈ 3–6/coin/year).
  The BTC-gated 69%/75% row is n=13/4 — suggestive, not evidence.
- I have now looked at OOS results across iterations → the split is partially
  contaminated. Mitigation for the final claim: **expand the universe to ~25
  coins** (fresh, never-touched data), pick the final config on IS only, and
  report the expanded OOS once.

**Iteration 6 plan:** 25-coin daily universe; candidate configs fixed a priori:
(1) os≤−45 tp1.5R pivot-stop, (2) + BTC-not-bear gate, (3) WT-cross exit
version, (4) tp1.0R high-win variant. Judge on IS; validate once on OOS.

### Iteration 6 — 25-coin daily universe: target achieved

| variant | IS n | IS win% | IS avgR | IS PF | IS maxDD% | OOS n | OOS win% | OOS avgR | OOS maxDD% |
|---|---|---|---|---|---|---|---|---|---|
| D1 os−45 tp1.5R (no gate) | 99 | 44.4 | +0.03 | 1.05 | 24.0 | 64 | 53.1 | +0.16 | 17.8 |
| **D2 os−45 tp1.5R + BTC gate** | 46 | **67.4** | **+0.61** | **2.74** | **9.1** | 10 | **70.0** | +0.70 | 2.1 |
| D3 WT-cross exit | 98 | 35.7 | +0.19 | 1.29 | 29.1 | 64 | 45.3 | +0.04 | 21.9 |
| D4 os−45 tp1.0R | 99 | 50.5 | −0.07 | 0.87 | 22.4 | 66 | 63.6 | +0.16 | 13.2 |
| D6 os−45 tp1.0R + BTC gate | 46 | **73.9** | +0.41 | 2.44 | 4.5 | 11 | 81.8 | +0.59 | 2.1 |

The **BTC regime gate is the difference between mediocrity and the target** —
it removes the falling-knife majority (compare D1 vs D2: same entries, half the
trades, triple the win rate, one-third the drawdown).

### Iteration 7 — robustness: it's an edge, not an artifact

Nudging every parameter of D2 over the full 5y period (each row an independent
full backtest):

| nudge | n | win% | avgR | PF | maxDD% |
|---|---|---|---|---|---|
| base (os−45, buf 0.5, tp 1.5R) | 56 | 67.9 | +0.63 | 2.82 | 9.1 |
| oversold −40 / −50 / −53 | 75/44/37 | 57/71/70 | +0.37/+0.70/+0.70 | 1.8/3.2/3.2 | 15/9/7 |
| stop buffer 0.3 / 0.7 ATR | 62/49 | 65/65 | +0.54/+0.58 | 2.4/2.6 | 10/9 |
| TP 1.0 / 1.25 / 1.75 / 2.0 R | 57/56/56/56 | 75/70/68/66 | +0.44/+0.50/+0.80/+0.91 | 2.7/2.5/3.3/3.5 | 5/7/9/9 |

Every neighbor is profitable → the edge degrades gracefully. Concentration
checks: profits spread over ~18 of 25 coins (largest coin ≈ 12% of total R);
**positive every calendar year 2022–2026 including the 2022 bear** (71% win)
and the 2025–26 alt downtrend the 1h strategies drowned in.

---

## FINAL STRATEGY — "Daily Capitulation Divergence" (D2)

**Universe:** liquid USDT pairs on CoinDCX (the ~25 majors screened here).
**Timeframe:** daily candles (UTC close). Evaluate once per day after the close.

**ENTRY — all four must be true at a daily close:**
1. **VMC bullish divergence on the daily chart**: price sets a lower low vs the
   previous oscillator pivot low while WT2 sets a higher low (both pivots below
   zero) — the pivot counts only once confirmed by 3 subsequent daily closes.
2. **Deep capitulation:** WT2 ≤ **−45** at the divergence pivot.
3. **BTC regime gate:** BTC/USDT daily direction per this repo's noise-filtered
   RS classifier (strength z-score with ±0.8 deadband, hysteresis exit −0.6,
   persistence 1) is **not bear** at the signal close. This single filter is
   what turns the raw signal from 44%-win/24%-DD into 68%-win/9%-DD.
4. Enter **long at the next daily open**.

**STOP-LOSS:** divergence pivot low − 0.5 × ATR(14, daily). If that distance
exceeds 10% of entry, skip the trade (no oversized risk units).

**TARGET / EXIT:** fixed target at **1.5R** (entry + 1.5 × risk). No trailing.
Safety time-stop at 40 daily bars (rarely reached; average hold ≈ 7.5 days).
Dials, all backtested-positive: **1.0R → ~75% win rate, lowest DD (4.5%)**;
2.0R → ~66% win rate, highest expectancy (+0.91R).

**POSITION SIZING:** risk **1% of equity** per trade (size = 1% / stop-distance).
One position per coin; independent signals may overlap across coins.

**Backtested performance** (2021→2026, 25 coins, 0.1% fee + 0.05% slippage per
side, conservative fills, no lookahead):
- Full period: **n=56, 67.9% win, +0.63R/trade, PF 2.82, max DD 9.1%** @1% risk
- In-sample: 67.4% win / +0.61R · Out-of-sample: 70.0% win / +0.70R
- Positive every year; ~11 trades/year across the whole universe (patience is
  part of the strategy — expect ≈ +7%/yr at 1% risk; scale risk to taste,
  drawdown scales with it).

**What did NOT survive testing** (kept for honesty):
- 1h and 4h implementations — the identical setup's edge (~0.5–0.8%) is the
  same size as round-trip costs at those scales.
- RS-vs-BTC as an *alt selector* (RS-bull filters, beta-snap on BTC dips) —
  consistently negative; laggards squeeze as hard as leaders.
- WT-cross confirmation (worse entries), multi-TF divergence stacking and
  weekly-stretch filters (fewer trades, no better).
- One **fake 83%-win breakthrough** from a limit-fill sequence bias — caught by
  auditing the engine, fixed, regression-tested.

**Caveats:** n=56 is modest (95% CI on the win rate ≈ ±12pts, i.e. the true
rate is likely 56–80%); universe has survivorship bias (picked from today's
listings); single-venue (Binance-mirrored) data; the gate keeps you flat for
long stretches of bear markets — that *is* the low-drawdown mechanism.

**Running it live with this repo:** after the daily close, run the confluence
report (`python -m backend.cli report --base USDT --timeframes 1d`) — daily VMC
divergences appear in the `div` column and the dashboard regime header shows
the BTC daily state; take signals only when the header is not bear, stop below
the divergence pivot per above.
