# Crypto Screener — Product Description

A self-hosted crypto dashboard (Streamlit). It answers four questions, and
tells you when price reaches a level, trendline or zone you set:

1. **Which coins are stronger or weaker than BTC** (or BTC dominance), on every
   timeframe from 1 hour to 1 month?
2. **Where are the liquidity zones** — the prices where leveraged traders would
   be liquidated — and which way is price likely to be pulled next?
3. **What does the chart show** — trendlines, flat levels, Fibonacci, chart
   patterns and daily order blocks, drawn automatically?
4. **Which coins have a pattern breaking out right now**, on any timeframe?

The screener needs no API keys. The Trade page places orders on CoinDCX
INR futures only with your keys and `trading.mode: live`. Everything else
below is a read of market data, not
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
| Pattern Scanner | `/Pattern_Scanner` | Triangles, wedges and flags across many coins and timeframes |
| Alerts | `/Alerts` | Price, trendline and zone alerts you set, checked every minute |
| Trade | `/Trade` | Open, protect (SL + target) and close CoinDCX INR futures trades |
| Chart Workspace | `/Chart_Workspace` → http://localhost:8000/workspace | TradingView-style chart: drawing tools, indicators, watchlists, crypto + stocks |

### Best time to trade (IST)
The main screener and the Trade page show a strip of 24 hour boxes in IST.
**Green = good time to trade** (high liquidity). **White = no trade.** An
orange border marks the current hour. A line below says "good time to trade"
or "no trade" now, and when the next good slot starts.

An hour is green when BTC perpetual volume at that hour is at least 1.1× an
average hour (median of the last 1,000 Binance 1h candles, weekdays only).
Binance candles open on the UTC hour, so every IST slot starts at :30. With
2026-09 data the green hours are 13:30–14:30 (London open) and 17:30–23:30
(London / New York overlap). On weekends a note says liquidity is thin all
day. If Binance cannot be reached, the strip shows those usual hours.

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
not list are flagged. Lists are saved in `data_cache/chart.db` (gitignored,
kept by Docker) and are the same lists as the Chart workspace's watchlist
panel; this page sees only their coins (stocks stay in the list).

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
layer can be switched off. A link like `Chart_Patterns?coin=XRP&tf=15m` opens
a chart directly, and the address follows the sidebar, so a chart can be
bookmarked.

- **Price action.** Recent swings are labelled on the candles: HH / LH for
  highs, HL / LL for lows. Under the chart, in plain words: the structure
  (uptrend = higher highs and higher lows, downtrend, squeeze = lower highs
  but higher lows, expanding, range; a swing within 0.3 ATR of the one before
  counts as equal, so a retested low in an uptrend still reads as uptrend),
  a close past the last swing high or low
  (break of structure), where price sits between the last swings, the last
  closed candle (strong body, long upper or lower wick, indecision), volume
  against its 20-candle average, and the change over the last 10 candles.
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
  necklines. A double bottom must be the low of a fall: price came down into
  the first bottom, and nothing just before it traded lower. Two equal lows
  inside an uptrend are a retest (continuation), not a double bottom; double
  tops are the mirror image.
- **Bull and bear flags** — trend continuation. Bull: in an uptrend (the top
  above a rising 50-candle EMA), a rise of at least 6 ATR (the pole), then a
  pullback that gives back under 61.8% of it under a falling line through
  its lower highs. The line is drawn the way a trader draws it as the chart
  unfolds: from the top through lower swing highs well inside the pullback,
  respected (no close above it yet), touching the most highs. A close above
  it with the top plus two lower highs on the line is the breakout — but it
  only counts once price clears the flag's top without closing back under
  the line; a poke that falls back is a false breakout and the line is
  redrawn above it. Target: the pole's height added to the breakout; the
  flag's low is where it fails. Bear flags are the mirror image. On LTC 15m
  (19–22 Sep) it finds both flags a trader drew, and their breakouts. Each shows its status (inside / broke up / broke down) and
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
- Patterns: by default ascending and descending triangles, falling and
  rising wedges, and bull and bear flags; double tops / bottoms, symmetrical
  triangles, channels and ranges can be added.
- Each row: coin, timeframe, pattern, a plain **setup line** ("Broke up,
  fresh; daily supply here", "Near breakout: 0.1% to the upper line",
  "Broke down, 3.7% past the line (late)"), price, the two lines with
  distances, targets, touches, and the **nearest daily supply above and
  demand below**.
- Fresh breakouts and near-breakouts come first; a switch hides the rest.
- **Tick a row** and its chart — candles, price-action labels, the pattern,
  lines, Fibonacci and daily order blocks — appears right below the table,
  with the price-action and pattern notes.
