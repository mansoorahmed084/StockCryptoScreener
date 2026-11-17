# Calibrating our indicators against LuxAlgo's

How close do indicators we built ourselves get to LuxAlgo's, and what moves them closer? This records what was
measured on BTC and ETH in November 2026, what changed in the code because of it, and what is still open.

Everything below is a measurement against LuxAlgo's output, not against the market. A match means "behaves like
LuxAlgo's", not "makes money". The one place profit is measured (Signals & Overlays) is called out as such.

## Summary

| Indicator | Reference we could get | Method | Result |
|---|---|---|---|
| **Technical Sentiment Composite** vs *Market Sentiment Technicals* | Public script (CC BY-NC-SA, free to use); run locally in PineTS | Exact numeric comparison, every component | **Exact** on 15m, 4h, 1d, 1w for BTC and ETH, after a warm-up. Six differences fixed in our Python and kernel, then ported to our Pine and the app's copy |
| **Price Action** vs *Price Action Concepts* | Closed, premium: no source, no numbers | Events read off Vela screenshots | Internal structure: our old rule reproduced **73%** of LuxAlgo's events, the new rule **95%** (98% within a bar). Swing structure, order blocks, gaps not measured |
| **Signals & Overlays** (our build) vs LuxAlgo's | Closed, premium | Band, signals and X marks read off Vela screenshots | Band: a modest, consistent improvement found. Signals and X marks: **do not match** under any rule tried (best F1 0.57 and 0.32) |

Tools: `calibration/` (the numba kernel and optimizer from the first stage, plus the screenshot readers below).
Data and screenshots are **not** committed (`calibration/data/` is git-ignored; see "Reproducing").

---

## 1. Technical Sentiment Composite

**Reference.** LuxAlgo's *Market Sentiment Technicals* is a public script. Its calculation part (drawing code
removed) was run over the same candles in PineTS, with one plot per component, so each of the 11 components could be
compared bar by bar, not just the final line. Candles: Binance BTCUSDT and ETHUSDT at 15m and 4h (9,999 bars each),
1d (3,378) and 1w (483).

**Starting point.** LuxAlgo's default settings are the ones we already used. So the gap was structural, not a
matter of parameters, and tuning could not have found it.

**What was different, and fixed** (Python indicator and its compiled kernel, then the Pine script and the
`myTradingView` library copy):

| Difference | Effect before |
|---|---|
| Swing points: LuxAlgo takes a bar that is at least as extreme as the bars before it and strictly more extreme than the bars after it; ours needed it to be unique | `structure` component 0.19–0.26 points off on average, up to 79 on single bars |
| A trend flip restarts one side of the running range and leaves the other; ours folded the flip bar's close into the other side | one bar of `ma` 1.7 points off |
| VWAP is of the **close**; ours used the typical price (hlc3) | VWAP component 13–16 points off |
| A session's first bar has a single sample, so its bands equal the close exactly; dividing sums back out left rounding noise that flipped the trend on 7 of 99 BTC days, with the false flip lasting up to 196 bars | the rest of the BTC VWAP error |
| VWAP anchor follows the timeframe: day (15m and below), Monday-start week (intraday above 15m), month (daily), quarter (weekly) | 18–19 points off on 4h; VWAP missing on 1d and 1w |
| A VWAP that cannot be computed counts as a neutral 50 in the average, as LuxAlgo does, instead of being left out | the average was over 10 tools, not 11 |

(Also, `common.rsi` edge cases: no down moves reads 100, no moves reads 50; the kernel mirrors it.)

**Result.** After a warm-up the combined score and all 11 components match LuxAlgo's to rounding on all eight
datasets. The score settles at about 150 bars on 15m, 110–375 on 4h, 0–280 on daily and 110–180 on weekly.

**Checked against Vela itself**, live, on the forming 15m bar: our kernel and PineTS agreed exactly; Vela's own
tooltips were within price drift (VWAP 22.88 against 22.84). Vela showed Stochastic %K as `NaN` at that moment, which
also made its sentiment meter `NaN`: a Vela quirk, not a difference in our indicator.

**Left different on purpose.** LuxAlgo shows no reading until a buy flip and a sell flip have both happened; ours
reads from the first bar. In a one-sided history LuxAlgo's can stay blank for good, and our screener must not. After
that point the two agree exactly. Pine also seeds RSI and EMA from a simple average, which leaves about 1e-4 of
difference on weekly charts for the first hundred-odd bars.

