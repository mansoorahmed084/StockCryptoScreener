# Chart Workspace — Implementation Plan (draft)

Goal: a TradingView-style chart page inside the screener. You pick a symbol,
draw on the chart, and keep coins in watchlists. Drawings can become alerts.

Status: **agreed 2026-09-28 — see Decisions at the end.** Markets: crypto
(Binance) + stocks (NSE/BSE and US, via Yahoo).

---

## 1. The big decision: how we draw the chart

Streamlit + Plotly (what the Chart Patterns page uses now) cannot do this.
Plotly redraws the whole chart on each change, and Streamlit reruns the whole
script on each click. Drawing a trendline with the mouse, dragging its
handles, and live ticks need a real browser app.

**Plan:** a separate full-screen web page, written in plain JavaScript, served
by the FastAPI app that already exists (`backend/api/app.py`, port 8000).

| Part | Choice | Why |
|---|---|---|
| Chart engine | **TradingView Lightweight Charts v5** | Free, open source (Apache-2.0), made by TradingView. Same look and feel: candles, price scale, crosshair, zoom, panes. Has a "primitives" plugin API for custom drawings. |
| Drawing tools | Our own code, on the primitives API | Lightweight Charts has no drawing tools built in. TradingView's own plugin examples (trend line, rectangle, etc.) are the starting point. |
| Front end | Plain JS (ES modules), no build step | No Node toolchain in a Python repo or the Docker image. The library file is kept in the repo (vendored), so it works offline. |
| Server | Existing FastAPI app, new `/api/chart/*` routes + static files | Reuses the data layer, cache and alerts DB. |
| Live prices | Crypto: browser opens the Binance WebSocket directly. Stocks: server polls Yahoo every 30 s | Binance: lowest delay, no server load. Yahoo has no free live stream. |
| Stock data | `yfinance` (new dependency) behind a small adapter | Free, no key, NSE/BSE/US. Unofficial and rate-limited, so the server caches hard. |
| Storage | SQLite `data_cache/chart.db` | Same pattern as `data_cache/alerts.db`. Survives Docker restarts (volume). |

Open the page at `http://localhost:8000/workspace` (`/chart` is already an API
route). The Streamlit sidebar gets a "Chart Workspace" page. Links like
`/workspace?symbol=BINANCE:SOLUSDT.P&tf=4h` open a chart.

Why not TradingView "Advanced Charts" (all drawing tools built in): TradingView
does not give it for personal or private use. Only companies with a public
website get access. So we use Lightweight Charts, which TradingView itself
points personal users to.

Licence note: Lightweight Charts asks for a TradingView attribution link. The
library shows a small logo by default. We keep it.

---

## 2. Screen layout (copies your screenshot)

```
┌──────────────────────────────────────────────────────────────────┐
│ [BTCUSDT.P ▾] [+] │ 1m 3m 15m 1h 2h 4h D W ▾ │ candles ▾ │ fx Indicators │ alert │ undo redo │ layout │ 📷 │
├──┬───────────────────────────────────────────────────┬───────────┤
│✚ │ Bitcoin / TetherUS PERP · 2h · Binance  O H L C   │ Watchlist ▾│
│╱ │                                                   │ Symbol Last Chg Chg% │
│≡ │            candles + drawings                     │ ▸ VOLATILITY│
│⋰ │                                        83,710.3  │   BTC.D ... │
│T │                                          10:56   │ ▸ ALTS      │
│📏│ ───────── volume ─────────                        │   ETHUSDT...│
│🧲│ ───────── VuManChu pane ─────────                 ├───────────┤
│🔒│                                                   │ Symbol info│
│👁│ 1D 5D 1M 3M 6M YTD 1Y All        19:19:03 IST    │            │
└──┴───────────────────────────────────────────────────┴───────────┘
```

- **Top bar:** symbol search, timeframes (favourites + dropdown), chart type,
  indicators, alert button, undo/redo, save layout, screenshot.
- **Left bar:** drawing tools, magnet, lock all, hide all, delete all.
- **Centre:** the chart. Price pane on top, extra panes (volume,
  VuManChu) below. Legend with OHLC and change at top left.
- **Right bar:** watchlist on top, details of the selected symbol below.
  The bar can be hidden and resized.
- **Bottom bar:** range buttons (1D … All), clock in IST.
- Dark theme first, like the screenshot.

---

## 3. Feature list, in build order

Each phase ends with something you can use.

### Symbols: one format for every market
`EXCHANGE:TICKER`, like TradingView:

| Example | Market | Data |
|---|---|---|
| `BINANCE:BTCUSDT.P` | Binance USDT perpetual | Binance futures REST + WebSocket |
| `BINANCE:ETHBTC` | Binance spot | Binance spot REST + WebSocket |
| `CRYPTOCAP:BTC.D`, `CRYPTOCAP:USDT.D` | Dominance | `backend/data/dominance.py` |
| `NSE:RELIANCE`, `BSE:RELIANCE` | India stocks | Yahoo `RELIANCE.NS`, `RELIANCE.BO` |
| `NASDAQ:AAPL`, `NYSE:JPM` | US stocks | Yahoo `AAPL`, `JPM` |

