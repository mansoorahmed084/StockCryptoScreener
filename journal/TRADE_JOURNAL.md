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
_Updated 27 Sep 2026 06:09 UTC. Open trades are marked at the last price._

| | Setups | Triggered | 🎯 Target | ❌ Stopped | ⏳ Open | Up / down | P&L, $100 a trade | P&L with close-stops |
|---|---|---|---|---|---|---|---|---|
| **All** | 41 | 32 | 2 | 7 | 23 | 13 / 19 | **+57.11** (on $3,200) | +78.70 |
| Bought at once ("buy now") | 17 | 17 | 0 | 4 | 13 | 6 / 11 | **+15.72** (on $1,700) | +39.31 |
| Waited for a close above the line | 24 | 15 | 2 | 3 | 10 | 7 / 8 | **+41.39** (on $1,500) | +39.39 |

By list:

| | Setups | Triggered | 🎯 Target | ❌ Stopped | ⏳ Open | Up / down | P&L, $100 a trade | P&L with close-stops |
|---|---|---|---|---|---|---|---|---|
| 24 Sep 15:10 best buys | 5 | 5 | 1 | 1 | 3 | 3 / 2 | **+54.29** (on $500) | +53.27 |
| 25 Sep 10:15 morning | 6 | 6 | 1 | 2 | 3 | 2 / 4 | **+6.29** (on $600) | +10.86 |
| 25 Sep 11:45 buy now | 5 | 5 | 0 | 2 | 3 | 0 / 5 | **-18.77** (on $500) | +1.23 |
| 25 Sep 11:45 about to break | 1 | 1 | 0 | 1 | 0 | 0 / 1 | **-2.21** (on $100) | -3.57 |
| 25 Sep 12:05 alerts | 7 | 4 | 0 | 0 | 4 | 3 / 1 | **+14.91** (on $400) | +14.91 |
| 26 Sep 14:00 buy now | 3 | 3 | 0 | 0 | 3 | 2 / 1 | **+7.05** (on $300) | +7.05 |
| 26 Sep 14:00 about to break | 5 | 4 | 0 | 1 | 3 | 0 / 4 | **-5.63** (on $400) | -6.22 |
| 27 Sep 06:08 buy now | 3 | 3 | 0 | 0 | 3 | 2 / 1 | **+0.05** (on $300) | +0.05 |
| 27 Sep 06:08 about to break | 5 | 0 | 0 | 0 | 0 | 0 / 0 | **+0.00** (on $0) | +0.00 |
| 26 Sep 15:20 S/ARB analysis | 1 | 1 | 0 | 0 | 1 | 1 / 0 | **+1.12** (on $100) | +1.12 |
<!-- /AUTO:SUMMARY -->

## What works and what doesn't

_Small sample: 32 triggered trades in 4 days, all in one market (a daily
uptrend in BTC with sharp intraday dips). Treat every point below as a lead to
test, not a proven edge. Last checked 27 Sep 06:10 UTC._

**Worked**
- **Waiting for a candle close above the line — but the lead is getting
  smaller.** Waiting: 7 up and 8 down (+$41.39 on $1,500). Buying at once: 6 up
  and 11 down (+$15.72 on $1,700). The 26 Sep "wait for a 1h close" list went
  0 up and 4 down, so 1h closes alone are not enough.
- **1h bull flags in a daily and 4h uptrend, with room below daily supply.**
  ENA hit its target (+24%). ENA from 24 Sep is +29%, KAS is +23%, and JUP hit
  its target (+12%). The KITE alert entry is +16%, and GRAM is +7.5%.
- **Buying when the BTC dip had ended.** The 24 Sep list is still the best:
  +$54.18 on $500.
- **Stops that need a close.** With close-stops, P&L is +$78.70 instead of
  +$57.11. DASH would have hit its target (+10%) instead of stopping at −4.8%.
  ARB would be +1.7% instead of stopped at −3.6%.

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

