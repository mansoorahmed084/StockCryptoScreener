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
