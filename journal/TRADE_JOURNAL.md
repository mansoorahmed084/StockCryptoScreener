# Trade journal

Paper trades from the pattern scans: every setup the scans called, what happened
to it, and what we learn. **Not financial advice. No real money.**

- The trades are in [trades.csv](trades.csv): one row for each setup as it was
  called (entry rule, stop, target).
- To refresh the tables below, run
  `.venv/Scripts/python.exe -m backend.cli journal`. It replays every trade on
  Binance futures candles. The notes are written by hand, and an update never
  changes them.
- New setups are added every day at 20:00 IST by
  `.venv/Scripts/python.exe -m backend.cli setups --journal`, which uses
  fixed rules. The rules are: 1h / 4h / 1d only, daily and 4h trend up, no
  bearish setup on the coin, 5% of room to daily supply, and reward at least
  2× risk. The trades from 24–26 Sep were picked by hand from the scans.

## Rules

- **Entry "now":** the price when the list was made.
- **Entry "close above":** the first closed candle of the trade's timeframe
  that closes above the trigger (a flat level, or the falling flag line).
- **Exit:** the first 15-minute candle whose low touches the stop, or whose
  high touches the target. If both happen in one candle, it counts as the stop.
- **Close-stop test:** the same trade, but the stop needs a candle of the
  trade's timeframe to *close* below it. This tests if wick stops shake us out.
- **P&L:** $100 a trade, no fees. Open trades use the last price.

## Scoreboard

<!-- AUTO:SUMMARY -->
_Updated 26 Sep 2026 14:58 UTC. Open trades are marked at the last price._

| | Setups | Triggered | 🎯 Target | ❌ Stopped | ⏳ Open | Up / down | P&L, $100 a trade | P&L with close-stops |
|---|---|---|---|---|---|---|---|---|
| **All** | 32 | 23 | 2 | 5 | 16 | 11 / 12 | **+65.91** (on $2,300) | +82.37 |
| Bought at once ("buy now") | 14 | 14 | 0 | 3 | 11 | 5 / 9 | **+26.60** (on $1,400) | +44.48 |
| Waited for a close above the line | 18 | 9 | 2 | 2 | 5 | 6 / 3 | **+39.31** (on $900) | +37.89 |

By list:

| | Setups | Triggered | 🎯 Target | ❌ Stopped | ⏳ Open | Up / down | P&L, $100 a trade | P&L with close-stops |
|---|---|---|---|---|---|---|---|---|
| 24 Sep 15:10 best buys | 5 | 5 | 1 | 1 | 3 | 3 / 2 | **+57.59** (on $500) | +56.56 |
| 25 Sep 10:15 morning | 6 | 6 | 1 | 1 | 4 | 3 / 3 | **+15.52** (on $600) | +15.47 |
| 25 Sep 11:45 buy now | 5 | 5 | 0 | 2 | 3 | 1 / 4 | **-13.39** (on $500) | +5.52 |
| 25 Sep 11:45 about to break | 1 | 1 | 0 | 1 | 0 | 0 / 1 | **-2.21** (on $100) | -3.57 |
| 25 Sep 12:05 alerts | 7 | 3 | 0 | 0 | 3 | 2 / 1 | **+5.28** (on $300) | +5.28 |
| 26 Sep 14:00 buy now | 3 | 3 | 0 | 0 | 3 | 2 / 1 | **+3.12** (on $300) | +3.12 |
| 26 Sep 14:00 about to break | 5 | 0 | 0 | 0 | 0 | 0 / 0 | **+0.00** (on $0) | +0.00 |
<!-- /AUTO:SUMMARY -->

## What works and what doesn't

_Small sample: 23 trades in 3 days, all in one market (a daily uptrend in BTC
with sharp intraday dips). Treat every point below as a lead to test, not a
proven edge._

**Worked**
- **Waiting for a candle close above the line.** 6 of 9 went up (+$37.70 on
  $900). Buying at once went 4 up and 10 down (+$25.70 on $1,400, most of it
  from two trades on 24 Sep).
- **1h bull flags in a daily and 4h uptrend, with room below daily supply.**
  ENA hit its target (+24%). ENA from 24 Sep is +29%, KAS is +23%, and JUP hit
  its target (+12%).
- **Buying when the BTC dip had ended.** The 24 Sep list was the best:
  +$56.84 on $500.
- **Stops that need a close.** With close-stops, P&L is +$79.37 instead of
  +$63.39. DASH would have hit its target (+10%) instead of stopping at −4.8%.
  ARB would still be open instead of stopping at −3.6%.

**Didn't work**
- **Buying "now" just as BTC's breakout failed.** The 25 Sep 11:45 list went 0
  up and 5 down (−$13.38). BTC closed back under 84,820 minutes later.
- **Tight stops just under the flag low.** LTC (0.4% away) and KITE (3% away)
  were stopped, and then both went up. KITE's later alert entry is +4%.