---

## 2. Price Action Concepts

**Reference.** Closed premium code: no source, and it draws labels, boxes and lines, not numbers. Its output was
measured from lossless Vela screenshots (`pac_vision.py`):

* pixels become bars by matching the candle silhouette to real candles (correlation 0.995–0.999, automatic);
* dashed structure lines give a pivot bar, a break bar and a side; labels (BOS, CHoCH, CHoCH+) are read by template
  matching;
* a candle drawn over the end of a line hides it, so line ends are snapped to real bars using the level the line was
  drawn at.

**Sample.** About 60 internal-structure events over 1,250 bars of BTCUSDT 15m (seven windows).

**Finding.** LuxAlgo's documented internal sensitivity is 5; ours used 3, with a different rule. Its rule:

* a bar is a swing high when it is higher than every bar after it (nothing required before it, so the later of two
  equal highs wins); the first such bar after a swing low registers it, so highs and lows alternate;
* a close crossing the latest registered swing from the other side breaks structure once per swing;
* CHoCH if the trend was the other way, BOS if the same way.

| Rule | Events reproduced bar for bar | Within 1 bar | Label type correct |
|---|---|---|---|
| ours before, k = 5 | 73% | 76% | 89% |
| **leg rule, k = 5** | **95%** | **98%** | **100%** |
| leg rule, k = 4 | 83% | 92% | 96% |
| leg rule, k = 6 | 83% | 86% | 98% |

Size 5 is a clear peak, matching the documented value. Our engine produced 67 events against 59 read; the ones
checked were events the reader missed, not disagreements.

**Changed.** `structure_legs` in `backend/screener/price_action.py` is now the default for internal structure
(`k_internal = 5`); `internal_engine="pivots"` keeps the earlier rule. The sweep-break setups still use the earlier
rule, because that is what they were research-tested with. The Price Action page slider defaults to 5.

**Not done.** Swing structure (LuxAlgo default 50: not shown by default, not measured), order blocks, fair value
gaps, equal highs and lows, liquidity grabs. Ours still uses the earlier rule for swing structure.

---

## 3. Signals & Overlays

Our build is documented in `freqtrade-lab/research/SIGNALS_OVERLAYS_RESEARCH.md`. LuxAlgo's is closed, so it was
read off Vela (`so_vision.py`): the **band** from its flat-coloured ribbon (both edges, between candles), the
**signals** from the green and red labels (strong "+" ones are 38 px wide, normal 29), and the **X marks** from
their exact colours (blue 40,98,255; orange 255,138,0).

**Reference sizes.** Daily BTCUSDT: 1 Jun 2021 to 15 Nov 2026, 1,994 bars, 94 signals (40 strong), 47 X marks.
4h: Dec 2023 to Mar 2024, 561 bars, 22 signals, 15 X marks. No 15m, 5m or 1m reference was captured.

### Band

* The band has two edges. The price-side edge is a ratchet (flat for long stretches, then steps); the outer line
  wiggles above it. No fixed rule fitted either edge.
* Tested and rejected: price ∓ k×ATR for ATR lengths 5 to 600; a moving average ± k×ATR (offset still varies by
  ~0.9 ATR); a constant percentage of price.
* **Best simple rule, on both timeframes:** a trailing stop on lows (up) and highs (down), flipped by a close beyond
  it, ATR length 20–50, multiplier about 3.0–3.25: **93% direction agreement on daily, 95% on 4h**, against 86% on
  daily for our current Smart Trail (close-based, ATR 14 × 4; not measured on 4h). Price is still about 1 ATR off,
  and only 15–20% of bars are within a quarter ATR, so this is an improvement, not a match.

### Signals and X marks

* Our SuperTrend-style flip, best settings: F1 **0.57** on daily (ATR 14–30, multiplier 1.75: recall 62%, precision
  53%), **0.45** on 4h. Our Autopilot (sensitivity picked by recent performance) does not help. LuxAlgo's docs call
  its signals "performance adaptive". One coincidence: our Optimal Sensitivity at the last daily bar is 10, the same
  as its dashboard; at 4h it is 12 against its 15.
* X marks: our RSI-cross rule reproduces 7–12% of LuxAlgo's. The best variants tried (RSI length and level grid,
  starting from LuxAlgo's own signals) reach F1 about 0.3. They are not a simple RSI cross.

### Backtest of the green and red signals (the only profit measure here)