- **Click the coin name or 📈 Open** for the full Chart Patterns page of that
  coin and timeframe in a new tab.
- The top 50 coins × 4 timeframes take about 11 seconds; results are kept for
  5 minutes.

---

## 5. Alerts page

**Question it answers:** tell me when price reaches my level, line or zone.

### Alert types
| Type | Conditions | Fires when |
|---|---|---|
| Price | goes above / goes below / touches | a 1-minute candle's high / low reaches the level |
| Price | closes above / closes below | a closed candle of the size you pick (1m, 5m, 15m, 1h, 4h, 1d) closes past the level |
| Trendline | touches / closes above / closes below | a candle trades through the line, or a closed candle (size you pick) closes past it |
| Zone | enters | a candle trades inside the zone (e.g. a purple order block) |

A close alert ignores wicks and the candle still forming: "BTC closes above
84,820 on a 15m close" fires only once a 15m candle has closed above 84,820.
The 🔔 box under a chart picks that chart's timeframe by default.

A trendline is a straight line through two (time, price) points, extended in
time, so its level moves with the clock. Wicks count for touches, so a quick
spike through a level between checks is not missed. Each alert fires once,
then waits under **Fired** to be re-armed or deleted. An alert that is
already met when you set it is refused with a warning.

### Setting alerts
- **Alerts page:** pick a coin (any Binance USDT perpetual), a type, a
  condition and an optional note. Trendlines take two points in UTC.