- **Chasing a 15m break that had already happened.** XLM was stopped in 90
  minutes.
- **A wide stop plus a bearish pattern on the same coin.** VVV bled slowly, to
  −3% and −5%.

**To test next**
- Make close-stops the default rule once there are more trades.
- A BTC filter: skip buys while BTC's 15m or 1h chart is breaking down.
- Take part of the profit near +5%. INJ, KITE and LTC were all up about 5%
  and then gave it back. The flag targets (the full pole) are far away.

## Daily notes

### 26 Sep
- BTC held 83,330 overnight and is at about 84,000. A 4h bull flag triggers on a
  4h close above 84,500 and fails below 82,830.
- The KITE, LTC and LDO alerts triggered yesterday evening. KITE and LTC are up
  and LDO is down. The ETH, BNB, HYPE and INJ alerts have not triggered.
- New buys: AVAX, BONK and GRAM (1h flags that broke up). Waiting for a close:
  SUI, SOL, HBAR, SHIB and GRT (1h flags).

### 25 Sep
- BTC closed a 15m candle above 84,820 at 11:15 UTC, then fell back under it
  by 11:45. The "buy now" list made at 11:45 caught that failure.
- ENA hit its target the next morning (+24%). DASH was stopped at 15:30 and
  then ran past its target.
- Alerts were set on 7 "about to break" coins. 3 triggered the same evening.

### 24 Sep
- A short BTC dip inside a daily uptrend. The list was ENA, ETC, KITE, JUP and
  KAS.
- ENA (+29%) and KAS (+23%) ran. JUP hit its target. KITE was stopped (tight
  stop), and ETC is −4%.

## Trades

<!-- AUTO:TRADES -->
### 26 Sep 14:00 about to break — 0/5 triggered, +0.00 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 28 | SUI | 1h | Bull flag | waits for a 1h close above line | 1.1499 | 1.418 | 💤 not triggered | — | — | — | falling flag line |
| 29 | SOL | 1h | Bull flag | waits for a 1h close above line | 119.78 | 131.9 | 💤 not triggered | — | — | — | falling flag line; tight stop |
| 30 | HBAR | 1h | Bull flag | waits for a 1h close above line | 0.08808 | 0.124 | 💤 not triggered | — | — | — | falling flag line |
| 31 | SHIB | 1h | Bull flag | waits for a 1h close above line | 0.005534 | 0.007484 | 💤 not triggered | — | — | — | falling flag line |
| 32 | GRT | 1h | Bull flag | waits for a 1h close above line | 0.02719 | 0.03286 | 💤 not triggered | — | — | — | falling flag line |

### 26 Sep 14:00 buy now — 3/3 triggered, +3.12 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 25 | AVAX | 1h | Bull flag | 10.83 (26 Sep 14:05) | 9.972 | 15.27 | ⏳ open | **+1.8%** | ⏳ +1.8% | +2.2% / +0.1% | broke up |
| 26 | BONK | 1h | Bull flag | 0.003699 (26 Sep 14:05) | 0.003378 | 0.00542 | ⏳ open | **+1.5%** | ⏳ +1.5% | +1.8% / -0.2% | 15m + 1h flags broke up; 4h flag at the line |
| 27 | GRAM | 1h | Bull flag | 1.479 (26 Sep 14:05) | 1.386 | 1.664 | ⏳ open | **-0.1%** | ⏳ -0.1% | +0.3% / -0.8% | broke up; 4h triangle 0.5% away |

### 25 Sep 12:05 alerts — 3/7 triggered, +5.28 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 18 | BNB | 1h | Bull flag | waits for a 1h close above line | 756.89 | 891.38 | 💤 not triggered | — | — | — | alert on the falling flag line |
| 19 | KITE | 1h | Bull flag | 0.13145 (25 Sep 18:00) | 0.12502 | 0.16641 | ⏳ open | **+4.2%** | ⏳ +4.2% | +6.6% / -0.0% | alert on the falling flag line |
| 20 | LDO | 4h | Ascending triangle | 0.4999 (25 Sep 20:00) | 0.43095 | 0.5783 | ⏳ open | **-1.5%** | ⏳ -1.5% | +1.5% / -4.5% | line + tolerance (price was on the line) |
| 21 | HYPE | 1h | Bull flag | waits for a 1h close above line | 89.828 | 111.64 | 💤 not triggered | — | — | — | alert on the falling flag line |
| 22 | INJ | 4h | Double bottom | waits for a 4h close above 8.378 | — | 9.3 | 💤 not triggered | — | — | — | neckline; no stop given |
| 23 | LTC | 1h | Bull flag | 71.03 (25 Sep 19:00) | 69.91 | 86.894 | ⏳ open | **+2.6%** | ⏳ +2.6% | +5.6% / -0.6% | line + tolerance (price was on the line) |
| 24 | ETH | 1h | Bull flag | waits for a 1h close above line | 2,626.01 | 3,204.44 | 💤 not triggered | — | — | — | alert on the falling flag line |

