# Crypto Lab — Freqtrade

Backtesting and paper-trading bot. Part of the **StockCryptoScreener** project.

The screener (in the parent folder) finds *which* coins are strong.
This folder tests *when* to enter and exit, and can run the trade automatically.
The two are separate on purpose: Freqtrade pins its own dependency versions
(pandas 3.x), so it keeps its own `.venv` and does not share the screener's.

Binance spot data. `dry_run` is on — no real money.

## First-time setup

```bash
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install freqtrade
cp config.example.json config.json
```

Then edit `config.json` and replace the three `CHANGE_ME` values in `api_server`.
`config.json` is gitignored because it will hold your exchange keys.

Get candle data before your first backtest:

```bash
.venv/Scripts/freqtrade.exe download-data --config config.json --timeframes 5m 1h --days 180
```

## Where things are

| Thing | Path |
|---|---|
| Settings | `config.json` |
| Your strategies | `user_data/strategies/` |
| Downloaded candles | `user_data/data/binance/` |
| Backtest results | `user_data/backtest_results/` |
| Python env | `.venv/` |

## Web UI

Open http://127.0.0.1:8080 after you start the bot.

- user: `freq`
- password: see `api_server.password` in `config.json`

## Commands

Run all of these from this folder.

Get fresh candle data (last 180 days):

```bash
.venv/Scripts/freqtrade.exe download-data --config config.json --timeframes 5m 1h --days 180
```

Backtest a strategy:

```bash
.venv/Scripts/freqtrade.exe backtesting --config config.json --strategy SampleStrategy --timeframe 5m
```

Start the paper-trading bot:

```bash
.venv/Scripts/freqtrade.exe trade --config config.json --strategy SampleStrategy
```

Auto-tune strategy settings (slow, uses all CPU cores):

```bash
.venv/Scripts/freqtrade.exe hyperopt --config config.json --strategy SampleStrategy --hyperopt-loss SharpeHyperOptLoss --epochs 100
```

Make a new empty strategy:

```bash
.venv/Scripts/freqtrade.exe new-strategy --userdir user_data --strategy MyIdea --template full
```

## Going live later

1. Change `"dry_run": true` to `false` in `config.json`.
2. Put your Binance API key and secret in the `exchange` block.
3. Give the API key trade permission only. Never withdraw permission.

Do not do this until a strategy has run in paper mode for weeks.