Stock data limits (Yahoo, free):
- Delayed about 15 minutes. The chart header says "Delayed".
- 1m candles only for the last ~7 days. 5m–30m for ~60 days. 1h for ~2 years.
  D/W/M for all history. The timeframe menu greys out what cannot load.
- No 2h/4h from Yahoo. The server builds them from 1h candles (resample).
  NSE 4h candles start at 09:15 IST, like TradingView.
- Only market hours. No weekend candles.

### Phase 1 — Chart core
1. `/chart` page with the layout above (empty panels are fine).
2. Candles for Binance perps and spot first, then Yahoo stocks. Timeframes: 1m 3m 5m 15m 30m 1h
   2h 4h 6h 12h D W M.
3. Symbol search box with market tabs (All / Crypto / India / US): type
   "sol", see SOLUSDT.P, SOLUSDT, SOLBTC; type "reli", see NSE:RELIANCE.
4. Live candle from the WebSocket. Countdown to candle close under the
   price label (the "10:56" in your screenshot).
5. Scroll left loads older candles (paging), up to a few thousand.
6. Crosshair legend: O H L C, change, volume.
7. Volume pane. Log/linear and auto/fixed price scale.
8. The URL and last symbol/timeframe are remembered.

### Phase 2 — Watchlists
1. Several named lists. Switch lists from a dropdown.
2. Sections inside a list (VOLATILITY, DOMINANCE, ALTS …). Collapse them.
3. Add with the "+" button or from the chart ("add to watchlist").
   Remove with the × on hover. Drag to reorder.
4. Live columns: Last, Chg, Chg%. Crypto from the Binance `!miniTicker@arr`
   stream (one connection for the whole list). Stocks from one batched
   server call every 30 s. Stock rows show a small "D" (delayed) mark.
5. Click a row to load it in the chart. Arrow keys move up/down the list.
6. Colour flags (red, blue, green …) and a "flagged" filter.
7. Special symbols: BTC.D, USDT.D (from `backend/data/dominance.py`), and
   ratios such as ETHBTC.
8. Import: paste "BINANCE:SOLUSDT, NSE:TCS, AAPL …". The items keep the full
   `EXCHANGE:TICKER` (the old parser in `backend/watchlists.py` strips it to a
   coin, which is wrong for stocks). Export as a TradingView
   text list.
9. **One store for all pages.** The BTC Strength and Pattern Scanner pages
   read the same lists (`WatchlistStore.load()` keeps its old
   `{name: [coins]}` result, so they do not break; it gives only the crypto
   items, because those pages are crypto only).

### Phase 3 — Drawing tools (the biggest phase)
Tools, in this order (your style: triangles, wedges, order-block zones):

| # | Tool | Shortcut |
|---|---|---|
| 1 | Trend line (+ extend left/right) | Alt+T |
| 2 | Horizontal line / horizontal ray | Alt+H / Alt+J |
| 3 | Vertical line | Alt+V |
| 4 | Ray | — |
| 5 | Rectangle (zones, order blocks) | Alt+Shift+R |
| 6 | Parallel channel | — |
| 7 | Fib retracement | Alt+F |
| 8 | Text / note | — |
| 9 | Long / short position (entry, SL, TP, R:R) | — |
| 10 | Measure (price %, bars, time) | Shift+drag |

How each drawing works:
- Points are stored as **(time, price)**, not pixels. So a line drawn on 2h
  shows at the right place on 15m and D.
- Click a drawing to select it. Drag the body to move it. Drag a handle to
  change one point.
- A small floating toolbar on the selected drawing: colour, width, style
  (solid/dashed), lock, delete, "add alert".
- **Magnet:** points snap to the nearest open/high/low/close.
- **Undo / redo:** Ctrl+Z / Ctrl+Y. Delete key removes the selected drawing.
- Lock all, hide all, delete all, on the left bar.
- Drawings are saved per symbol in `chart.db` right after each change.
  SOLUSDT and SOLUSDT.P share drawings (same prices). SOLBTC has other
  prices, so it keeps its own. Stocks key by `EXCHANGE:TICKER`.

### Phase 4 — Indicators
1. Built in: EMA, SMA, VWAP, Bollinger Bands, RSI, MACD, volume. Computed in
   the browser (fast, no server call).
2. **VuManChu Cipher B pane.** The server already computes it
   (`backend/indicators/vumanchu.py`, used by `GET /chart`). We reuse it, so
   the numbers match the screener exactly.
3. **Visible-range volume profile** (the bars on the left of your chart).
4. **"Auto analysis" layer:** the trendlines, patterns, Fibonacci and daily
   order blocks that the Chart Patterns page already finds
   (`frontend/pattern_view.py` / pattern code). They show as dimmed,
   read-only drawings. One click copies one into your own drawings.
5. Indicator settings dialog (length, source, colour).

### Phase 5 — Alerts from the chart
The alert system already supports exactly these shapes
(`backend/alerts/price_alerts.py`): price level, line through two
(time, price) points, and zone [low, high].
1. Right-click a horizontal line → "Add alert" → price alert.
2. Trend line → line alert (touch, close above, close below).
3. Rectangle → zone alert (enter).
4. Active alerts show on the chart as a small bell on the price scale.
   Fired alerts show greyed.