### 27 Sep (morning, 06:10 UTC)
- BTC is 84,480. Its 4h bull flag broke up (line 83,725), and the 1h chart is
  in an uptrend. It still sits under resistance at 84,550–84,850.
- Overnight, the ARB 1h flag alert triggered (0.2257, now +1%) and the HYPE
  alert triggered (92.62, now +0.6%). SUI was stopped (−2.8%). S broke down
  under 0.0404, which matched its sell alert.
- The first picks by the fixed rules: buy now USELESS, BTC and SEI (4h and 1h
  flags). Waiting for a 4h close: HBAR, ARB, BONK, ETH and AVAX.

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
### 26 Sep 15:20 S/ARB analysis — 1/1 triggered, +1.12 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 41 | ARB | 1h | Bull flag | 0.22573 (26 Sep 15:00) | 0.2102 | 0.2445 | ⏳ open | **+1.1%** | ⏳ +1.1% | +2.3% / -3.6% | alert on the 4h/1h flag line; targets 0.2282 / 0.2320 / 0.2445 |

### 27 Sep 06:08 about to break — 0/5 triggered, +0.00 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 36 | HBAR | 4h | Bull flag | waits for a 4h close above line | 0.08808 | 0.12391 | 💤 not triggered | — | — | — | auto: score 10, reward/risk 5.3 |
| 37 | ARB | 4h | Bull flag | waits for a 4h close above line | 0.21022 | 0.35207 | 💤 not triggered | — | — | — | auto: score 9, reward/risk 7.2 |
| 38 | BONK | 4h | Bull flag | waits for a 4h close above line | 0.003378 | 0.005425 | 💤 not triggered | — | — | — | auto: score 9, reward/risk 6.6 |
| 39 | ETH | 4h | Bull flag | waits for a 4h close above line | 2,626.01 | 3,158.84 | 💤 not triggered | — | — | — | auto: score 9, reward/risk 5.6 |
| 40 | AVAX | 4h | Bull flag | waits for a 4h close above line | 9.972 | 15.67 | 💤 not triggered | — | — | — | auto: score 9, reward/risk 5.2 |

### 27 Sep 06:08 buy now — 3/3 triggered, +0.05 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 33 | USELESS | 4h | Bull flag | 0.2894 (27 Sep 06:08) | 0.27009 | 0.44965 | ⏳ open | **+0.1%** | ⏳ +0.1% | — / — | auto: score 9, reward/risk 8.3 |
| 34 | BTC | 4h | Bull flag | 84,497.30 (27 Sep 06:08) | 82,832.00 | 96,200.36 | ⏳ open | **+0.0%** | ⏳ +0.0% | — / — | auto: score 8, reward/risk 7.0 |
| 35 | SEI | 1h | Bull flag | 0.07365 (27 Sep 06:08) | 0.07041 | 0.09312 | ⏳ open | **-0.1%** | ⏳ -0.1% | — / — | auto: score 8, reward/risk 6.0 |

### 26 Sep 14:00 about to break — 4/5 triggered, -5.63 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 28 | SUI | 1h | Bull flag | 1.1831 (26 Sep 16:00) | 1.1499 | 1.418 | ❌ stopped 26 Sep 20:30 | **-2.8%** | ❌ -3.4% | +0.6% / -4.6% | falling flag line |
| 29 | SOL | 1h | Bull flag | 121.83 (26 Sep 16:00) | 119.78 | 131.9 | ⏳ open | **-0.4%** | ⏳ -0.4% | +0.0% / -1.5% | falling flag line; tight stop |
| 30 | HBAR | 1h | Bull flag | 0.09516 (26 Sep 16:00) | 0.08808 | 0.124 | ⏳ open | **-1.3%** | ⏳ -1.3% | +0.2% / -3.6% | falling flag line |
| 31 | SHIB | 1h | Bull flag | 0.00597 (26 Sep 15:00) | 0.005534 | 0.007484 | ⏳ open | **-1.1%** | ⏳ -1.1% | +1.8% / -2.7% | falling flag line |
| 32 | GRT | 1h | Bull flag | waits for a 1h close above line | 0.02719 | 0.03286 | 💤 not triggered | — | — | — | falling flag line |

