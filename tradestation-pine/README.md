# LuxAlgo indicators for Trade Station

Pine v5 ports of the three Python rebuilds in `freqtrade-lab/research/`. They are saved in the
Trade Station app's script library (Pine editor). They are kept here, not in the public
trade-station repo, because of the LuxAlgo licence (CC BY-NC-SA 4.0: personal, non-commercial use).

| File | Indicator | Python source |
|---|---|---|
| `supertrend_ai.pine` | SuperTrend AI (Clustering) | `supertrend_ai.py` |
| `sr_breaks.pine` | Support and Resistance Levels with Breaks | `sr_breaks.py` |
| `liquidity_swings.pine` | Liquidity Swings (rebuilt from LuxAlgo's description) | `liquidity_swings.py` |

## Check that Pine and Python agree

1. Export bars and the Python values (coin, timeframe, number of bars):

```bash
cd C:\temp\AI\StockCryptoScreener\freqtrade-lab
.venv\Scripts\python.exe ..\tradestation-pine\export_golden.py btc_4h.csv BTC 4h 2500
```

2. Run the Pine files in Trade Station's Pine engine and compare (timeframe in minutes):

```bash
cd C:\temp\myTradingview
node C:\temp\AI\StockCryptoScreener\tradestation-pine\compare.ts C:\temp\AI\StockCryptoScreener\freqtrade-lab\btc_4h.csv 240
```

Result on 2026-11-15: BTC 4h and ETH 1h, 2,500 bars each. Every value matches, except 1 ETH bar
where SuperTrend AI's factor differs (two scores tie in the last digit; the line and the direction
still match).

## Signals & Overlays — own build

`signals_overlays_own.pine` is **not** a port of LuxAlgo code. LuxAlgo's Signals & Overlays is paid
and closed. This file has the same features and settings layout, taken from LuxAlgo's public docs.
All the formulas are our own (they are listed at the top of the file), so it does not match
LuxAlgo's signals bar for bar. The copies of the paid script on Scribd, Pastebin and GitHub are
leaks; they were not used.

Not built: Custom Alert Creator, Alert Scripting, External Conditions.

Check it in Trade Station's Pine engine (csv columns: time in ms, open, high, low, close, volume;
then the timeframe in minutes):

```bash
cd C:\temp\myTradingview
node C:\temp\AI\StockCryptoScreener\tradestation-pine\check_signals_overlays.ts <bars.csv> 240
```

Result on 2026-11-16: BTC 4h, ETH 1h (3,000 bars each) and SOL 1d (2,218 bars). All checks pass:
signals alternate, exits are in profit, filters and presets do what they say, TP/SL levels are in
order, and no value on an old bar changes when new bars come in (no look-ahead). Not yet compiled
on TradingView itself.

The Python twin is `freqtrade-lab/research/signals_overlays.py`. To check that Python and Pine give
the same values (21 settings, every plot, every bar):

```bash
cd C:\temp\myTradingview
node C:\temp\AI\StockCryptoScreener\tradestation-pine\dump_signals_overlays.ts <bars.csv> 240 <out dir>
cd C:\temp\AI\StockCryptoScreener\freqtrade-lab
.venv\Scripts\python.exe ..\tradestation-pine\compare_signals_overlays.py <bars.csv> <out dir>
```

Backtest result (2026-11-16): `freqtrade-lab/research/SIGNALS_OVERLAYS_RESEARCH.md`.

## Notes

- The Pine engine rounds values kept in `var` and arrays to 10 decimal places. SuperTrend AI keeps
  its state in prices times 1,000,000 to avoid that.
- Level lines and zones start where they become known (no look-back offset), the same as the Python.
