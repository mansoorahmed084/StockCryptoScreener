# SMC Sweep-Break (4h entry, daily bias)

The one Smart Money Concepts setup out of ~2,000 tested that kept its edge on
203 coins it had never seen. Derivation: [SMC_RESEARCH.md](SMC_RESEARCH.md).
Code: [smc.py](smc.py); the config is `B_final` in [smc_oos.py](smc_oos.py).

## Rules (long; shorts are the mirror)

| step | rule |
|---|---|
| daily bias | the last daily CLOSE broke above the last unbroken daily swing high. Daily swings are 2-bar fractals (2 lower highs each side). Only closed daily candles count. |
| 4h swings | 5-bar fractals: a swing high has 5 lower highs on each side. It is only known 5 bars (20 hours) later. |
| trigger | a 4h candle CLOSES above the last unbroken 4h swing high (BOS or CHoCH, either) while the daily bias is up |
| liquidity sweep | the lowest candle of the leg that made that break (the origin) wicked BELOW the previous 4h swing low and CLOSED back above it |
| entry | market, at the open of the next 4h candle |
| stop | origin low − 0.5 × ATR(14) on 4h |
| skip | if the stop is under 0.5% or over 8% from the signal close |
| exit | the first of: the stop; +6R; a 4h close that breaks the last 4h swing LOW against a 4h uptrend (a bearish CHoCH); 28 days |
| per coin | one position at a time |
| size | 0.5-1% of equity at risk per trade, at most 10 open, total notional ≤ 5x equity |

In plain words: the daily chart is going up. On the 4h chart, price dips
under an old low (stops get taken), snaps back, and then closes above the last
high. Buy the next candle. Put the stop under the dip. Get out when the 4h
chart breaks its last low, or at 6R.

## Results

Binance USDT candles, 2020-01 to 2026-09, cost 0.06% per side, long and short.

| | 76 coins used to build it | **203 coins never used** | all 279 |
|---|---|---|---|
| trades | 681 | 1,053 | 1,734 |
| win rate | 40.8% | 36.3% | 38.1% |
| avg R per trade | +0.310 | **+0.245** | +0.270 |
| profit factor | 1.71 | 1.49 | 1.57 |
| at 0.10% cost per side | +0.296 | +0.231 | |
| years positive | 7/7 | 5/7 | 7/7 |
| longs / shorts avg R | +0.27 / +0.34 | +0.43 / +0.15 | +0.36 / +0.22 |

Average win **+1.96R**, average loss **-0.77R** (realised 2.55 : 1). The 6R
target is hit on only 7% of trades; 62% leave on the 4h CHoCH (avg +0.26R)
and 31% on the stop. Median hold 4.7 days. The best 20 trades are 26% of the
profit, so it does not rest on a few lucky runners.

**Account** (all 279 coins, profit banked at exit, worst case = every open
trade stopped at once):

| risk / slots | CAGR | max DD (closed) | worst case DD |
|---|---|---|---|
| **0.5% / 10** | **22.6%** | **15.0%** | 18.4% |
| 1% / 10 | 43.6% | 29.2% | 35.0% |
| 1% / 10, new coins only | 29.2% | 28.7% | 33.1% |

Per year (all coins, avg R / trades): 2020 +0.31/54, 2021 +0.35/27,
2022 +0.01/156, 2023 +0.17/461, 2024 +0.40/285, 2025 +0.34/339,
2026 +0.32/412.

### Controls (is the SMC part doing anything?)

| change | 76 old coins | 203 new coins |
|---|---|---|
| as specified | +0.310 | +0.245 |
| no liquidity sweep needed | +0.153 | +0.116 |
| 1h entry with 4h bias instead | +0.041 | +0.028 |
| 3-bar 4h swings instead of 5 | +0.185 | +0.136 |

The sweep doubles the edge on both coin sets, and the daily bias is
essential.

## What it is NOT

* **Not 60% accuracy.** The win rate is 36-41%. The R:R makes the money.
* **Not 1:3 on every trade.** Only 7% reach 6R. A fixed 3R or 4R target
  scored worse than letting the 4h structure decide the exit (round 5).