### 26 Sep 14:00 buy now — 3/3 triggered, +7.05 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 25 | AVAX | 1h | Bull flag | 10.83 (26 Sep 14:05) | 9.972 | 15.27 | ⏳ open | **+0.8%** | ⏳ +0.8% | +2.8% / -2.7% | broke up |
| 26 | BONK | 1h | Bull flag | 0.003699 (26 Sep 14:05) | 0.003378 | 0.00542 | ⏳ open | **-1.4%** | ⏳ -1.4% | +1.9% / -3.6% | 15m + 1h flags broke up; 4h flag at the line |
| 27 | GRAM | 1h | Bull flag | 1.479 (26 Sep 14:05) | 1.386 | 1.664 | ⏳ open | **+7.6%** | ⏳ +7.6% | +10.5% / -0.8% | broke up; 4h triangle 0.5% away |

### 25 Sep 12:05 alerts — 4/7 triggered, +14.91 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 18 | BNB | 1h | Bull flag | waits for a 1h close above line | 756.89 | 891.38 | 💤 not triggered | — | — | — | alert on the falling flag line |
| 19 | KITE | 1h | Bull flag | 0.13145 (25 Sep 18:00) | 0.12502 | 0.16641 | ⏳ open | **+15.8%** | ⏳ +15.8% | +21.6% / -0.0% | alert on the falling flag line |
| 20 | LDO | 4h | Ascending triangle | 0.4999 (25 Sep 20:00) | 0.43095 | 0.5783 | ⏳ open | **-3.1%** | ⏳ -3.1% | +1.5% / -6.3% | line + tolerance (price was on the line) |
| 21 | HYPE | 1h | Bull flag | 92.62 (26 Sep 17:00) | 89.828 | 111.64 | ⏳ open | **+0.5%** | ⏳ +0.5% | +1.4% / -1.8% | alert on the falling flag line |
| 22 | INJ | 4h | Double bottom | waits for a 4h close above 8.378 | — | 9.3 | 💤 not triggered | — | — | — | neckline; no stop given |
| 23 | LTC | 1h | Bull flag | 71.03 (25 Sep 19:00) | 69.91 | 86.894 | ⏳ open | **+1.7%** | ⏳ +1.7% | +5.6% / -0.6% | line + tolerance (price was on the line) |
| 24 | ETH | 1h | Bull flag | waits for a 1h close above line | 2,626.01 | 3,204.44 | 💤 not triggered | — | — | — | alert on the falling flag line |

### 25 Sep 11:45 about to break — 1/1 triggered, -2.21 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 17 | XLM | 15m | Ascending triangle | 0.22385 (25 Sep 12:15) | 0.2189 | 0.2508 | ❌ stopped 25 Sep 13:45 | **-2.2%** | ❌ -3.6% | +0.8% / -5.1% | broke before its alert was set |

### 25 Sep 11:45 buy now — 5/5 triggered, -18.77 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 12 | BONK | 4h | Ascending triangle | 0.003749 (25 Sep 11:50) | 0.003461 | 0.004917 | ⏳ open | **-2.7%** | ⏳ -2.7% | +0.6% / -4.9% | broke up |
| 13 | ENS | 4h | Ascending triangle | 7.242 (25 Sep 11:50) | 6.711 | 8.147 | ⏳ open | **-2.5%** | ⏳ -2.5% | +0.5% / -5.3% | broke up; daily demand just below |
| 14 | DASH | 1h | Bull flag | 64.79 (25 Sep 11:50) | 61.67 | 71.25 | ❌ stopped 25 Sep 15:30 | **-4.8%** | 🎯 +10.0% | +13.7% / -5.6% | flag + triangle broke up |
| 15 | ARB | 1h | Ascending triangle | 0.2245 (25 Sep 11:50) | 0.2165 | 0.2366 | ❌ stopped 25 Sep 14:00 | **-3.6%** | ⏳ +1.6% | +2.9% / -3.6% | broke up; 15m double bottom |
| 16 | VVV | 1h | Bull flag | 31.37 (25 Sep 11:50) | 28.38 | 44.61 | ⏳ open | **-5.2%** | ⏳ -5.2% | +0.6% / -7.4% | broke up; bearish 15m pattern too |

