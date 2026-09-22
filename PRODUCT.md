# Crypto Screener — Product Description

A self-hosted crypto dashboard (Streamlit). It answers four questions:

1. **Which coins are stronger or weaker than BTC** (or BTC dominance), on every
   timeframe from 1 hour to 1 month?
2. **Where are the liquidity zones** — the prices where leveraged traders would
   be liquidated — and which way is price likely to be pulled next?
3. **What does the chart show** — trendlines, flat levels, Fibonacci, chart
   patterns and daily order blocks, drawn automatically?
4. **Which coins have a pattern breaking out right now**, on any timeframe?

It needs no API keys. Everything below is a read of market data, not
financial advice.

Run it:

```bash
.venv/Scripts/python.exe -m streamlit run frontend/streamlit_app.py
```

Then open http://localhost:8501 and pick a page in the sidebar.

| Page | URL | What it is for |
|---|---|---|
| Main screener | `/` | The original relative-strength matrix vs BTC, ETH, USDT, INR and an alt index |
| BTC Strength | `/BTC_Strength` | Coins vs BTC or BTC.D on 1h–1M, plus each coin's trend |
| Liquidation Heatmap | `/Liquidation_Heatmap` | Estimated liquidation zones, plus a short-term market read |
| Chart Patterns | `/Chart_Patterns` | Auto-drawn lines, Fibonacci, patterns and daily order blocks on one chart |
| Pattern Scanner | `/Pattern_Scanner` | Triangles and wedges across many coins and timeframes |

---

## 1. BTC Strength page

**Question it answers:** is this coin beating BTC right now, and on which
timeframes?

### Measure against BTC or BTC.D
A switch at the top of the sidebar picks the benchmark.

- **vs BTC** — each coin is measured on its COIN/BTC price, built as
  COIN/USDT ÷ BTC/USDT. BTC cannot be measured against itself, so its row
  shows BTC dominance instead.
- **vs BTC.D** — each coin, BTC included, is measured on its USDT price ÷
  BTC dominance. A coin is "strong" when it rises faster than BTC's share of
  the market. (Coin dominance ÷ BTC dominance would cancel back to COIN/BTC,
  so the price is used.) In a rising market almost every coin beats BTC.D.

### What each cell shows
- **Strength (default):** the ratio run through the screener's noise-filtered
  classifier on closed candles. ▲ stronger, ▼ weaker, · no clear edge. The
  colour always matches the arrow (blue stronger, red weaker); the number is
  how strong. **"Turning"** means the newest reading points the other way but
  the filter has not flipped yet.
- **% vs benchmark:** how much the coin beat or lagged over the last 1h, 4h,
  24h, 7d or 30d, up to the live price.

### Trends
Short, medium and long trend of every coin, of **BTC (BTC/USDT)** and of
BTC.D: the last closed daily candle against the 20, 50 and 200-day EMA. Up =
above a rising EMA, down = below a falling one, otherwise flat.

### Other parts of the page
- Header: BTC.D now (CoinGecko), BTC trend, BTC.D trend, and a one-line
  market read ("alts are taking share from BTC" etc.).
- **"Coins stronger than BTC"** per timeframe, with the **names** of those
  coins listed under each count, strongest first.
- A bar chart of the % beat or lag over a chosen window.
- A full table of every coin, sortable.

### Which coins
- **Top by market cap:** 25, 50, 100, 200, 300 or 500. These are the biggest
  coins on CoinGecko that CoinDCX also lists, without stablecoins and
  wrapped tokens. If CoinGecko rate-limits, the list is topped up by CoinDCX
  24h volume.
- **My watchlist:** your own saved lists (see below).
- **Config list:** the watchlist in `config.yaml`.

Sort by all timeframes or by one, weakest first if wanted, and choose how
many rows the chart shows. 500 coins take about a minute (a progress bar
shows); the result is kept for 5 minutes, and switching BTC ↔ BTC.D reuses
the downloaded candles.

### Custom watchlists
Sidebar → **Edit my watchlists**: create, rename or delete named lists. Pick
coins from every CoinDCX USDT coin, or paste symbols — TradingView tickers
like `BINANCE:SOLUSDT`, `SOLUSDT.P`, `SOL/USDT` all work. Coins CoinDCX does
not list are flagged. Lists are saved in `data_cache/watchlists.json`
(gitignored, kept by Docker).

---

## 2. Liquidation Heatmap page

**Question it answers:** where would leveraged traders get liquidated, and
where is price likely to be pulled?

### The model (the CoinGlass method)
No exchange publishes liquidation prices, so they are estimated from free
Binance futures data, candle by candle:

1. Open interest rose by X dollars → X of new positions opened near the
   candle's VWAP. The taker-buy share of the candle's volume splits it into
   longs and shorts.
