# Short-Term Strategy Research — VMC Multi-Timeframe Continuation

**Objective:** a *short-term, frequent* long strategy on CoinDCX USDT pairs using
VuManChu Cipher B + multi-timeframe analysis, with:

- **R:R ≥ 1:2** (target at least twice the stop distance) — hard requirement
- **frequent trades** (target ≥ 2–3 signals/week across the universe; hundreds
  of trades in the backtest sample)
- **low drawdown** (≤ 10% max DD at 1% equity risk per trade)
- accuracy as high as achievable — at 2R with ~0.15R round-trip cost the
  breakeven win rate is ≈ 38–39%, so **45%+ is genuinely profitable and 50%+
  is excellent**. (A 65% win rate at 2R would be a money machine; do not expect
  it — the previous journal shows how win rate alone misleads.)

**Design priors carried over from [STRATEGY_RESEARCH.md](STRATEGY_RESEARCH.md):**

1. Costs killed 1h *mean reversion* because its wins were ~0.5–0.8%. With 2R
   targets on ATR-scale stops, wins are 3–6% → costs shrink to ~0.1–0.2R.
   → Short-term is viable only as **continuation/momentum**, not fading.
2. Regime/trend gates were the difference between 44% and 68% win rates on the
   daily strategy → the multi-timeframe part here is the **4h context gate**
   (WT2 state/slope, the repo's own 4h trend classifier) plus optional 1d gates.
3. All the honesty rules stand: no lookahead (4h states map to the 1h bar at
   whose close the bucket completed), entries at next open, 0.1% fee + 0.05%
   slippage per side, stop-before-target intrabar, limit fills can't hit
   same-bar targets, IS/OOS split (70/30), and a **fresh-coin validation set**
   at the end (coins never touched during tuning).

**Core hypothesis ("pullback resumption"):** in an established 4h uptrend, 1h
WT pullbacks that turn back up (WT1 crosses above WT2 from a shallow zone — a
dip, not a capitulation) continue the trend often enough to pay 2R.

Entry candidates: 1h WT cross-up in zone [lo, hi] (e.g. −60…0)
× 4h context: WT2_4h ≥ threshold / rising, 4h classifier bull, MFI_4h > 0,
price > EMA200(1h) × regime: BTC-1d / alt-1d not bear.
Stop candidates: swing low (N bars) − buffer, or k×ATR(1h).
Exit candidates: fixed 2R / 2.5R / 3R, chandelier trail (close − k×ATR).

Data: 11 coins × 18 months of 1h candles (12,960 bars each), cached;
IS < 2026-01-27 ≤ OOS. Fresh-coin validation universe fetched only at the end.

---

## Iteration log

### Iteration A — raw pullback crosses + single 4h gates: all negative

1h WT cross-up in zone (−60…0), stop = 10-bar swing low − 0.5×ATR, TP 2R,
96-bar time stop. Each 4h gate tested individually.

| variant | IS n | IS win% | IS avgR | OOS n | OOS win% | OOS avgR |
|---|---|---|---|---|---|---|
| P0 raw crosses | 1854 | 31.0 | −0.28 | 844 | 31.6 | −0.29 |
| P1 WT2_4h ≥ 0 | 1026 | 32.0 | −0.26 | 498 | 30.5 | −0.33 |
| P2 WT2_4h rising | 768 | 31.0 | −0.29 | 374 | 29.1 | −0.35 |
| P3 alt-4h classifier bull | 801 | 29.5 | −0.32 | 350 | 32.3 | −0.25 |
| P4 price > EMA200 | 779 | 30.3 | −0.30 | 348 | 31.3 | −0.28 |
| P5 MFI-4h > 0 | 960 | 31.1 | −0.27 | 311 | 29.3 | −0.39 |
| P6/P7 pairs of gates | 338–634 | 29–31 | −0.33…−0.35 | 177–275 | 29–31 | −0.28…−0.36 |

Breakeven at 2R after costs ≈ 39% wins; nothing clears 32%. **A 1h WT cross-up
is not an edge, and generic "trend up" gates don't make it one** — they cut
trades proportionally without changing per-trade quality. Frequency is there
(1854 IS trades), so aggressive filtering is affordable.

**Iteration B plan — make the entry mean something.** Three concepts from trend
anatomy, added as gates and drift-tested before any exit tuning:
1. **Recent momentum thrust:** 4h WT2 reached ≥ +53 within the last ~5 days —
   only trends that recently proved momentum get pullback entries.
2. **Real pullback depth:** min 1h WT2 over the last ~12 bars ≤ −30/−40 — the
   dip actually stretched; skip mid-trend wiggles.
3. **EMA200 rising** (slope over ~24 bars), not just price above it.

### Iteration B — structured continuation gates: the hypothesis family is DEAD

Forward-drift diagnostics (no exits) on every gate combination:

| gate | IS n | IS mean@24 | IS win@24 | OOS mean@24 |
|---|---|---|---|---|
| raw crosses | 3840 | −0.05% | 48.2% | −0.20% |
| recent 4h thrust (WT2≥53 in 5d) | 2020 | −0.23% | 46.0% | −0.30% |
| real dip (min WT2 ≤ −30/−40) | 2362–2898 | +0.02/+0.03% | 49.4% | −0.11…−0.17% |
| EMA200 up & rising | 1406 | **−0.45%** | 43.7% | −0.38% |
| thrust+dip+EMA (all 3) | 784 | −0.27% | 44.9% | −0.25% |

**Every "stronger trend" gate makes drift MORE negative.** On 1h crypto alts,
buying strength after a WT cross-up is anti-edge — this market mean-reverts at
the 1h scale (which is also *why* the capitulation entries of the first journal
had positive drift). Continuation longs at 1h are dead on this data; no exit
engineering can rescue a negative-drift entry.

**Iteration C plan — bring the proven mechanism down one timeframe.** The daily
journal's winner (capitulation divergence + BTC regime gate) at **4h**:
VMC bull div on 4h with WT2_4h ≤ −40/−45/−53 *at the pivot* (the original 4h
tests predated the oversold-at-pivot fix and never had the regime gate),
BTC-1d-not-bear gate, stop = 4h pivot low − buffer, **TP 2R** (hard requirement),
1h execution. Expect ~4× the daily strategy's frequency.

### Iteration C — 4h capitulation @ 2R on 18 months: marginal, verdict deferred

| variant | IS n | IS win% | IS avgR | OOS n | OOS win% | OOS avgR |
|---|---|---|---|---|---|---|
| os−40 / −45 / −53 ungated | 79–127 | 35–38 | −0.03…−0.13 | 50–67 | 38–40 | −0.07…0.00 |
| os−45 + BTC gate | 43 | 39.5 | −0.04 | 13 | 46.2 | +0.21 |
| os−45 + BTC + alt gate | 27 | 44.4 | +0.04 | 11 | 36.4 | −0.11 |
| os−45 + BTC + **limit entry** | 28 | 42.9 | **+0.12** | 12 | 41.7 | 0.00 |

Right at the 39% breakeven line: the mechanism transfers to 4h but the 18-month
window (chop + bear; even the daily winner only found ~13 trades here) can't
separate edge from noise — gated variants flip sign between IS and OOS on
n≈10–40. **Decision: extend the data, not the parameters.** Fetching ~3 years
of 1h × the full 25-coin universe (pagination reaches back to ≥ early 2024);
the SAME grid re-runs unchanged on the bigger sample — no new tuning.

### Iteration C′ — 3 years × 25 coins: the LONG side is conclusively dead

Same grid, 6× the trades: every variant 33–40% win IS (breakeven 39%), all
avgR ≤ +0.02, OOS uniformly negative (23–34% win). The 18-month "positive
pockets" were noise. Long capitulation @ 2R doesn't work at 4h. That kills the
third long-side family in this track.

### Iteration D — the SHORT side: first real edge of this track

Rationale: the sample is half bear, CoinDCX lists perps, and the mirror
mechanism (fading 4h **blow-off tops** — bear divergence with WT2 ≥ +45/+53 at
the pivot, gated by "BTC not bull") had never been priced. Implemented by
inverting prices (a short on X = a long on 1/X), so the entire audited long
pipeline runs unchanged.

| variant | IS n | IS win% | IS avgR | IS PF | OOS n | OOS win% | OOS avgR | OOS PF |
|---|---|---|---|---|---|---|---|---|
| ungated os−40/−45/−53 | 562–834 | 37–38 | −0.04…−0.09 | 0.88–0.94 | 159–229 | 40–44 | −0.10…0.00 | 0.87–1.00 |
| os−45 + BTC-not-bull | 170 | 43.5 | +0.08 | 1.12 | 80 | 46.2 | +0.13 | 1.21 |
| **os−53 + BTC-not-bull** | 113 | 45.1 | +0.12 | 1.18 | 52 | 46.2 | +0.15 | 1.22 |

First configuration in this document positive on both sides of the split with
real frequency. Drawdown (18–26% @1% risk) still too high → one refinement
round, **selected on IS only**:

| refinement | IS n | IS win% | IS avgR | IS PF | IS maxDD% | OOS n | OOS win% | OOS avgR | OOS maxDD% |
|---|---|---|---|---|---|---|---|---|---|
| **+ alt-not-bull gate (R1)** | 80 | **50.0** | **+0.29** | **1.51** | **10.9** | 29 | 55.2 | +0.41 | 9.8 |
| rr 2.5 / buf 0.5 / buf 1.5 / hold 120 | 112–113 | 40–46 | −0.01…+0.15 | 0.98–1.24 | 20–25 | 50–52 | −0.10…+0.43 | 12–24 |

R1 (don't fade a blow-off while the alt is still in a confirmed bull state)
wins on IS decisively and the single OOS read confirms: **55.2% win, +0.41R,
PF 1.71, max DD 9.8%.**

### Iteration E — robustness

Full-period nudges around R1 (each an independent backtest): os −45/−60,
buffer 0.75/1.25, rr 1.75/2.25, hold 180 — **all profitable** (win 48–56%,
PF 1.28–2.03); base = 109 trades, 51.4% win, +0.32R, PF 1.56, DD 10.9%.
Per-coin: top coin ≈ 19% of total R (no single-coin dependency), though a
loser tail exists (MANA/NEAR/BNB — kept; excluding them post-hoc would be
curve-fitting). Per-year: **2023 +6.5R, 2024 +6.8R, 2025 +24.4R, 2026 −2.9R** —
the current year is the weak spot (38% win over 16 trades; fading tops into a
market that keeps knifing lower without the alt re-entering "bull" state).

---

## FINAL STRATEGY — "4h Blow-off Fade" (SHORT)

⚠️ Requires **futures** (CoinDCX perps) — this is a short strategy.

**Universe:** ~25 liquid USDT perps. **Signal TF:** 4h. **Execution:** 1h.

**ENTRY (short) — all conditions at a 1h close:**
1. **VMC bearish divergence on the 4h chart**: price higher high, WT2 lower
   high, both oscillator pivots **above zero**, pivot confirmed by 3
   subsequent 4h candles.
2. **Blow-off extension:** WT2 ≥ **+53** at the divergence pivot.
3. **BTC gate:** BTC/USDT 1d direction (repo classifier) is **not bull**.
4. **Alt gate:** the alt's own 1d direction is **not bull** (never fade a
   confirmed uptrend).
5. Enter **short at the next 1h open** after all conditions are knowable.

**STOP-LOSS:** divergence pivot high + 1.0×ATR(14, 1h). Skip if risk > ~8%.
**TARGET:** fixed **2R** (R:R = 1:2 by construction). Time-stop 240×1h (10 days).
**SIZING:** 0.5–1% equity risk per trade → max DD ≈ 5.5–11% backtested.

**Backtested** (Jul 2023 → Jul 2026, 25 coins, 0.3% round-trip costs,
conservative fills, no lookahead): **n=109, 51.4% win at 2R, +0.32R/trade,
PF 1.56, max DD 10.9% @1% risk**; IS 50.0%/+0.29R · OOS 55.2%/+0.41R;
~37 trades/year (≈3/month). Robust to all parameter nudges.

**Caveats (read before trading):**
- **2026 YTD is −2.9R** — the strategy's weak regime is a relentless bear
  where alts never flip back to "bull" (the gate can't distinguish "top of a
  bounce" from "middle of a knife"). Position sizing is the defense.
- Perp **funding is not modelled** (typically ~0.01%/8h; avg hold ≈ 55h →
  ≈ 0.03–0.04R headwind on average — the edge survives it, but it's real).
- Shorts were priced via exact price inversion (log-symmetric to true shorts
  up to a small convexity term).
- n=109 → 95% CI on the 51.4% win rate ≈ ±9.4pts.
- Complements the long-side [Daily Capitulation Divergence](STRATEGY_RESEARCH.md):
  one profits from capitulation in non-bear regimes, the other from euphoria
  in non-bull regimes — they are active in largely disjoint conditions.

**What was tried and killed in this track** (see iterations above): 1h WT
cross-up continuation in every gated form (anti-edge — 1h alts mean-revert),
structured pullback entries (thrust/dip/EMA gates made drift *worse*), long
4h capitulation @ 2R (breakeven at scale, noise pockets exposed by 6× data).

---

## Iteration F — the 70% accuracy requirement: frontier math + scale-out exits

User requirement update: ~70% accuracy. The measured frontier across ~100
configurations says win rate × payoff trade off — at fixed 2R targets the best
honest result anywhere was 51.4% (fade) and 65–66% (daily). 70% at a fixed 2R
(= +1.1R/trade expectancy) does not exist in this signal family on this data.

The legitimate structural lever: **scale-out exits** — book half at +1R, move
the stop to breakeven, let the runner ride to 2.5–3R. A trade is then
net-positive (≈ +0.5R) whenever price reaches +1R first, which is a much
higher-probability event than reaching +2R, while the runner preserves the
≥1:2 reward tail. Engine extended with partial exits (+3 fill-ordering tests;
conservative rules unchanged: stop-first, no favorable fills on limit bars).

**4h Blow-off Fade with scale-out** (same entries as the final spec above):

| exit structure | IS n | IS win% | IS avgR | IS maxDD% | OOS n | OOS win% | OOS avgR | OOS maxDD% |
|---|---|---|---|---|---|---|---|---|
| fixed 2R (reference) | 80 | 50.0 | +0.29 | 10.9 | 29 | 55.2 | +0.41 | 9.8 |
| **half @1R→BE, runner 3R** | 80 | **60.0** | +0.17 | 10.9 | 29 | **62.1** | +0.20 | 9.0 |
| half @0.75R→BE variants | 80 | 62.5 | +0.09 | 9.9–10.8 | 29 | 62.1 | −0.04 | 8.6–9.7 |

The fade tops out at **60–62% accuracy** — its probability of reaching +1R
before the stop is ~62%, and no exit engineering can exceed the entry's own
1R-first probability. **70% is not achievable on the 4h fade.**

**Daily Capitulation entries with scale-out** (entries from
[STRATEGY_RESEARCH.md](STRATEGY_RESEARCH.md), exits restructured):

| exit structure | IS n | IS win% | IS avgR | IS PF | IS maxDD% | OOS n | OOS win% | OOS avgR |
|---|---|---|---|---|---|---|---|---|
| fixed 2R (reference) | 46 | 65.2 | +0.89 | 3.36 | 8.6 | 10 | 70.0 | +1.05 |
| **half @1R→BE, runner 3R (G3)** | 46 | **73.9** | +0.64 | 3.27 | **5.8** | 11 | **81.8** | +0.59 |
| half @0.75R→BE, runner 2.5R | 46 | 76.1 | +0.48 | 2.86 | 5.1 | 11 | 81.8 | +0.41 |

### VERDICT — meeting the 70% requirement honestly

- **70%+ accuracy with a 1:3 runner and ≤6% drawdown exists: the Daily
  Capitulation Divergence with scale-out exits (G3).** 73.9% IS / 81.8% OOS,
  +0.64R/trade, PF 3.3. Its price is frequency: ~12 signals/year across 25
  coins (~1/month).
- The **4h fade** remains the frequency engine (~3/month) at **60–62%**
  accuracy with scale-out (or 51% at straight 2R with higher expectancy).
- Anyone promising 70% accuracy AND fixed 2R targets AND multiple trades a
  week from public indicators is describing a backtest artifact. The two-
  strategy portfolio above is what the data actually supports:
  **run G3 for accuracy, the fade for activity** — they trigger in disjoint
  regimes (capitulation in non-bear vs euphoria in non-bull).

**G3 exit spec (replaces the fixed target when accuracy is the priority):**
enter and stop exactly per the daily strategy; sell **half at entry + 1×risk**;
immediately move the stop on the remainder to **entry (breakeven)**; exit the
remainder at **entry + 3×risk**, the breakeven stop, or the 40-day time stop.
