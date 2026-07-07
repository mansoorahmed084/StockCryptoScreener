# Crypto Relative-Strength Screener — Implementation Plan

**Author:** Planning draft
**Date:** 2026-07-08
**Status:** Proposed

---

## 1. What we are building (scope)

A self-hosted dashboard that shows, at a glance, which crypto coins are **outperforming or underperforming** their base pairs (BTC, ETH, USDT, and others) across **many timeframes simultaneously** — weekly, daily, 4h, 1h, 15m, 3m — with bullish/bearish coloring.

Core deliverables:

1. **Relative-Strength (RS) screener grid** — a table/heatmap of coins × timeframes. Each cell shows performance of e.g. `SOL/BTC` on that timeframe (bullish green / bearish red, with magnitude).
2. **Multi-base support** — the same coin measured against BTC, ETH, USDT (and configurable others), because SOL can be strong vs USDT but weak vs BTC — that divergence is the alpha.
3. **Chart view** — click a cell to open a real chart for the exact synthetic pair: `SOLUSDT`, `SOLBTC`, `SOLETH`.
4. **Custom indicators (Phase 2+)** — pluggable indicator engine, first target being **VuManChu Cipher B + Divergences** (WaveTrend, MFI, RSI/Stoch, divergence dots).
5. **Alerts (Phase 3)** — notify when a coin flips strength or an indicator fires.

### Terminology clarification (important)

There are two different concepts that both get called "relative strength":

| Term | Meaning | What you want |
|------|---------|---------------|
| **RSI** (Relative Strength *Index*) | A 0–100 momentum oscillator of a single series | Secondary / optional |
| **RS** (Relative *Strength*, a.k.a. ratio) | Performance of asset A **relative to** asset B, i.e. the `A/B` ratio and its trend | ✅ **This is the primary feature** |

Most GitHub "crypto RSI screeners" implement RSI, not RS. Your `SOL-BTC` idea is the **ratio/RS** approach — the `SOLBTC` price series *is* the relative strength series. We build directly on the ratio series and its returns/trend per timeframe.

---

## 2. Existing open-source projects — reuse assessment

I researched this first. **No single project does your exact combination** (ratio-based RS across a timeframe matrix + multi-base + VuManChu). But we can reuse several building blocks instead of writing everything from scratch.

### Reusable building blocks (recommended)