2. Each side is spread over 10x / 25x / 50x / 100x leverage (weights in
   `config.yaml` → `liquidation`). Each lands at its liquidation price,
   slightly early for the maintenance margin.
3. Open interest fell → every open level shrinks by the same share.
4. Price crossed a level → those positions are gone, the level is wiped.

Bright bands on the heatmap are the big clusters ("liquidity zones").

### What the page shows
- The heatmap over time with the price line, for BTC and the top 10 coins by
  market cap, or any Binance USDT perpetual. Ranges: 12h, 1d, 3d, 7d, 30d
  (Binance keeps 30 days of open interest).
- A profile of what is open **now** at each price, with the biggest zones
  labelled, and liquidations above vs below.
- The 3 biggest zones above price (short liquidations) and below (long
  liquidations), with distance and size.
- An overview table of BTC and the top 10; a click on a row opens that coin.

### Market read panel
At the top of the page: a rules-based short-term lean for BTC and the top 10,
from 1h candles, open interest, funding and the 1d / 7d liquidation maps.
Each rule adds to a score:

| Rule | Score |
|---|---|
| 1h trend: close above a rising EMA20, above EMA50 (mirror: below, falling) | +1 / −1 |
| Nearest pull: the side whose nearest big cluster is bigger per % of distance, by 1.5× or more | +1 above / −1 below |
| 7d map holds under half as much liquidity above as below (or over twice as much) | −0.5 / +0.5 |
| 1h RSI over 70 / under 30 | −0.5 / +0.5 |
| Open interest +15% in 24h after a 5% move (pump / dump) | −0.5 / +0.5 |
| Funding over 0.03% / under −0.01% | −0.5 / +0.5 |

Score ≥ 1 is **up**, ≤ −1 **down**. When the 1h trend and the nearest pull
disagree and the rest is small, the lean is **"dip first, then up"** (or
"bounce first, then down"). Confidence never goes above medium, and it is
always low when the clusters near the price hold under $5M. The panel shows a
summary paragraph, a 48h sparkline per coin, the lean, the confidence, the
nearest cluster each side and the reasons. It refreshes every 5 minutes.

---

## 3. Chart Patterns page

**Question it answers:** what would a trader draw on this chart?

Any Binance USDT perpetual, on 15m, 1h, 4h or 1d, 100–1000 candles. Each
layer can be switched off.

- **Trendlines.** Every pair of swing lows (support) or swing highs
  (resistance) is a candidate. A line survives if no candle closes through
  it; wicks may poke through, as on a hand-drawn chart. Lines are ranked by
  touches, span, recency and closeness to the price. A line broken in the
  last few candles stays on the chart, **dotted**, so fresh breakouts show.
- **Flat levels.** Swing highs and lows at one price, 2+ touches, labelled
  "R 0.04141 ×2".
- **Fibonacci** (yellow). Retracements 0.236–0.786 and extensions 1.272 /
  1.618 of the biggest leg in view; the 0.5–0.618 band is shaded.
- **Patterns** between the best support and resistance lines: ascending,
  descending and symmetrical triangles, rising and falling wedges, channels,
  ranges and broadening shapes — plus double tops and bottoms with their
  necklines. Each shows its status (inside / broke up / broke down) and
  targets one pattern-height past the breakout.
- **Daily order blocks** (purple zones, on every timeframe). Supply: the last
  up candle before a sharp daily drop that broke the recent low. Demand: the
  last down candle before a sharp daily rally that broke the recent high.
  Each is marked fresh, tested ×N, or **flipped** (price later closed through
  it, so it now works the other way).
- **VuManChu Cipher B** pane, styled like TradingView's: green / red money
  flow, white WT1, blue WT2, sell, buy and divergence dots, lines at ±53 and
  ±60. Its maths is the repo's port of the Pine script.
- Under the chart: a plain-language summary of the pattern, and tables of the
  lines, levels, Fibonacci prices and order blocks with their distances.

Example: on S/USDT 15m it found the ascending triangle a trader drew by hand
(flat top 0.04135 over rising support) and, on the daily, the supply zone at
0.0391–0.0413.

---

## 4. Pattern Scanner page

**Question it answers:** which coins have a triangle or wedge breaking out
right now?

- Coins: the top 10–200 by market cap, or a saved watchlist.
- Timeframes: 15m, 1h, 4h, 1d.
- Patterns: by default ascending and descending triangles and falling and
  rising wedges; double tops / bottoms, symmetrical triangles, channels and
  ranges can be added.
- Each row: coin, timeframe, pattern, a plain **setup line** ("Broke up,
  fresh; daily supply here", "Near breakout: 0.1% to the upper line",
  "Broke down, 3.7% past the line (late)"), price, the two lines with
  distances, targets, touches, and the **nearest daily supply above and
  demand below**.
- Fresh breakouts and near-breakouts come first; a switch hides the rest.
- A click on a row opens that coin and timeframe on the Chart Patterns page.
- The top 50 coins × 4 timeframes take about 11 seconds; results are kept for
  5 minutes.