* **Not short term.** 4h candles, ~5-day holds. Every 15m and 1h SMC setup
  tested either lost money after costs or failed on the new coins.

## Known weaknesses

1. 2022 was flat (+0.01R on 156 trades). 2020-2022 earned +4-9% a year at
   0.5% risk; 2023-2026 carried the result.
2. Losing streaks are long: 27 losers in a row in the pooled book.
3. Funding is not modelled. At ~0.01% per 8h it costs about 0.005R a day
   against a 6% stop, so ~0.03R on a median trade. Shorts can be paid or pay.
4. Spot candles stand in for perpetual futures prices.
5. Selection bias: the family was picked after four rounds on the 76 coins,
   and the 203 were looked at twice (before and after the exit change, which
   was itself chosen on the 76 only).
6. Not yet checked in freqtrade, and not forward tested. The repo's rule is
   that nothing is banked until a second engine agrees.

## Live scan

```bash
cd freqtrade-lab
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe research/scan_smc.py
```

Run it just after a 4h candle closes (00:00, 04:00, 08:00, 12:00, 16:00,
20:00 UTC = 05:30, 09:30, 13:30, 17:30, 21:30, 01:30 IST). It reads live
Binance USDT perpetual candles (crypto only, 24h volume ≥ $10M; `--min-vol`,
`--dcx-only`, `--coins` change that) and prints:

* **NEW** — the candle that just closed made a signal. The backtest enters at
  the open of the candle forming now; `now R` shows how far price has moved
  since. Stop, stop % and the 6R target are given.
* **OPEN** — trades the strategy holds now, with the 4h close that ends each
  one (the CHoCH level). Exit when a 4h candle CLOSES beyond it.
* **CLOSED** — trades that ended on the last closed candle.

* **WATCH** (with `--watch [PCT]`, default 3%) — setups the FORMING 4h
  candle would trigger: either it fires if the candle closes at the current
  price, or it needs a close just past the live 4h swing within PCT% of
  price. The daily trend and the sweep are already in place. Checked on past
  signal candles: 196 of 196 found, 0 false alarms on 450 other candles.

It places nothing. About 40 seconds for ~170 coins.

**Checks.** [scan_smc_check.py](scan_smc_check.py) replays the scanner's own
code at past moments on the backtest data — with only the 1000 4h and 400
daily closed candles it gets live — and compares it with the backtest:
4,329 checks on 40 coins, **0 mismatches** (216 NEW, 224 OPEN, 216 CLOSED
events). Live candles are Binance FUTURES, the backtest used SPOT: on 30
coins from May to September 2026, 24 trades were the same, 5 were spot only
and 4 futures only. Same rules, slightly different candles.

## Paper trading (automatic)

A Windows scheduled task, **SMC Sweep-Break scan**, runs
`scan_smc.py --log` at :35 past 01, 05, 09, 13, 17 and 21 IST — 5 minutes
after each 4h close. Each run:

* logs every NEW call to [journal/smc_paper.csv](../../journal/smc_paper.csv)
  (entry = the backtest's fill, plus the price seen when the scan ran)
* closes each logged trade when the backtest rules exit it, with the R
* rebuilds [journal/SMC_PAPER.md](../../journal/SMC_PAPER.md): summary, open
  trades with the 4h close that would end each one, closed trades, last scan
* appends its output to `freqtrade-lab/user_data/logs/smc_scan.log`

It runs only while you are logged in. If the PC slept through a run, the
task runs once on waking; exits are still recorded at the right candle, and
an entry found after its candle closed is flagged `late` and left out of the
on-time numbers. [smc_paper_check.py](smc_paper_check.py) replays 120 days
of runs with 30% skipped at random: 0 failures against the backtest.

```powershell
cd freqtrade-lab
.\schedule-smc-scan.ps1           # create or update the task
.\schedule-smc-scan.ps1 -Remove   # delete it
```

Nothing is committed automatically; the journal files change on every run.

## How to reproduce

```bash
cd freqtrade-lab
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe research/smc_oos.py B_final
```
