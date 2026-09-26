# Crypto Relative-Strength Screener

A self-hosted dashboard that shows which crypto coins are **outperforming or
underperforming** their base pairs (BTC, ETH, USDT, INR, and an equal-weight alt
index) across many timeframes at once — `1w / 1d / 4h / 1h / 15m / 3m` — with
multi-condition AND/OR filters, noise-filtered strength scoring, custom
indicators (VuManChu Cipher B), alerts, and a backtest harness.

Primary data source: **CoinDCX** (public candles, no API key required).

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full design, and
[PRODUCT.md](PRODUCT.md) for what every dashboard page does, how it works, its
data sources and limits.

## Quick start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Print a relative-strength matrix from the command line:

```bash
python -m backend.cli matrix --coins SOL,ETH --base BTC
```

Run the dashboard (Phase 2):

```bash
streamlit run frontend/streamlit_app.py
```

The sidebar also has a **BTC Strength** page. It shows which coins are stronger
or weaker than BTC or BTC.D on 1h / 4h / 1d / 1w / 1M, which coins those are,
and the short / medium / long trend (daily EMA 20 / 50 / 200) of each coin, of
BTC (BTC/USDT) and of BTC.D.

- **vs BTC:** each coin on COIN/USDT ÷ BTC/USDT. BTC's own row uses BTC.D.
- **vs BTC.D:** each coin, BTC included, on its USDT price ÷ BTC.D (Binance
  `BTCDOMUSDT`; the live % comes from CoinGecko).
- **Coins:** the top 25-500 by CoinGecko market cap that CoinDCX lists (500
  coins take about a minute), your own saved watchlists, or the config list.
  Watchlists are saved to `data_cache/watchlists.json`; you can paste
  TradingView tickers such as `BINANCE:SOLUSDT`.

Settings are under `btc_strength` in `config.yaml`.

A **Liquidation Heatmap** page estimates where leveraged traders would be
liquidated, the way CoinGlass does, from free Binance futures data: every rise
in open interest adds positions at 10x / 25x / 50x / 100x liquidation prices,
falling open interest shrinks them, and price crossing a level wipes it. Bright
bands are the big liquidity zones. It covers BTC and the top 10 coins by market
cap (or any Binance USDT perpetual) over 12h, 1d, 3d, 7d or 30d. The leverage
mix is under `liquidation` in `config.yaml`. Sizes are model estimates.

A **Chart Patterns** page draws what a trader would draw by hand, on any
Binance USDT perpetual (15m, 1h, 4h or 1d): support and resistance trendlines
through swing lows and highs, flat levels, Fibonacci retracements and
extensions of the biggest leg in view, and patterns between the best two lines
(ascending / descending / symmetrical triangles, rising / falling wedges,
channels, ranges, double tops and bottoms) with breakout levels and targets,
plus bull and bear flags — a trend, a pullback under a falling line, and the
break of that line. A
line broken in the last few candles stays on the chart, dotted, so fresh
breakouts show. Daily order blocks are drawn as purple zones on every
timeframe: supply is the last up candle before a sharp daily drop that broke
the recent low, demand the mirror image; a zone price has since closed through
is marked "flipped". The VuManChu Cipher B pane underneath is styled like
TradingView's.

A **Pattern Scanner** page runs that detection across the top 10-200 coins (or
a saved watchlist) on 15m, 1h, 4h and 1d, and lists ascending / descending
triangles, falling / rising wedges and more, with fresh breakouts and
near-breakouts first and the nearest daily supply and demand beside each.
Tick a row to see its chart below the table, or click the coin / 📈 Open for
the full chart page. Every chart also labels price action: HH / HL / LH / LL
swings, plus notes on structure, breaks, the last candle and volume.

An **Alerts** page lets you set price, trendline and zone alerts (or set them
in one click from the 🔔 box under any chart). They are checked every minute
while any page is open: "goes above / below" fires on any 1-minute wick,
"closes above / below" waits for a closed candle of the size you pick (1m to
1d, e.g. a 15m close). Hits pop up in the dashboard, as
a Windows notification, and on Telegram if `.env` has a bot token. To watch
them with the dashboard closed:

```bash
.venv/Scripts/python.exe -m backend.cli alerts
```

A **trade journal** in [journal/TRADE_JOURNAL.md](journal/TRADE_JOURNAL.md)
tracks every buy setup the scans called, as paper trades ($100 each, no
fees), and notes what worked and what didn't. The setups are rows in
`journal/trades.csv`. This command replays them on Binance candles and
refreshes the tables:

```bash
.venv/Scripts/python.exe -m backend.cli journal
```

New setups come from a fixed set of rules, so the journal tests the scanner
itself (see `backend/screener/buy_setups.py`). The rules are: 1h / 4h / 1d
only, daily and 4h trend up, no bearish setup on the coin, 5% of room to
daily supply, and reward at least 2× risk.

```bash
.venv/Scripts/python.exe -m backend.cli setups            # show today's picks
.venv/Scripts/python.exe -m backend.cli setups --journal  # add them to trades.csv
```

Run the API (Phase 4):

```bash
uvicorn backend.api.app:app --reload
```

## Testing

```bash
pytest
```

Unit tests use synthetic candle series and need no network access.

## Configuration

Everything is driven by [config.yaml](config.yaml): coin universe, bases,
timeframes, liquidity floor, sector tags, and the per-timeframe noise-filter
thresholds. Secrets (Telegram, future order keys) live in `.env` — see
[.env.example](.env.example). The screener itself needs **no keys**.

## Status — all phases implemented ✅

- **Phase 0** — setup, config
- **Phase 1** — CoinDCX data layer, ratio builder, noise-filtered RS engine, universe/liquidity, data quality, CLI
- **Phase 2** — Streamlit dashboard, filter engine, sector RS, regime header
- **Phase 3** — charts, indicators (WaveTrend + VuManChu Cipher B), alerts (Telegram), signal journal, backtest harness
- **Phase 4** — FastAPI backend API
- **Phase 5** — CoinDCX futures funding signal, scheduled alert scanner, Docker deployment

## Commands

```bash
python -m backend.cli markets                 # sanity-check the data source
python -m backend.cli matrix --base BTC,USDT  # print the RS matrix
python -m backend.cli report --base USDT --timeframes 15m,4h,1d,1w
                                              # multi-TF bullish confluence
                                              # + VuManChu divergence report
python -m backend.cli scan                    # evaluate presets, fire alerts
python -m backend.cli watch --interval 5      # always-on alert scanner
python -m backend.cli backtest --coin SOL --base BTC --timeframe 1d
```

## Execution & backtesting — `freqtrade-lab/`

The screener answers *which* coin. [freqtrade-lab/](freqtrade-lab/README.md)
answers *when* to enter and exit, and can place the orders automatically.

It runs [Freqtrade](https://www.freqtrade.io/) against Binance spot data with
`dry_run` on (paper money). It has its own `.venv` because Freqtrade pins
dependency versions that clash with the screener's.

```bash
cd freqtrade-lab
.venv/Scripts/freqtrade.exe backtesting --config config.json --strategy-list EmaCross RsiDip BbandsBreakout --timeframe 1h --timerange 20260308-20260905
```

Baseline results for three reference strategies are in
[freqtrade-lab/RESULTS.md](freqtrade-lab/RESULTS.md).

## Deployment

```bash
docker compose up -d          # dashboard :8501, API :8000, alert watcher
```

Put `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` in `.env` to enable alert delivery.