5. The watcher and Telegram flow stay as they are.
6. Stock alerts: the watcher today checks Binance only. Stock alerts need a
   Yahoo check in the watcher (1-minute delay on top of the 15-minute feed
   delay). Built last in this phase; the chart hides "Add alert" on stocks
   until then.

### Phase 6 — Polish (later)
- Multi-chart layouts: 1, 2 or 4 charts, linked symbol or linked crosshair.
- Saved layouts (symbol + timeframe + indicators + drawings per slot).
- Chart types: Heikin Ashi, line, area.
- Screenshot to PNG.
- Bar replay (step through old candles).
- Links to the Trade page (pre-fill entry/SL/TP from a long/short drawing).

**Not planned:** Pine Script, social ideas, paper trading, news.

---

## 4. Server work (FastAPI)

New routes in a new `backend/api/chart_routes.py`, added to `app.py`:

| Route | Does |
|---|---|
| `GET /workspace` | Serves the page (`frontend/chart_app/index.html`) |
| `GET /api/chart/symbols?q=&market=` | Search Binance perps + spot (exchangeInfo, cached 1 h) and Yahoo (search endpoint, NSE/BSE/US only) |
| `GET /api/chart/quotes?symbols=` | Last/chg/chg% for stock rows, batched, cached 30 s |
| `GET /api/chart/candles?symbol=&tf=&end=&limit=` | Candles, with paging by `end` time. Special symbols: BTC.D, USDT.D, ratios |
| `GET /api/chart/indicators/vumanchu?symbol=&tf=` | wt1, wt2, dots, from the existing indicator |
| `GET /api/chart/analysis?symbol=&tf=` | Auto trendlines, patterns, order blocks, as JSON shapes |
| `GET/POST/PUT/DELETE /api/chart/watchlists…` | Lists, sections, items, order, flags |
| `GET /api/chart/drawings?symbol=` · `PUT/DELETE /api/chart/drawings/{id}` | Drawings |
| `POST /api/chart/alerts` · `GET /api/chart/alerts?symbol=` | Alerts, through the existing `price_alerts` store |
| `GET/PUT /api/chart/layouts…` | Saved layouts (phase 6) |

New `backend/data/market_data.py`: one `candles(symbol, tf, end, limit)` call
that routes by exchange prefix to Binance futures, Binance spot, dominance or
a new `backend/data/yahoo.py` adapter.

`BinanceFutures.klines()` today takes only `limit`. It needs an `endTime`
parameter for paging. The candles route caches closed candles, so scrolling
back is fast after the first load.

### Database: `data_cache/chart.db`

```
watchlists      (id, name, position, active)
watchlist_items (id, list_id, symbol, section, flag, position)
drawings        (id, symbol_key, tool, points_json, style_json,
                 locked, hidden, created_ms, updated_ms)
layouts         (id, name, state_json, updated_ms)
```

On first start, the lists in `data_cache/watchlists.json` are copied in. Then
`WatchlistStore` reads from SQLite.

---

## 5. Front-end files

```
frontend/chart_app/
  index.html
  css/app.css                  dark theme tokens
  vendor/lightweight-charts.standalone.production.mjs
  js/main.js                   start-up, URL state
  js/api.js                    fetch helpers
  js/datafeed.js               history paging + WebSocket live candle
  js/chart.js                  chart, panes, legend, countdown
  js/toolbar.js                top bar, timeframes, symbol search
  js/watchlist.js              right panel
  js/indicators/*.js           ema, rsi, macd, vumanchu, volume-profile
  js/drawings/manager.js       select, drag, undo/redo, save, magnet
  js/drawings/base.js          shared primitive code (hit test, handles)
  js/drawings/trendline.js, hline.js, rect.js, channel.js, fib.js,
               text.js, position.js, measure.js
  js/alerts.js                 bells on the price scale, "add alert" dialog
```

---

## 6. Tests

- Python: pytest for each new route (candles paging, watchlist CRUD,
  drawings CRUD, drawing → alert conversion, JSON → SQLite migration).
- Browser: each phase is checked in the preview browser (draw, move, reload,
  drawing still there; watchlist live prices change; alert created).
- Drawing maths (time/price ↔ pixel, hit test, fib levels) in small pure
  functions, so they are easy to test.

---

## 7. Rough size

| Phase | Work |
|---|---|
| 1 Chart core (crypto) | 1 session |
| 1b Stocks data (Yahoo) | 1 session |
| 2 Watchlists | 1 session |
| 3 Drawing tools | 2–3 sessions |
| 4 Indicators | 1–2 sessions |
| 5 Alerts | 1 session |
| 6 Polish | as wanted |

---

## 8. Decisions (2026-09-28)

1. Markets: crypto + stocks (NSE/BSE and US).
2. Own full-screen page at `/workspace`, linked from Streamlit.
3. Lightweight Charts + our own drawing tools. (Advanced Charts is not
   licensed for private use.)
4. SOLUSDT and SOLUSDT.P share drawings.