### 25 Sep 10:15 morning — 6/6 triggered, +6.29 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 6 | HBAR | 1h | Bull flag | 0.09352 (25 Sep 11:00) | 0.0881 | 0.118 | ⏳ open | **+0.4%** | ⏳ +0.4% | +3.3% / -1.9% | 1h + 15m flags at the line |
| 7 | INJ | 1h | Bull flag | 8.041 (25 Sep 10:20) | 7.456 | 10.6 | ❌ stopped 26 Sep 20:45 | **-7.3%** | ⏳ -2.6% | +4.6% / -7.8% | broke up; 15m double bottom forming |
| 8 | BONK | 4h | Ascending triangle | 0.003744 (25 Sep 12:00) | 0.003461 | 0.004917 | ⏳ open | **-2.5%** | ⏳ -2.5% | +0.7% / -4.8% | 4h triangle at the line + 15m flag |
| 9 | ENA | 1h | Ascending triangle | 0.22867 (25 Sep 11:00) | 0.2079 | 0.2841 | 🎯 target 26 Sep 10:15 | **+24.2%** | 🎯 +24.2% | +25.0% / -0.2% | 15m flag + 1h triangle |
| 10 | VVV | 4h | Bull flag | 32.06 (25 Sep 10:20) | 28.38 | 44.64 | ⏳ open | **-7.2%** | ⏳ -7.2% | +1.1% / -9.4% | 4h + 1h flags broke up; wide stop |
| 11 | LTC | 1h | Bull flag | 70.85 (25 Sep 11:00) | 69.91 | 87.34 | ❌ stopped 25 Sep 12:15 | **-1.3%** | ❌ -1.4% | +5.8% / -2.9% | 15m flag broke up; very tight stop |

### 24 Sep 15:10 best buys — 5/5 triggered, +54.29 $

| # | Coin | TF | Setup | Entry | Stop | Target | Result | P&L | With close-stop | Best / worst | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ENA | 1h | Bull flag | 0.216 (24 Sep 15:15) | 0.1977 | 0.311 | ⏳ open | **+26.1%** | ⏳ +26.1% | +32.3% / -0.7% | broke up |
| 2 | ETC | 4h | Ascending triangle | 9.916 (24 Sep 15:15) | 9.053 | 12.04 | ⏳ open | **-5.0%** | ⏳ -5.0% | +3.3% / -8.1% | broke up; 15m double bottom too |
| 3 | KITE | 1h | Bull flag | 0.1326 (24 Sep 15:15) | 0.1286 | 0.1619 | ❌ stopped 25 Sep 00:45 | **-3.0%** | ❌ -4.0% | +20.5% / -5.7% | 15m and 1h flags broke up |
| 4 | JUP | 1h | Ascending triangle | 0.3049 (24 Sep 16:00) | 0.2742 | 0.3427 | 🎯 target 25 Sep 20:30 | **+12.4%** | 🎯 +12.4% | +16.2% / -2.2% | 1h + 4h flags and a 1h triangle at the line |
| 5 | KAS | 4h | Bull flag | 0.03944 (24 Sep 15:15) | 0.0377 | 0.05276 | ⏳ open | **+23.8%** | ⏳ +23.8% | +27.5% / -0.0% | at the line; 4h trend mixed |
<!-- /AUTO:TRADES -->