Rules for every source: act at the next bar's open; green long, red short, reversing on the opposite signal; the
whole equity in the trade, no leverage; 0.06% fee per side; drawdown includes the open trade.
"Tuned" ours = ATR 14, 1.75× on daily (the setting that best matched LuxAlgo's signals, not the most profitable).

**Daily, 16 Nov 2021 to 15 Nov 2026** (buy and hold +2.7%, max drawdown −75%):

| Source | Variant | Trades | Win | PF | Return | Max DD |
|---|---|---|---|---|---|---|
| LuxAlgo | both sides | 79 | 42% | 1.13 | −12.5% | −74% |
| LuxAlgo | long only | 39 | 44% | 1.42 | +42.4% | −50% |
| Ours, default (sens 12) | both sides | 47 | 34% | 1.05 | −36.5% | −71% |
| Ours, default | long only | 23 | 39% | 1.34 | +14.4% | −46% |
| Ours, tuned | both sides | 89 | 33% | 1.21 | +9.5% | −64% |
| Ours, tuned | long only | 44 | 36% | 1.47 | +48.6% | −42% |
| Benchmark: long while above the 200-day average | | 14 | | 5.49 | **+182.7%** | −31% |

Long-only, split by period (the tuning used only the later three years):

| | Nov 2021 – Nov 2023 | Nov 2023 – Nov 2026 |
|---|---|---|
| LuxAlgo | −0.8% | +43.5% |
| Ours, default | −4.2% | +14.3% |
| Ours, tuned | +15.0% | +18.6% |
| Buy and hold | −40.5% | +72.6% |

On 4h (Dec 2023 to Mar 2024, a steady rally, buy and hold +67%) the three were within a few points: long-only
+39% to +42%, both sides +10% to +14%.

**Reading it.**

* Ours, tuned, is as good as LuxAlgo's over five years and shallower in drawdown; the default settings are weaker and
  agree with only 24% of LuxAlgo's signals (tuned: 56%).
* Both lose money when the red signals are traded as shorts. Both lag holding in the 2023–2024 rally and protect in
  2022. **Neither beats a plain 200-day-average rule**, which was not tuned.
* The "strong (+) only" rows look extreme (ours: +203% to +341%) on 5 to 10 trades: ignore them.

### Not changed

`signals_overlays.py` defaults are untouched: the research results for the 4h Smart Trail candidate depend on the
current band. Switching to the trailing-stop rule above would mean re-running that research.

---

## Limits that apply to everything above

* The reference for sections 2 and 3 is **read from pictures**. A few events may be missed or a bar out; line ends
  hidden under candles are inferred from price (the reader marks those).
* One asset at a time (BTC; ETH only in section 1), one chart zoom. Section 3's reference is BTCUSDT only.
* Sections 2 and 3 have small samples (about 60 structure events; 94 signals).
* Section 3's backtest uses signals that were partly tuned on the same data; the split table shows the part that
  was not.

## Reproducing

The screenshots live in the assistant tool's temporary folder and the reference data in `calibration/data/` (both
git-ignored), so a re-run needs fresh captures.

1. Candles: `python -m calibration.fetch_candles BTCUSDT 1d 4000 calibration/data/so/btcusdt_1d.csv`
2. Capture from Vela: BTCUSDT on a **separate chart tab**, the toolkit added, one `zoom` capture of the chart
   area per window (region about 1343 × 585, **full scale**: the `scale` option also shrinks the saved file),
   dragging the chart back ~1150 px between captures. Wait for the toolkit to finish recalculating after any
   timeframe change (its legend shows "•••" while it works).
3. List the capture files in `calibration/data/so/windows_<tf>.txt`, then
   `so_vision.read_windows(paths, candles, dx_guess)` builds the reference (pixel-to-bar fit, band, signals, X marks).
4. Score with `so_compare.py`, search settings with `so_search.py` and `so_variants.py`, backtest with
   `so_report.run_range(...)`. For Price Action: `pac_vision.py` and `pac_compare.py`.
5. Sentiment: `pine_reference.mjs` runs a Pine script over a candles CSV in PineTS (from the `myTradingView`
   project) and writes every plot; the trimmed LuxAlgo script is not committed (CC BY-NC-SA).

Gotchas met on the way: Python's `csv` writes `\r\n`, which silently broke a header lookup; `ta.vwap` in PineTS
needs volume or it returns nothing; typing text into Vela can trigger its keyboard shortcuts.