- **🔔 Set an alert on this chart** — a box under every chart (Chart Patterns
  and the scanner's chart): one click sets an alert on a detected trendline
  (resistance defaults to "closes above", support to "closes below"), a flat
  level, a daily order block, a Fibonacci level or a typed price.
- The page lists active alerts with the level they wait for, the price now
  and the distance; fired alerts with the hit price and time.

### How you get told
- **Dashboard pop-up** on every page, which checks all alerts every 60 s
  while it is open (`alerts.check_seconds`), plus the last hits in the
  sidebar.
- **Windows notification** (`alerts.desktop`, on by default).
- **Telegram** when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are in `.env`.
- **With the dashboard closed:** `.venv/Scripts/python.exe -m backend.cli
  alerts` checks every 60 s (`--every`, `--once`).

Alerts are stored in `data_cache/alerts.db` (SQLite). Firing an alert is one
atomic update, so two open tabs or a tab plus the watcher never send it twice.

## 6. Trade page

**Question it answers:** place this trade on CoinDCX with a stop loss and a
target, sized so I lose only what I choose.

"INR futures" on CoinDCX are the USDT perpetuals (e.g. `B-BTC_USDT`) with
INR as margin. Prices are in USDT; margin, risk and P&L are in INR at
CoinDCX's fixed USDT→INR rate.

### A trade ticket
Pick the coin, long or short, market or limit entry, a **stop loss (always
required)**, an optional target, the **INR you accept to lose** if the stop
is hit, and leverage. The page sizes the trade from that risk (fees
included) and shows: size, entry, margin, loss at the stop, profit at the
target and its R multiple, and an estimated liquidation price.

A trade is **refused** when the stop is on the wrong side, closer than
`min_stop_pct`, beyond the liquidation price, the size is under CoinDCX's
minimum, the leverage is above the pair's tier or your limit, the risk or
margin is above your limit, you already hold that coin, you have
`max_open_positions` open, or you have lost `max_daily_loss_inr` today (UTC).

To place it you **type the pair name** (e.g. `B-SOL_USDT`) and click.

### What happens when you place it
1. Leverage is set for the pair, then the entry is sent.
2. Market entry: the page waits for the fill, attaches the stop loss and
   target on the exchange, then **reads the position back** to make sure the
   stop is there. If CoinDCX does not show the stop after a second try, the
   position is **closed at market** — it is never left without a stop.
3. Limit entry: it waits on the exchange; the watcher attaches SL / target
   when it fills.
4. A request that times out is never sent twice; the exchange is re-read.

### Gold-standard rules (fixed in code)
Every trade must meet these, from any screen or command: **stop loss at most
10% from entry**, **margin at most 5% of the free INR futures balance**,
**leverage at most 5x**. They live in `backend/trading/risk.py`, not in
config. Only a trade you explicitly mark **override** (a tick box on the page,
`--override` in the terminal) may break them, and it is logged as overridden.
The override lifts only these size rules, never your `trading.limits`.

A setup is **only suggested when its reward is at least 2x its risk**,
re-checked at the CoinDCX price with fees in, both when a scan lists it and
when you place it; the override does not lift this. `trade take ID --margin X
--override` places a setup bigger than 5%.

Terminal confirmations show the pair and ask **y/n**; only `panic` asks you
to type `PANIC`.

### Setups from the scan: tap to place
- **Scan now** on the page, or `trade scan` (add `--every-min 15` to repeat),
  runs the scanner's fixed buy-setup rules over the top 50 coins and lists
  each setup with the trade it would make: a LONG at market, the pattern's
  lower line as stop loss, its target, sized at 5% of the free balance, 5x.
  A scan never places an order. A new ready setup is also sent to Telegram.
- Each setup is **ready** (tap **Place**, then confirm), **waiting** (near its
  line; ready once a later scan sees the break), **blocked** (with the rule
  that failed), **placed** or **expired** (a ready setup older than 2 hours;
  the next scan offers it again, fresh, if it still passes every rule).
- Tapping Place re-checks size, stop and every rule at the current price.
- A setup you traded is never offered again. A coin rests 24 hours after any
  trade on it — including one you **closed by hand** in the app, which the
  next scan or the watcher records as closed.
- Terminal: `trade ideas` lists setups, `trade take ID` places one.

### Managing open trades
- Each open position shows entry, SL, target and the price now. Move the SL
  or target (type the pair to confirm) or **close at market**.
- Open orders, with cancel.
- **Panic** (type `PANIC`): cancels every order, closes every position and
  blocks new trades until you allow them again.
- A **log** of every request sent and CoinDCX's answer
  (`data_cache/trading.db`).

### Trailing stop loss
CoinDCX has none, so the watcher moves the stop itself. R is the trade's first
risk (entry to its first stop). Once price is **1R in profit**, the stop moves
to **breakeven** (entry + 0.2% for fees); after that it follows the **best
price, 1R behind it**. It only moves in the trade's favour, and only in steps
of at least 0.25R. The target stays in place.

- On for every trade this tool opens; off for positions opened by hand.
  Switch it per trade with the toggle in the position panel or
  `trade trail-on PAIR` / `trade trail-off PAIR`.
- Settings: `trading.trailing` (`activate_r`, `trail_r`, `min_step_r`,
  `breakeven_buffer_pct`, `min_gap_pct`, `enabled`).
- It works only while `trade watch` runs, and it sees the price once per
  round (every 30 s by default), so a spike between rounds is missed.
- Moving a stop: the old stop is cancelled, the new one placed and read
  back. If "stop alone" is refused, it is sent again with the target; if
  CoinDCX still shows no stop, the old one is put back.
- `trade watch --dry-run` shows the moves it would make and sends nothing.

Two more ways to trail, set per trade:
- **Candle:** a notch (0.1%, `candle_buffer_pct`) under the low of the last
  **closed CoinDCX** futures candle (1m, 5m, 15m or 1h; the one still forming
  is ignored) — over its high for a short. `--trail-candle 15m`. A candle is
  read 60 s after it closes (`candle_settle_s`; CoinDCX revises it for a few
  seconds), and moves smaller than 0.1% of the price are skipped
  (`candle_min_step_pct`), so each 15m close gives at most one re-place.
- **Percent:** a fixed % behind the best price. `--trail-pct 1.5`.

`trade trail-set PAIR --trail-candle 15m` (or `--trail-pct X`) switches an
open trade's method. `trade adopt PAIR --trail-candle 15m` hands a position
you **opened by hand** to the watcher: it records it and sends nothing; the
watcher then sets and moves its stop. Both ask you to type the pair first.
Checked live on 2026-09-27: AR's stop moved 4.799 → 4.818 under a 15m low.

### The watcher (live mode)
`.venv/Scripts/python.exe -m backend.cli trade watch` checks every 30 s: it
attaches SL / target to filled limit entries, marks trades closed when their
stop or target hits, and warns (Telegram / Windows) about any position with
no stop loss — including ones opened by hand in the CoinDCX app. SL and
target orders sit on CoinDCX, so they work even when the watcher is off.

### From a terminal
```bash
.venv/Scripts/python.exe -m backend.cli trade status
.venv/Scripts/python.exe -m backend.cli trade preview SOL long --sl 115 --tp 135 --risk 300 --lev 3
.venv/Scripts/python.exe -m backend.cli trade open SOL long --sl 115 --tp 135 --risk 300 --lev 3
.venv/Scripts/python.exe -m backend.cli trade tpsl SOL --sl 118
.venv/Scripts/python.exe -m backend.cli trade close SOL
.venv/Scripts/python.exe -m backend.cli trade panic
.venv/Scripts/python.exe -m backend.cli trade log
```
Add `--limit PRICE` for a limit entry. Every command that sends something
asks you to type the pair (or `PANIC`) first.

### Safety set-up
- `trading.mode: dry_run` (the default) checks and logs every order and sends
  nothing. Switch to `live` only after a dry run looks right.
- Keys live only in `.env` (git-ignored): `COINDCX_API_KEY`,
  `COINDCX_API_SECRET`. They are sent in headers, never logged or stored.
- CoinDCX has **no read-only keys**: bind the key to the IP of the machine
  that trades, and keep only trading money in that account (a sub-account
  has its own keys).
- Claude can preview trades, read status and prepare commands; you type the
  confirmation that places or closes a trade.

---

## 7. Chart workspace

**Question it answers:** what does this chart look like, with my own lines on
it? A TradingView-style full-screen chart for crypto and stocks.

Run the API, then open the page:

```bash
.venv/Scripts/python.exe -m uvicorn backend.api.app:app --port 8000
```

http://localhost:8000/workspace — or the **Chart Workspace** page in the
Streamlit sidebar (a frame + an "Open full screen" button). A link like
`/workspace?symbol=BINANCE:SOLUSDT.P&tf=4h` opens that chart.

### Chart
- Candles for Binance USDT perpetuals (`BINANCE:BTCUSDT.P`), Binance spot
  (`BINANCE:ETHBTC`) and BTC dominance (`CRYPTOCAP:BTC.D`, Binance's BTCDOM
  index contract). Live from Binance's WebSocket.
- Timeframes 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, D, W, M. Favourites
  in the top bar, the rest under ▾.
- **Symbol search:** click the symbol, or just start typing on the chart.
  Tabs: All, Crypto, India, US. Arrow keys + Enter.
- Scroll left and older candles load by themselves.
- Legend: O H L C, change and volume of the candle under the cursor.
- Countdown to the candle close under the price label.
- Chart styles: candles, Heikin Ashi, bars, line, area.
- Bottom bar: 1D … All ranges (each picks a timeframe, like TradingView),
  clock (click to change the time zone; IST by default), % / log / auto
  price scale.
- Symbol, timeframe and settings are remembered, and kept in the URL.

### Stocks
- India: `NSE:RELIANCE`, `BSE:RELIANCE`; US: `NASDAQ:AAPL`, `NYSE:JPM`,
  `AMEX:SPY`; indices `NSE:NIFTY`, `NSE:BANKNIFTY`, `BSE:SENSEX`, `SP:SPX`,
  `NASDAQ:NDX`, `DJ:DJI`. Pick them in the India or US search tab.
- Data from Yahoo Finance (free, no key). **Delayed about 15 minutes**; the
  top bar says "Delayed" and the newest candles are re-read every 30 s.
- Timeframes: 1m, 5m, 15m, 30m, 1h, 2h, 4h, D, W, M. Yahoo has no 2h/4h, so
  they are built from 1h candles counted from the session open (NSE 4h
  candles open at 09:15 and 13:15 IST, like TradingView). 3m, 6h and 12h are
  greyed out; a crypto chart on 3m opens a stock on 5m.
- History: 1m only ~7 days back (one page), 5m–30m 60 days, 1h 2 years,
  D/W/M all. Yahoo's BSE history is short for some shares; NSE is better.
- No countdown on stock candles.

### Watchlists (right panel)
- ☰ **Watchlist** in the top bar opens and closes the panel; drag its left
  edge to resize.
- Several named lists (▾ next to the name): create, rename, delete, clear,
  **import** (paste `BINANCE:SOLUSDT.P, ETHUSDT.P, NSE:TCS, AAPL, PEPE …`;
  bare tickers are guessed — a Binance coin becomes its perpetual, else an
  exact stock match; `###NAME` starts a section) and **export** (TradingView's
  comma format).
- Sections: collapse with a click; add, rename or remove from the right-click
  menu.
- Columns Last, Chg, Chg%: crypto live from Binance (24h change), stocks
  every 30 s (today's change, delayed). Prices flash green / red on a tick.
- Click a row to open it; ↑ / ↓ walk the list. ＋ adds a symbol through the
  search; **Alt+W** adds the chart's symbol.
- Colour flags: click the thin bar at a row's left edge to cycle colours, or
  right-click. ⚑ shows only one flag colour.
- Drag rows (and sections) to reorder. Every change is saved at once.
- Under the list: the chart symbol's name, price, change, 24h high / low /
  volume (crypto), and whether it is live or delayed.
- A first-time user starts with one list: dominance, five coins, NIFTY,
  BANKNIFTY, RELIANCE, SPX, NDX, AAPL. The lists are shared with the BTC
  Strength and Pattern Scanner pages.

## Data sources

| Source | Used for | Key |
|---|---|---|
| CoinDCX public API | Spot candles and 24h volume (main screener, BTC Strength) | none |
| Binance USDⓈ-M futures public API | Futures candles, open interest, funding, perpetual list (heatmap, market read, patterns, scanner) | none |
| Binance `BTCDOMUSDT` | BTC dominance candles on every timeframe | none |
| CoinGecko public API | Live BTC.D %, market-cap ranking | none |
| CoinDCX futures API | Trade page: INR futures instruments, prices, orders, positions | yes, for orders |

Binance refuses US servers, so hosting must be outside the US for the BTC.D
and futures data.

## Configuration (`config.yaml`)

| Key | What it sets |
|---|---|
| `btc_strength.timeframes`, `trend_timeframe`, `trend_emas` | BTC Strength timeframes and trend EMAs |
| `btc_strength.workers`, `btc_strength.exclude` | Parallel downloads; stablecoins / wrapped tokens left out of top-N lists |
| `classifier.per_timeframe.1M` | Classifier settings for the new 1-month timeframe |
| `liquidation.leverages`, `maintenance_margin`, `bins` | Liquidation model |
| `data.watchlists_file` | Old custom-watchlist file, copied into `chart.db` once |
| `chart.db` | Chart workspace store: watchlists (default `data_cache/chart.db`) |
| `chart.workspace_url` | Where the Chart Workspace page opens the chart (default `http://localhost:8000/workspace`) |
| `alerts.db`, `check_seconds`, `desktop` | Alert store, how often open pages check, Windows pop-ups |
| `trading.mode`, `trading.limits`, `close_unprotected` | Dry run or live; per-trade and daily risk limits; auto-close positions with no stop |

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
| `393b1b4` | This product description |
| `6c79d30` | Scanner: chart below the table on a ticked row, coin / 📈 links to the full chart; price action (HH / HL / LH / LL labels and notes) on every chart |
| `e18a854` | Price, trendline and zone alerts: Alerts page, 🔔 box under every chart, checks on every page, Windows / Telegram / terminal watcher |
| `b101f13` | Bull and bear flags (pole, pullback under a falling line, its break) in charts and the scanner; double tops / bottoms need the move into them; equal swings read as a retest; pattern analysis 2× faster |
| `bb26488` | Close alerts: "closes above / below" a price on a candle size you pick (1m–1d, e.g. a 15m close); trendline breaks take the same choice |
| `002d311` | Trade journal (`journal/TRADE_JOURNAL.md`): every buy setup the scans called, replayed as a paper trade, with what worked and what didn't; `python -m backend.cli journal` refreshes it |
| `f6797c6` | Trade page and `cli trade`: CoinDCX INR futures sized from the rupees you risk, SL/TP attached and checked after every fill (closed if no stop shows), your limits, panic, a log of every order; dry run until `trading.mode: live` |
| `eefc9d2` | Trades sized by margin (`--margin`); CoinDCX history paging and stop-order price fixes; first live test (SOL, Rs 1,000 margin, 5x) placed with SL/TP checked |
| `8341078` | Gold-standard rules in code (stop ≤ 10%, margin ≤ 5% of free balance, ≤ 5x; override only when asked); scan setups on the Trade page with tap-to-place; no re-trading a setup or a coin closed by hand |
| `23cee24` | Trailing stop loss run by the watcher: breakeven at 1R, then 1R behind the best price; per-trade on/off; hand-opened positions untouched |
| `8560021` | `trade adopt` / `trail-set`: trail positions opened by hand; percent trail and a trail under the last closed CoinDCX 1m–1h candle |
| `b7f807e` | Candle trail waits 60 s for a closed candle to settle and skips moves under 0.1%; trail-set fixes the trade's note. AR's 15m trail took it out at 4.843 for +Rs 306 net |
| `c5effd9` | An expired ready setup is offered again by the next scan that still finds it (was hidden for up to 6 hours) |
| `b2fc950` | Setups suggested only at 2R or more (CoinDCX price, fees in); `trade take --margin --override` for bigger setup trades; y/n confirmations |
| `aa946a6` | Best time to trade (IST) strip on the screener and Trade page: green = high-liquidity hour, white = no trade |

Tests: 89 at the start of the day, 129 at the end, all passing.