### 25 Sep 11:45 about to break — 1/1 triggered, -2.21 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 17 | XLM | 15m | Ascending triangle | 0.22385 (25 Sep 12:15) | 0.2189 | 0.2508 | ❌ stopped 25 Sep 13:45 | **-2.2%** | ❌ -3.6% | +0.8% / -4.2% | broke before its alert was set |

### 25 Sep 11:45 buy now — 5/5 triggered, -13.39 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 12 | BONK | 4h | Ascending triangle | 0.003749 (25 Sep 11:50) | 0.003461 | 0.004917 | ⏳ open | **+0.1%** | ⏳ +0.1% | +0.6% / -3.9% | broke up |
| 13 | ENS | 4h | Ascending triangle | 7.242 (25 Sep 11:50) | 6.711 | 8.147 | ⏳ open | **-1.5%** | ⏳ -1.5% | +0.5% / -3.6% | broke up; daily demand just below |
| 14 | DASH | 1h | Bull flag | 64.79 (25 Sep 11:50) | 61.67 | 71.25 | ❌ stopped 25 Sep 15:30 | **-4.8%** | 🎯 +10.0% | +12.7% / -5.6% | flag + triangle broke up |
| 15 | ARB | 1h | Ascending triangle | 0.2245 (25 Sep 11:50) | 0.2165 | 0.2366 | ❌ stopped 25 Sep 14:00 | **-3.6%** | ⏳ +0.6% | +2.9% / -3.6% | broke up; 15m double bottom |
| 16 | VVV | 1h | Bull flag | 31.37 (25 Sep 11:50) | 28.38 | 44.61 | ⏳ open | **-3.6%** | ⏳ -3.6% | +0.6% / -6.4% | broke up; bearish 15m pattern too |

### 25 Sep 10:15 morning — 6/6 triggered, +15.52 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 6 | HBAR | 1h | Bull flag | 0.09352 (25 Sep 11:00) | 0.0881 | 0.118 | ⏳ open | **+0.7%** | ⏳ +0.7% | +3.3% / -1.2% | 1h + 15m flags at the line |
| 7 | INJ | 1h | Bull flag | 8.041 (25 Sep 10:20) | 7.456 | 10.6 | ⏳ open | **-2.6%** | ⏳ -2.6% | +4.6% / -4.8% | broke up; 15m double bottom forming |
| 8 | BONK | 4h | Ascending triangle | 0.003744 (25 Sep 12:00) | 0.003461 | 0.004917 | ⏳ open | **+0.3%** | ⏳ +0.3% | +0.7% / -3.7% | 4h triangle at the line + 15m flag |
| 9 | ENA | 1h | Ascending triangle | 0.22867 (25 Sep 11:00) | 0.2079 | 0.2841 | 🎯 target 26 Sep 10:15 | **+24.2%** | 🎯 +24.2% | +25.0% / -0.2% | 15m flag + 1h triangle |
| 10 | VVV | 4h | Bull flag | 32.06 (25 Sep 10:20) | 28.38 | 44.64 | ⏳ open | **-5.7%** | ⏳ -5.7% | +1.1% / -8.4% | 4h + 1h flags broke up; wide stop |
| 11 | LTC | 1h | Bull flag | 70.85 (25 Sep 11:00) | 69.91 | 87.34 | ❌ stopped 25 Sep 12:15 | **-1.3%** | ❌ -1.4% | +5.8% / -2.9% | 15m flag broke up; very tight stop |

### 24 Sep 15:10 best buys — 5/5 triggered, +57.59 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ENA | 1h | Bull flag | 0.216 (24 Sep 15:15) | 0.1977 | 0.311 | ⏳ open | **+28.7%** | ⏳ +28.7% | +32.3% / -0.7% | broke up |
| 2 | ETC | 4h | Ascending triangle | 9.916 (24 Sep 15:15) | 9.053 | 12.04 | ⏳ open | **-3.8%** | ⏳ -3.8% | +3.3% / -8.1% | broke up; 15m double bottom too |
| 3 | KITE | 1h | Bull flag | 0.1326 (24 Sep 15:15) | 0.1286 | 0.1619 | ❌ stopped 25 Sep 00:45 | **-3.0%** | ❌ -4.0% | +5.7% / -5.7% | 15m and 1h flags broke up |
| 4 | JUP | 1h | Ascending triangle | 0.3049 (24 Sep 16:00) | 0.2742 | 0.3427 | 🎯 target 25 Sep 20:30 | **+12.4%** | 🎯 +12.4% | +16.2% / -2.2% | 1h + 4h flags and a 1h triangle at the line |
| 5 | KAS | 4h | Bull flag | 0.03944 (24 Sep 15:15) | 0.0377 | 0.05276 | ⏳ open | **+23.2%** | ⏳ +23.2% | +23.9% / -0.0% | at the line; 4h trend mixed |
<!-- /AUTO:TRADES -->