---

## Data sources

| Source | Used for | Key |
|---|---|---|
| CoinDCX public API | Spot candles and 24h volume (main screener, BTC Strength) | none |
| Binance USDⓈ-M futures public API | Futures candles, open interest, funding, perpetual list (heatmap, market read, patterns, scanner) | none |
| Binance `BTCDOMUSDT` | BTC dominance candles on every timeframe | none |
| CoinGecko public API | Live BTC.D %, market-cap ranking | none |

Binance refuses US servers, so hosting must be outside the US for the BTC.D
and futures data.

## Configuration (`config.yaml`)

| Key | What it sets |
|---|---|
| `btc_strength.timeframes`, `trend_timeframe`, `trend_emas` | BTC Strength timeframes and trend EMAs |
| `btc_strength.workers`, `btc_strength.exclude` | Parallel downloads; stablecoins / wrapped tokens left out of top-N lists |
| `classifier.per_timeframe.1M` | Classifier settings for the new 1-month timeframe |
| `liquidation.leverages`, `maintenance_margin`, `bins` | Liquidation model |
| `data.watchlists_file` | Where custom watchlists are saved |

## Hosting (planned, not done)

Target: **Oracle Cloud Always Free VM** (Mumbai or Hyderabad) running the
dashboard in Docker, reached only through a **Cloudflare Tunnel** at
`crypto.skillcurio.dev`, with **Cloudflare Access** letting in only the
owner's email. Scripts are ready in `deploy/` (`setup-vm.sh`, `deploy.sh`,
`docker-compose.yml`) and the image builds and runs locally. Still to do:
create the Oracle VM, the Cloudflare Access app and the tunnel.

Ruled out: Vercel and Supabase (cannot run a long-lived Python web server),
Cloudflare Containers (needs the paid Workers plan), Streamlit Cloud and
Hugging Face (US servers, which Binance blocks; no custom domain).

## Fixes made along the way

- **CoinDCX volume was multiplied by the price twice.** The ticker's volume is
  already in quote units, so cheap coins looked illiquid (PEPE showed $522 a
  day instead of ~$106M) and expensive ones huge. This affected the liquidity
  gate and the top-by-volume universe on every page.
- **CoinDCX's own X/BTC markets are priced to ~6 decimals**, so cheap coins
  come back flat (DOGE/BTC = 0.000001 on every candle). The BTC Strength page
  always builds COIN/BTC from the two USDT prices. The main matrix still uses
  the native books; a separate task was started to fix it (branch
  `claude/nostalgic-burnell-1609f0`, not merged).
- **Speed:** 500 coins went from ~110 s to ~60 s — a bigger cached download
  now serves smaller timeframes (3 downloads per coin instead of 6), ratios
  are divided in NumPy and built once, and the gap check is vectorised.
- **Equal highs:** the strict pivot rule skipped a flat top made of candles
  with the same high — exactly the top of an ascending triangle. Pattern
  detection counts the first of equal highs.
- **A flaky test** failed about once in a dozen runs when it crossed a minute
  boundary; its candle series now share one end time.

## Limits

- Liquidation levels are model estimates from one exchange (Binance); totals
  are smaller than CoinGlass's all-exchange numbers, and each map starts
  empty on its left edge.
- Lines, patterns and order blocks are fitted to past candles. They describe
  where price reacted; they do not promise it will react again, and many
  breakouts fail.
- The 1-month timeframe has about 32 closed months (CoinDCX serves 1000 daily
  candles); newer coins show no 1M reading.
- Chart Patterns and the scanner use Binance futures candles, so levels can
  differ slightly from MEXC or spot charts.

## Change log — 2026-09-21 / 22

| Commit | Change |
|---|---|
| `46fbaad` | BTC Strength page: coins vs BTC on 1h–1M, BTC.D for BTC's row, daily EMA trends; 1-month timeframe added |
| `5b53501` | Fix: CoinDCX ticker volume no longer multiplied by the price |
| `37af39a` | BTC Strength: BTC.D mode for every coin, top 25–500 coins by market cap, custom watchlists, coin names per timeframe, sorting, 2× faster |
| `86f3257` | Liquidation Heatmap page for BTC and the top 10 coins |
| `ec1e2fc` | Deploy scripts for a VM behind a Cloudflare Tunnel |
| `6c30225` | Market-read panel: rules-based short-term lean for BTC and the top 10 |
| `9e707a3` | Fix a flaky test (minute boundary) |
| `95fdfe9` | Chart Patterns page: trendlines, flat levels, Fibonacci, patterns, TradingView-style VuManChu |
| `4ac3cac` | Daily order blocks (purple zones) and the Pattern Scanner page |

Tests: 89 at the start of the day, 114 at the end, all passing.