| Project | What it gives us | How we use it |
|---------|------------------|---------------|
| **[CCXT](https://github.com/ccxt/ccxt)** | Unified API to 100+ exchanges for OHLCV, tickers, websockets (Python + JS). | **Data layer.** Fetch candles for all timeframes. The backbone of the whole project. |
| **[TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts)** | 45 KB, free, no-ToS charting engine (candles + custom series). | **Chart view** for SOLUSDT/SOLBTC/SOLETH. Same engine as TradingView, embeddable. |
| **[keithorange/CryptoSuperScreener](https://github.com/keithorange/CryptoSuperScreener)** | CCXT-based multi-exchange screener with a grid of many charts + real-time filtering. | Reference architecture / possible fork for the grid-watching UX. |
| **[deepentropy/tvscreener](https://github.com/deepentropy/tvscreener)** | Python wrapper over TradingView's screener API; RSI/indicators across many intervals. | Fast MVP shortcut if we're OK depending on TradingView's data endpoints. |
| **[ktshen/screener](https://github.com/ktshen/screener)** | Relative-strength ranking for stocks + crypto trend similarity across 15m–4h. | Reference for RS ranking logic. |
| **[kukapay/crypto-indicators-mcp](https://github.com/kukapay/crypto-indicators-mcp)** | 50+ TA indicators with buy/sell/hold signals. | Indicator ideas / signal layer reference. |
| **[pandas-ta](https://github.com/twopirllc/pandas-ta)** or **[TA-Lib](https://github.com/TA-Lib/ta-lib-python)** | 130+ indicators in Python. | Indicator engine foundation (RSI, MFI, EMA, WaveTrend building blocks). |

### VuManChu Cipher B — reuse sources

VuManChu Cipher B is **open source** (originally a TradingView Pine script). Reusable ports:

- **[cipher.nanvel.com VuManChu example](https://cipher.nanvel.com/examples/vumanchu_cipher_b.html)** — Python implementation using the `cipher` backtesting library + TA-Lib.
- **[VuManChu B Divergences gist](https://gist.github.com/lughino/8bd1697e17b7940abbf242c0658cb2b2)** — reference port.
- **[Original Pine script](https://www.tradingview.com/script/Msm4SjwI-VuManChu-Cipher-B-Divergences/)** — source of truth for exact formulas (WaveTrend WT1/WT2, MFI, divergence rules) to re-implement in Python/pandas.

**Decision:** Re-implement VuManChu in our own indicator module (pandas + numpy) using the Pine script as the spec, so we control it and can run it on any timeframe/pair. Use the Python ports above to cross-check our numbers.

### Verdict

**Build a thin custom app that composes CCXT (data) + pandas-ta/custom indicators (compute) + Lightweight Charts (charts).** Don't adopt a whole framework — none fits the ratio-matrix concept. Optionally study/fork CryptoSuperScreener for the grid UX.

---

## 3. Recommended architecture

### Stack decision

Two viable paths. Recommendation: **start with Path A for a fast working MVP, then graduate to Path B** once the RS logic is proven.

**Path A — Python + Streamlit (fast MVP, 1–2 weeks to something usable)**
- Backend + frontend in one: Python, CCXT, pandas-ta, Streamlit.
- Pros: minimal code, fastest to a working RS matrix, easy for iterative research.
- Cons: charting is weaker (Plotly, not TradingView-grade); not ideal for real-time streaming UX at scale.

**Path B — FastAPI backend + React/Next.js frontend (production target)**
- **Backend:** Python FastAPI + CCXT + pandas-ta + custom indicators. Background workers poll/stream candles; Redis or DuckDB/Postgres cache.
- **Frontend:** Next.js + TradingView Lightweight Charts + a data grid (TanStack Table / AG Grid) for the RS matrix.
- **Transport:** REST for snapshots, WebSocket for live updates.
- Pros: TradingView-grade charts, real-time, scalable, clean separation.
- Cons: more upfront work.

> Recommendation: **Python everywhere.** It keeps the RS + indicator math (the hard part) in one language, and pandas/pandas-ta/TA-Lib are the strongest TA ecosystem. Do the MVP in Streamlit, reuse the exact same `screener/` and `indicators/` Python modules unchanged when you move to FastAPI + Next.js.

### Component diagram

```
                    ┌─────────────────────────────────────────┐
                    │              Exchanges                    │
                    │   (Binance, Bybit, OKX, ... via CCXT)     │
                    └───────────────┬───────────────────────────┘
                                    │ OHLCV (REST + WS)
                    ┌───────────────▼───────────────┐
                    │      Data Ingestion Layer      │
                    │  ccxt fetch_ohlcv per (sym,tf) │
                    │  rate-limit, retry, normalize  │
                    └───────────────┬────────────────┘
                                    │
                    ┌───────────────▼────────────────┐
                    │           Cache / Store         │
                    │  DuckDB or Postgres + Redis      │
                    │  candles(symbol, tf, ts, ohlcv)  │
                    └───────────────┬────────────────┘
                                    │
             ┌──────────────────────┼───────────────────────┐
             │                      │                        │
   ┌─────────▼─────────┐  ┌─────────▼──────────┐  ┌──────────▼─────────┐
   │  RS Engine        │  │  Indicator Engine  │  │  Pair/Ratio Builder │
   │  returns per tf,  │  │  VuManChu, RSI,    │  │  synth SOLBTC from  │
   │  rank vs base,    │  │  MFI, EMA, custom  │  │  SOLUSDT / BTCUSDT   │
   │  bull/bear class  │  │  (pluggable)       │  │  when no direct pair │
   └─────────┬─────────┘  └─────────┬──────────┘  └──────────┬─────────┘
             └──────────────────────┼────────────────────────┘
                                    │  JSON / WS
                    ┌───────────────▼────────────────┐
                    │        API (FastAPI)            │
                    │  /screener  /chart  /indicators │
                    └───────────────┬────────────────┘
                                    │
                    ┌───────────────▼────────────────┐
                    │   Frontend (Streamlit → Next)   │
                    │  RS matrix heatmap + chart view │
                    └────────────────────────────────┘
```

---

## 4. Core logic details

### 4.1 The pair / ratio builder (the heart of it)

Goal: get a price series for `COIN/BASE` on each timeframe.

- **Direct pair exists** (e.g. Binance lists `SOLBTC`, `SOLETH`): fetch it directly via CCXT. Best data.
- **No direct pair** (many coins only have USDT pairs): **synthesize** the ratio:
  `SOLBTC[t] = SOLUSDT[t] / BTCUSDT[t]` (align candles by timestamp per timeframe).
  This lets us measure strength vs BTC/ETH for *any* coin even without a native pair.
- Bases to support out of the box: **BTC, ETH, USDT, INR** (USDT ≈ USD-denominated performance; **INR = rupee-denominated**, the trader's home/settlement currency on CoinDCX). Make the base list configurable (add SOL, BNB, etc.).
- **INR note:** INR pairs are *native* CoinDCX order books (not Binance-mirrored), so `SOL/INR` reflects real local pricing. `SOL/INR` vs `SOL/USDT` will differ by the `USDT/INR` premium — that spread is itself useful signal for an Indian trader. Coins without a native INR pair are synthesized (`SOL/USDT × USDT/INR`).
- **Index base (synthetic):** besides single-coin bases, support an **equal-weight altcoin index** as a base. `SOL/INDEX` answers "is SOL beating the *whole alt market*," a cleaner strength read than `SOL/BTC` alone. Built cheaply from candles already pulled: index level = equal-weight average of member coins' USDT returns (BTC optionally excluded). Treat it as just another base in the matrix and filters.

### 4.2 Relative-strength computation per timeframe

For each `(coin, base, timeframe)` cell:

1. Build the ratio series `R = coin/base` on that timeframe.
2. **Performance** = % change over the lookback window for that timeframe (e.g. last N closed candles, and/or current candle vs prior).
3. **Trend / bull-bear classification**, combine a few signals for robustness:
   - Sign of ratio return over the window.
   - Price vs EMA (e.g. R above/below EMA(21) → bullish/bearish).
   - Slope of a short EMA on the ratio.
   - Optional: RS-Rating style rank (percentile of this coin's ratio-return vs all screened coins) — like IBD RS rating, useful for "top movers".
4. Output per cell: `{ change_pct, direction: bull|bear|neutral, strength_score, rank }`.

> The classification here must be **noise-filtered** — a raw sign-of-return flips constantly on fast timeframes. See §4.7 for the smoothing/threshold/hysteresis rules that produce a stable `direction` + `strength_score`.

> Design the RS metric as a pure function `rs(ratio_series, tf) -> RSResult` so it's swappable and testable.

### 4.3 Timeframe matrix

Timeframes: `1w, 1d, 4h, 1h, 15m, 3m` (configurable). Note `3m` is not native on all exchanges — resample from `1m` if needed. The screener output is a matrix:

```
             1w    1d    4h    1h    15m   3m
SOL/BTC     🟢+4  🟢+2  🔴-1  🟢+3  🔴-1  🟢+1
SOL/ETH     🟢+3  🟢+1  🔴-1  🟢+2  🟢+1  🔴-1
SOL/USDT    🟢+6  🟢+3  🟢+1  🟢+4  🔴-1  🟢+2
ETH/BTC     🔴-2  🔴-1  🔴-2  🟢+1  🔴-1  🔴-1
...
```

"Full stack alignment" (all timeframes green for a coin/base) is a strong signal and should be highlighted / sortable.

### 4.4 Indicator engine (VuManChu etc.)

- Define an `Indicator` interface: `compute(df: DataFrame) -> DataFrame/overlays` + metadata (panes, series, markers).
- Ship built-ins: EMA, RSI, MFI, WaveTrend (WT1/WT2), and **VuManChu Cipher B + Divergences** composed from those.
- VuManChu divergence: detect pivots on the oscillator vs price, flag regular/hidden bull/bear divergence (green/red dots, gold circles per the original script).
- Indicators run per `(pair, timeframe)` and feed both the chart (overlays/markers) and optionally the screener (e.g. "coins with a fresh VuManChu bullish divergence on 1h").

### 4.5 Chart view

- Lightweight Charts candlestick for the selected synthetic/real pair (`SOLUSDT`, `SOLBTC`, `SOLETH`).
- Overlays (EMAs) on the main pane; oscillators (WaveTrend/VuManChu) in a lower pane; divergence markers.
- Timeframe switcher; symbol switcher; base switcher.

### 4.6 Filter / query engine (multi-condition AND/OR)

This is what turns a static heatmap into a **scanner**. The user wants to combine conditions, e.g. *"SOL outperforming BTC on 1h **AND** 1d **AND** 1w"* — and more generally scan the whole market for coins that satisfy a stack of conditions at once.

#### Condition model

A **condition** is one testable statement about a `(coin, base, timeframe)` cell:

```
Condition = {
  subject:    "SOL" | "*"          # a specific coin, or "any coin" for market scans
  base:       "BTC" | "ETH" | "USDT" | ...
  timeframe:  "1w" | "1d" | "4h" | "1h" | "15m" | "3m"
  metric:     "direction" | "strength" | "change_pct" | "rs_rank" | "price_vs_ema" | "quote_volume_24h" | "sector_rank" | "indicator"
  operator:   ">" | ">=" | "<" | "==" | "is"
  value:      "bull" | 1.5 | 0.0 | 90 | "vumanchu_bull_div" ...
}
```

Examples of single conditions:
- `SOL / BTC / 1h / direction is bull` → "SOL outperforming BTC on 1h"
- `SOL / BTC / 1d / change_pct >= 2` → "up ≥2% vs BTC on the daily"
- `* / BTC / 4h / rs_rank >= 90` → "any coin in the top 10% strength vs BTC on 4h"
- `SOL / USDT / 1h / indicator is vumanchu_bull_div` → "fresh VuManChu bullish divergence"

#### Combining conditions (the AND part)

A **filter** is a boolean expression over conditions. Support at minimum:

- **AND** (all must be true) — the primary use case.
- **OR** (any true) and **NOT** (negate) — nice-to-have, added via a simple group structure.

```
Filter = {
  logic: "AND" | "OR",
  conditions: [ Condition, ... ],
  groups:     [ Filter, ... ]     # nested groups → arbitrary AND/OR trees
}
```

The requested example becomes one AND filter with three conditions differing only by timeframe:

```json
{
  "logic": "AND",
  "conditions": [
    { "subject": "SOL", "base": "BTC", "timeframe": "1h", "metric": "direction", "operator": "is", "value": "bull" },
    { "subject": "SOL", "base": "BTC", "timeframe": "1d", "metric": "direction", "operator": "is", "value": "bull" },
    { "subject": "SOL", "base": "BTC", "timeframe": "1w", "metric": "direction", "operator": "is", "value": "bull" }
  ]
}
```

#### Evaluation

- Because the RS engine already computes a value for **every** `(coin, base, timeframe)` cell (§4.2), the whole screener output is effectively a tidy table: `rows = (coin, base, timeframe, direction, change_pct, rs_rank, indicator_flags…)`.
- A filter is then just a **predicate over that table**. Implementation options, cheapest first:
  1. **pandas mask** — build a boolean mask per condition and `&`/`|` them together. Fast, simple, perfect for the MVP.
  2. **DuckDB SQL** — compile the filter tree to a `WHERE` clause and run it against the candle/metrics store. Scales to full-market scans and is easy to persist.
- When `subject = "*"`, the engine groups by coin and returns every coin where **all** AND-conditions hold (each condition may target a different timeframe/base). This is how "scan the market for coins stacked bullish vs BTC on 4h+1d+1w" works.
- Output: the filtered list of coins (plus which conditions matched), fed back into the same matrix/heatmap view — now showing only matches.

#### Common presets to ship

Give users one-click starting points (they're just saved filters):

- **Full-stack bull** — bullish vs BTC on `1h AND 4h AND 1d AND 1w` (timeframe alignment).
- **Higher-TF-with-pullback** — bull on `1w AND 1d` **AND** bear on `1h` (buy-the-dip in an uptrend).
- **Multi-base strength** — outperforming `BTC AND ETH AND USDT` on `1d` (true broad strength).
- **Fresh momentum** — `rs_rank >= 90` on `4h` **AND** VuManChu bull divergence on `1h`.

#### UI

- A **filter builder**: rows of `[coin][base][timeframe][metric][operator][value]`, an AND/OR toggle, "+ add condition", and grouping.
- A quick-add shortcut for the common case: pick a coin + base once, then check the timeframes to AND together and a single direction — generates the 3–4 conditions automatically.
- **Save / name / re-run** filters; show a live match count; sort matches by aggregate strength.

#### Data model note

Persist filters as JSON (the `Filter` tree above). This keeps them portable across the Streamlit MVP and the later FastAPI/Next.js app, shareable, and directly compilable to either a pandas mask or a DuckDB `WHERE` clause.

### 4.7 Defining "outperformance" robustly (noise filtering)

A raw sign-of-return test on the `COIN/BASE` ratio is far too noisy — on 3m/15m it flips every few candles and the screener becomes useless. Outperformance must be a **smoothed, threshold-gated, volatility-aware** signal so that only *meaningful* strength registers as bull/bear. Six layers, applied together:

**1. Closed candles only (no repaint).** Evaluate on the last *closed* candle, never the still-forming one. Prevents a cell from flickering intra-candle. Optionally show the live candle separately as "provisional".

**2. Deadband / neutral zone → three states, not two.** Introduce a threshold `θ` so a cell is `bull` / `bear` / **`neutral`**. Anything inside `±θ` is neutral (grey), not a weak bull/bear. This alone removes most chop and makes AND-filters meaningful ("all timeframes *actually* bullish", not "barely positive").

**3. Volatility-normalized threshold (the key idea).** A fixed % threshold can't work across 3m and 1w, or across BTC and a memecoin. Normalize the move by the ratio's own volatility so the threshold self-adjusts:

```
z = ratio_return_over_window / stdev(ratio_returns, lookback)     # a z-score / how many sigma
# or, ATR-style:
score = (ratio.close - ratio.EMA(n)) / ATR(ratio, n)
```

Classify by `z`/`score` vs a band (e.g. `> +1.0` = bull, `< -1.0` = bear, else neutral). Now "outperformance" means *statistically significant* strength on any timeframe or coin, with one shared band.

**4. Smoothing the signal.** Reduce jitter before classifying:
- Smooth the ratio itself with a short **EMA/HMA** (Hull MA reacts fast with less lag) — especially useful because a *synthesized* ratio (`SOLUSDT/BTCUSDT`) can be noisier than a native pair.
- Trend gate: `bull` requires ratio **above** its EMA(n) **and** EMA slope > 0 (and mirror for bear). Combine slope + position + normalized momentum.

**5. Persistence / confirmation.** Require the condition to hold for **k consecutive closed candles** (e.g. `k=2`) before the cell flips. Kills one-bar spikes.

**6. Hysteresis (debounce the boundary).** Use two thresholds so a cell doesn't oscillate around a single line: enter `bull` at `+θ_in`, but only leave `bull` when it drops below `−θ_out` (with `θ_out < θ_in`). State is "sticky" until genuinely reversed.

#### Recommended default: a composite strength score

Combine the sub-signals into one **strength score** per cell, roughly in `[-3, +3]`, then band it:

```
strength =  w1 * sign_and_size(z_return)        # volatility-normalized momentum
          + w2 * position_vs_ema(ratio, n)      # above/below trend line
          + w3 * sign(ema_slope)                # trend direction
apply persistence (k bars) + hysteresis (θ_in/θ_out)

direction = bull   if strength >=  θ_in
            bear   if strength <= -θ_in
            neutral otherwise
```

The screener shows the score magnitude (how strong), the direction (color), and neutral cells are visibly greyed. Filters (§4.6) then get a real `metric: "strength"` with a numeric operator, so users can demand e.g. `strength >= 1.5` rather than a bare direction — the noise threshold becomes a first-class, tunable filter input.

#### Per-timeframe defaults (starting points, all tunable in config)

| Timeframe | EMA len | Vol lookback | Neutral band `±θ` (z) | Persistence `k` |
|-----------|---------|--------------|-----------------------|-----------------|
| 3m        | 20      | 100          | 1.2                   | 3               |
| 15m       | 20      | 96           | 1.0                   | 2               |
| 1h        | 21      | 90           | 1.0                   | 2               |
| 4h        | 21      | 90           | 0.8                   | 2               |
| 1d        | 20      | 60           | 0.8                   | 1               |
| 1w        | 20      | 52           | 0.7                   | 1               |

Faster timeframes get **wider** neutral bands and **more** persistence (they're noisier); higher timeframes trust the move sooner. These are defaults to calibrate against real data in Phase 1, not final values.

> Keep the classifier a single pure function `classify(ratio_series, tf, params) -> {direction, strength, score_parts}` so thresholds live in config, it's unit-testable with golden series, and the same logic feeds both the matrix and the filter engine.

### 4.8 Universe selection & liquidity gating

Which coins get scanned — and keeping untradeable ones out.

- **Universe:** configurable — a fixed watchlist, or auto **top-N by 24h quote volume** on CoinDCX (refreshed daily). New listings / delistings picked up from the Market Details map (§5.1).
- **Liquidity gate (hard):** exclude any `(coin, base)` pair below a minimum 24h quote volume / average candle volume, so RS on thin books never surfaces a "winner" you can't actually enter or exit. Re-checked per pair — a coin can be liquid vs USDT but dead vs INR.
- Exposed as a **first-class filter metric** (`quote_volume_24h >= X`) so scans can tighten/loosen liquidity per query.
- **Synthesized-ratio guard:** if either leg is below the liquidity floor, mark the cell `unknown` rather than classify it.

### 4.9 Narrative / sector grouping

Crypto rotates by narrative; aggregate RS per sector shows *where the money is flowing*.

- Tag each coin with one or more **sectors** (L1, L2, DeFi, Memes, AI, DePIN, RWA, Gaming, …) via a small maintained mapping (config/JSON, optionally seeded from CoinGecko categories).
- Compute **sector RS** = aggregate (median/mean) strength of member coins vs a base, per timeframe → a sector heatmap and a `sector_rank` metric.
- Enables "which narrative is strongest on the daily" and filters like "coins in a top-ranked sector that are *also* individually bull vs BTC."

### 4.10 Market-regime context (BTC dominance / total-cap)

Frames every RS reading so signals aren't misread.

- Header widget: **BTC dominance**, **total market-cap** trend, and BTC's own USDT trend across timeframes → a simple **risk-on / risk-off / BTC-season** label.
- Interpretation aid: in a hard BTC downtrend, "green vs BTC" often just means "falling less" — surface the regime so that's obvious.
- Optional (CoinDCX **futures**): per-coin **funding rate** and **open interest** as extra positioning signal.

### 4.11 Signal validation / backtest harness

Prove a setup works before trusting it.

- Given a filter/preset, replay history: each time it fired on a `(coin, base, tf)`, measure the ratio's forward return over the next N candles → **hit rate, avg/median forward return, distribution**.
- Uses: (a) validate presets like "all-TF aligned bull," and (b) **calibrate the §4.7 noise thresholds** against realized outcomes instead of eyeballing — guards against overfitting the filters.
- Keep it lightweight (vectorized pandas over cached candles) — signal sanity-checking, not a full trading backtester.

### 4.12 Alerts & notifications

The payoff — turns a dashboard you stare at into something that taps you on the shoulder.

- Trigger on: a preset gaining a **new match**, a stack **aligning** or **flipping**, or an indicator (VuManChu divergence) firing.
- Channels: **Telegram** (primary — simple bot), Discord webhook, optional email. Message carries coin, base, timeframe(s), strength, and a chart link.
- **De-dupe / cooldown** so a wobbling signal doesn't spam; alert only on state *changes* of confirmed (closed-candle, §4.7) signals.

### 4.13 Signal history / journal

Persist every fired signal for later review.

- Log `(timestamp, coin, base, tf, preset, strength, direction)` to the store on each fire.
- Lets you review "what happened after this setup," compute per-preset hit rates live over time, and build (or withdraw) trust in each filter.
- Feeds the backtest harness (§4.11) with real forward outcomes.

---

## 5. Data & performance considerations

- **API load:** `coins × bases × timeframes` grows fast. 50 coins × 3 bases × 6 tf = 900 series. Mitigate by:
  - Fetching only USDT pairs from the exchange and **synthesizing** BTC/ETH ratios locally (so you fetch ~50 USDT series + BTCUSDT + ETHUSDT, not 900).
  - Caching candles; only fetch the newest candles incrementally.
  - Respecting CCXT `enableRateLimit`; batch/stagger requests; use websockets (ccxt.pro or exchange WS) for live top-of-book/candles.
- **Storage:** DuckDB (embedded, great for candle analytics) for MVP; Postgres + TimescaleDB if multi-user/scale.
- **Refresh cadence:** higher timeframes recompute infrequently (1d/1w every few min is fine); 3m/15m near real-time. Schedule per-timeframe.
- **Exchange choice:** default Binance (deep pairs) via CCXT; make it configurable. Handle geo/availability.

### 5.1 Exchange adapters (CCXT + CoinDCX)

Wrap every data source behind one `ExchangeAdapter` interface (`fetch_markets`, `fetch_ohlcv(symbol, tf, since, limit)`, normalize to a common candle frame). Two adapters ship:

- **`CoinDcxAdapter`** (custom, thin REST) — **PRIMARY / default**, the exchange the user actively trades on (India). Gives trade-venue parity incl. native INR markets.
- **`CcxtAdapter`** (secondary) — Binance/Bybit/OKX/etc. for deeper pairs / cross-checking. Enabled via config when needed.

**CoinDCX specifics** (researched):
- **Public candles, no auth needed:** `GET https://public.coindcx.com/market_data/candles?pair={PAIR}&interval={TF}&limit={N}`. Returns OHLCV sorted newest-first; default limit 500. A screener needs *only* this public endpoint — **no API key/secret required**. (Keys, HMAC-signed, are only needed for private order/balance calls, which this project doesn't do.)
- **Intervals (verified live 2026-07):** the public candles endpoint only actually
  returns data for **`1m`, `15m`, `1h`, `1d`** (the documented longer list 422s).
  So the screener fetches those four and **resamples everything else** — `3m` from
  `1m`, `4h`/`2h` from `1h`, `1w`/`3d` from `1d`, `30m` from `15m`. Handled in
  `OHLCVService.source_for()`; max 1000 candles/request.
- **Pairs / naming (two market families):**
  - **`B-` = Binance-sourced** crypto markets, e.g. `B-SOL_USDT`, `B-SOL_BTC`. So `SOL/USDT` and `SOL/BTC` are **native** here.
  - **`I-` = CoinDCX native INR** markets, e.g. `I-SOL_INR`, `I-BTC_INR`, `I-USDT_INR` — real local order books, used for the **INR base**.
  - **`SOL/ETH` has no market → synthesize** (`SOL/USDT ÷ ETH/USDT`); coins with no native INR pair → synthesize (`SOL/USDT × USDT/INR`). §4.1 ratio builder handles both.
  - **Don't hardcode symbol strings** — call the **Market Details** endpoint (`/exchange/v1/markets_details`) once at startup to build a `(coin, base) → pair/ecode` map, since available markets change over time.
- **Not in mainline CCXT:** the CoinDCX CCXT PR (#22708) was closed unmerged; only a community `ccxt-unmerged` port exists. Therefore implement `CoinDcxAdapter` as a **small direct REST client** (requests/httpx) rather than depending on CCXT for it.
- **Caveat:** `B-` data mirrors Binance, so choosing CoinDCX vs Binance changes little about the *numbers*; its value is matching the **exact venue/pairs the user trades**. INR-quoted markets exist too if the user wants USD/INR-denominated performance, but BTC/USDT bases are the relevant ones here.

Config selects the active adapter per run; the RS engine, filters, and indicators are adapter-agnostic (they consume normalized candles).

### 5.2 Data quality & integrity

Screeners live or die on clean data — especially with *synthesized* ratios.

- **Missing candles / gaps:** detect and forward-fill or flag; never silently misalign two series.
- **Stale data:** if the latest candle is older than a per-timeframe freshness threshold (exchange downtime, dead pair), mark the cell `unknown` and don't classify.
- **Synthesized-ratio hygiene:** align both legs strictly by timestamp; drop unmatched candles; if either leg is NaN or zero-volume, the ratio is `unknown`.
- **Listings / delistings:** rebuild the CoinDCX `(coin, base) → pair` map on a schedule; drop vanished pairs, pick up new ones.
- **Candle boundaries / timezone:** be explicit about UTC vs exchange time for daily/weekly opens (matters for the INR daily close); align all series to the same boundary before dividing.

### 5.3 Ops, hosting & secrets

- **Always-on:** the poller must survive Windows sleep/reboot. For continuous 3m/15m refresh + alerts, run it as a small **always-on VPS service** (or a kept-alive/scheduled local process); local-only is fine for manual daytime use.
- **Scheduling:** per-timeframe refresh cadence — fast TFs near-real-time, `1d`/`1w` every few minutes.
- **Secrets:** read-only public data needs **no keys** today. The moment order execution is added, keep API key/secret in `.env` (git-ignored), never in code; HMAC-sign per CoinDCX private-endpoint rules.
- **Observability:** structured logs + basic health metrics for the long-running poller; retry/backoff on CoinDCX rate limits.

---

## 6. Suggested project structure

```
crypto-screener/
├── backend/
│   ├── data/
│   │   ├── adapters/
│   │   │   ├── base.py         # ExchangeAdapter interface (fetch_markets/fetch_ohlcv)
│   │   │   ├── ccxt_adapter.py # Binance/Bybit/OKX/... via CCXT (default)
│   │   │   └── coindcx.py      # thin REST client for public.coindcx.com (no auth)
│   │   ├── ohlcv.py            # fetch/resample candles per tf (incl. 3m from 1m)
│   │   ├── quality.py         # gap/stale/NaN detection, timestamp alignment
│   │   └── pairs.py           # direct vs synthesized ratio builder (incl. index base)
│   ├── screener/
│   │   ├── rs.py              # relative-strength metric + noise-filtered classification
│   │   ├── matrix.py         # build coins × bases × tf matrix
│   │   ├── universe.py       # watchlist / top-N by volume + liquidity gating
│   │   ├── sectors.py        # narrative tags + sector RS aggregation
│   │   ├── regime.py         # BTC dominance / total-cap / risk-on-off label
│   │   └── filters.py        # condition + filter tree → pandas mask / DuckDB WHERE
│   ├── indicators/
│   │   ├── base.py           # Indicator interface
│   │   ├── wavetrend.py
│   │   ├── vumanchu.py       # Cipher B + divergences
│   │   └── common.py         # ema, rsi, mfi
│   ├── signals/
│   │   ├── backtest.py       # replay presets → forward-return stats
│   │   └── journal.py        # persist fired signals for review
│   ├── alerts/
│   │   ├── dispatcher.py     # de-dupe/cooldown, state-change detection
│   │   └── telegram.py       # Telegram bot (+ discord/email later)
│   ├── store/                # duckdb/postgres + redis cache; signal journal table
│   ├── api/                  # FastAPI routes (Phase 2)
│   └── config.py            # coins, bases, timeframes, exchange, thresholds, sectors
├── frontend/                 # streamlit app (MVP) → next.js (Phase 2)
├── tests/                    # unit tests for rs.py, vumanchu.py (golden values)
├── requirements.txt
├── docker-compose.yml
└── README.md
```

---

## 7. Phased roadmap

### Phase 0 — Setup (0.5 day)  ✅ **DONE**
- Repo, `git init`, venv, `requirements.txt` (ccxt, pandas, pandas-ta, streamlit, duckdb).
- Config file listing coins, bases (**BTC/ETH/USDT/INR**), timeframes, and active exchange (**default: `coindcx`**).
- Build the CoinDCX `(coin, base) → pair` map from the Market Details endpoint at startup.

### Phase 1 — Data + RS engine (core, ~3–5 days)  ✅ **DONE**
- CCXT OHLCV fetch with caching + incremental updates.
- Ratio builder (direct + synthesized).
- `rs.py` metric + **noise-filtered** bull/bear/neutral classification (§4.7: closed-candle, vol-normalized threshold, smoothing, persistence, hysteresis); unit tests with golden series.
- **Calibrate** the per-timeframe bands/persistence (§4.7 table) against real historical data — check flip frequency vs signal quality before locking defaults.
- **Universe + liquidity gating** (§4.8) and **data-quality** handling (§5.2: gaps, stale→unknown, ratio hygiene).
- CLI/notebook that prints the RS matrix for a coin list.

### Phase 2 — Screener dashboard MVP + filter engine (Streamlit, ~4–6 days)  ✅ **DONE**
- RS matrix as a color-coded heatmap/table (coins × timeframes, per base tab).
- **Multi-condition filter engine (§4.6):** condition model + AND/OR evaluation via pandas mask; filter-builder UI; the "SOL bull vs BTC on 1h AND 1d AND 1w" case and market-wide `*` scans; ship the preset filters; save/name/re-run.
- Sorting (e.g. "all-green stacks", top movers), auto-refresh.
- **Sector/narrative RS** heatmap (§4.9), **market-regime header** (§4.10: BTC dominance / total-cap), and the **index base** (§4.1) as a scan target.
- Basic chart panel (Plotly or embed Lightweight Charts) for a clicked pair.

### Phase 3 — Real charts + indicators (~1–2 weeks)  ✅ **DONE**
- Integrate TradingView Lightweight Charts (SOLUSDT/SOLBTC/SOLETH), tf switcher.
- Indicator engine + EMA/RSI/MFI/WaveTrend.
- **VuManChu Cipher B + Divergences** implemented and validated against the Pine script / Python ports.
- Show indicators on chart; optionally surface indicator signals in the screener.
- **Alerts** (§4.12: Telegram/Discord on match / align / flip) + **signal journal** (§4.13).
- **Backtest / validation harness** (§4.11) to validate presets and recalibrate the §4.7 thresholds against forward returns.

### Phase 4 — Production app (optional, ~2–3 weeks)  ✅ **DONE**
- Split into FastAPI backend + Next.js frontend; WebSocket live updates.
- Postgres/Timescale, background workers, dockerized deploy.

### Phase 5 — Extras & polish  ✅ **DONE**
- (Core alerts, journal, and backtest now land in Phase 3.)
- **CoinDCX futures** funding-rate / open-interest signals (§4.10), extra alert channels, watchlists, persisted user settings, more bases/sectors, always-on VPS deployment (§5.3).

---

## 8. Key libraries / dependencies

- **Data:** `ccxt` (and `ccxt.pro` for websockets if needed); `httpx`/`requests` for the custom **CoinDCX** REST adapter (§5.1)
- **Compute:** `pandas`, `numpy`, `pandas-ta` (or `TA-Lib`)
- **Store:** `duckdb` (MVP) → `postgres` + `timescaledb`, `redis`
- **MVP UI:** `streamlit`, `plotly`
- **Prod UI:** `fastapi`, `uvicorn`, `next.js`, `lightweight-charts`, `@tanstack/react-table` or AG Grid
- **Alerts / scheduling:** `python-telegram-bot` (or plain bot API via `httpx`), `apscheduler` for per-timeframe refresh
- **Testing:** `pytest`

---

## 9. Open questions to confirm before building

1. **Exchange(s):** ✅ **Decided — CoinDCX is primary/default** (§5.1); public candles, no key, `B-` (Binance-sourced) crypto pairs + `I-` native INR pairs, 3m resampled from 1m. CCXT/Binance kept as an optional secondary adapter for cross-checks.
2. **Coin universe:** fixed watchlist, top-N by volume, or full market scan?
3. **Bases:** ✅ **Decided — BTC / ETH / USDT / INR** out of the box (INR = native CoinDCX). Add SOL/BNB/others later via config.
4. **"Performance" definition per cell:** the plan now defaults to a **noise-filtered composite strength score** with a neutral band (§4.7). Confirm the exact bands/persistence per timeframe once we calibrate on real data, and whether to also surface raw % change alongside it.
5. **Real-time vs periodic:** how fresh must 3m/15m be? (Drives websockets vs polling.)
6. **Deployment:** local desktop use only, or an always-on VPS (§5.3) for continuous fast-TF refresh + alerts?
7. **Universe:** fixed watchlist, or auto top-N by 24h volume — and what liquidity floor (§4.8)?
8. **Sector taxonomy:** hand-maintained tag list, or seed from CoinGecko categories (§4.9)?
9. **Alert channel:** Telegram to start (§4.12)? (Need a bot token + chat ID.)

---

## 10. Immediate next steps

1. Confirm the answers in §9 (especially exchange, coin universe, and cell metric).
2. Scaffold `crypto-screener/` per §6 and pin `requirements.txt`.
3. Build Phase 1: CCXT fetch + ratio builder + `rs.py`, print a real `SOL/BTC` matrix across all six timeframes to validate the concept end-to-end before any UI.

---

### Sources
- [CCXT](https://github.com/ccxt/ccxt) · [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts) · [keithorange/CryptoSuperScreener](https://github.com/keithorange/CryptoSuperScreener) · [deepentropy/tvscreener](https://github.com/deepentropy/tvscreener) · [ktshen/screener](https://github.com/ktshen/screener) · [kukapay/crypto-indicators-mcp](https://github.com/kukapay/crypto-indicators-mcp) · [pandas-ta](https://github.com/twopirllc/pandas-ta) · [TA-Lib](https://github.com/TA-Lib/ta-lib-python)
- VuManChu: [Pine source](https://www.tradingview.com/script/Msm4SjwI-VuManChu-Cipher-B-Divergences/) · [cipher.nanvel Python example](https://cipher.nanvel.com/examples/vumanchu_cipher_b.html) · [B Divergences gist](https://gist.github.com/lughino/8bd1697e17b7940abbf242c0658cb2b2)
- CoinDCX: [API docs](https://docs.coindcx.com/) · [Candles help](https://coindcx.com/api/help/Market%20Data%20on%20CoinDCX%20API/Candles) · [REST API reference](https://coindcx-official.github.io/rest-api) · [CCXT PR #22708 (closed, unmerged)](https://github.com/ccxt/ccxt/pull/22708)
