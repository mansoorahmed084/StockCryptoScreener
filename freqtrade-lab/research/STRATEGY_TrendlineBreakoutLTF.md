# TrendlineBreakoutLTF — daily trendline break, 1h stop, 25% trail

**Status (2026-09-14):** the strongest result in this repo, confirmed by two
independent engines. **Not yet traded forward.** Paper trade before any real
money, and read [Known weaknesses](#known-weaknesses) first — most of the profit
comes from a small number of trades, and at its worst the account value fell
**38%** while trades were open.

Freqtrade class: [TrendlineBreakoutLTF](../user_data/strategies/TrendlineBreakoutLTF.py)
(inherits the daily signal from [TrendlineBreakout](../user_data/strategies/TrendlineBreakout.py))
Research: [trendline.py](trendline.py) · [refine.py](refine.py) ·
[rf_final.py](rf_final.py) · [RESULTS_refined_entries.md](RESULTS_refined_entries.md)
Parent strategy: [STRATEGY_TrendlineBreakout.md](STRATEGY_TrendlineBreakout.md)

---

## At a glance

**What it does, in five steps**

1. Every day, for each coin, draw the falling trendline across its lower highs.
2. When a daily candle closes above that line on strong volume, buy at the next
   daily open.
3. Put the stop just under that day's low (minus a little 1h volatility). This
   is usually about **7% below** the entry.
4. As price rises, move a stop **25% below the highest price** since entry.
   The stop never moves down.
5. Sell when price hits that stop, or after 365 days.

**The numbers** — freqtrade, 76 Binance spot coins, 2020-01-01 → 2026-09-07,
10,000 USDT start, max 10 open trades, 1% risk per trade, 15m fills.

| | TrendlineBreakoutLTF | TrendlineBreakout (daily stop, 3R trail) |
|---|---|---|
| **CAGR** | **49.0%** | 14.1% |
| CAGR, closed trades only | 44.2% | 11.3% |
| **Max drawdown, account value** (open trades marked daily) | **38.4%** | 28.7% |
| Max drawdown, closed trades only | 20.8% | 21.0% |
| Total return | +1,342% (10k → 144k) | +141% |
| Trades | 208 (~31 a year) | 163 (~24 a year) |
| Win rate | 30.8% | 37.4% |
| Profit factor | 2.80 | 1.80 |
| Average hold | 25 days (winners 53, losers 13) | 55 days |
| Typical loss | −6.9% | −21% |
| Average win | +61.1% | — |
| Worst losing streak | 24 trades | 16 trades |

The research engine, built separately, gets **48.3% CAGR**, a 21.1% drawdown on
closed trades, and a **34.1%** drawdown with open trades marked daily.

**Four warnings before anything else**

- **The real worst drop is about 38%, not 21%.** The 21% counts closed trades
  only. With open trades valued every day, the account fell 38.4% in 2024.
- **Five trades made 68% of the profit.** The best one (XLM, +367%) made 21%.
- **2022 and 2025 were flat** (+0.6% and +0.5%). The strategy needs a market
  that fell hard first and then turned.
- **Positions are big.** The median entry is 12.6% of the account, and the
  largest was 37.7%. The account was fully invested at its peak.

---

## Where it came from

1. The trader sent two daily charts, TAO/USDT and STX/USDT. Each showed one
   falling line across a year of lower highs, and a break that ran far.
2. That became [TrendlineBreakout](STRATEGY_TrendlineBreakout.md). It uses a
   daily stop about 21% away and a 3R trailing exit. It earned 14.5% CAGR in
   freqtrade.
3. A 600-permutation study ([RESULTS_refined_entries.md](RESULTS_refined_entries.md))
   then asked whether 1h candles could improve the entry, the stop, or the exit:
   - **Entry timing: no.** Waiting for a 1h confirmation, a retest, or a
     pullback all did worse than buying the next daily open. These breaks go
     immediately, and waiting misses the ones that run.
   - **Stop placement: yes.** A 1h-based stop cuts the distance from ~21% to
     ~7%, so the same price move earns about three times more R.
   - **Exit: it must change too.** An R-based trail shrinks with the stop, which
     cancels the gain. A percent trail does not.

---

## The rules, exactly

**Universe:** 76 Binance USDT spot pairs (`config-big.json`, listed in
[campaign.py](campaign.py)). **Direction:** long only. **Market:** spot, no
leverage.

### Timeframes

| job | timeframe |
|---|---|
| draw the trendline, detect the break | **1d** candles |
| enter | next **1d** open (00:00 UTC) |
| measure volatility for the stop | **1h** candles, ATR(14) |
| simulate fills in backtests | **15m** candles (checked against 1h and 5m); before 2020-10-01 only daily candles exist |

### Signal — the daily trendline break (inherited, unchanged)

At each daily close, the line is rebuilt only from **earlier** bars:

```
anchor a = the highest high of the previous 200 days
slope  s = max over k in (a, today) of (high[k] - high[a]) / (k - a)
line     = high[a] + s * (today - a)
```

That is the shallowest falling line from the peak that no later high crosses.
It is the line a trader draws by hand. All of these must be true:

| # | condition | parameter |
|---|---|---|
| 1 | the line falls: `s < 0` | — |
| 2 | at least 60 days from the anchor to today | `MIN_SPAN = 60` |
| 3 | price fell at least 25% below the anchor at some point | `MIN_DROP_PCT = 0.25` |
| 4 | at least 3 highs lie within 3% of the line (anchor included) | `MIN_TOUCHES = 3`, `TOUCH_TOL = 0.03` |
| 5 | today closes above the line **and** yesterday closed at or below it | — |
| 6 | today's volume ≥ 1.5 × its 20-day average | `VOL_MULT = 1.5` |
| 7 | one signal per anchor, and 20 days since the last signal on that coin | `COOLDOWN = 20` |
| 8 | the parent's **daily** stop (20-day low − 1.5 × ATR(14), daily) is no more than 25% below the close | `MAX_RISK_PCT = 0.25` |

Rule 8 is easy to miss. The daily stop is no longer used to exit, but it still
**filters** signals before the 1h stop is placed. The research path does the
same (`trendline_breakout(**FINAL)` keeps `max_risk_pct=0.25`), so the two
engines trade the same set of breaks.

### Entry

Buy at the **open of the next daily candle**. Do not wait for anything else.

### Stop — placed from 1h structure

```
stop = low of the signal day  -  1.0 * ATR(14) on 1h candles
```

- The ATR is read from the **1h candle stamped 23:00** on the signal day. That
  candle closes at the same moment as the daily candle, so nothing from the
  future is used.
- The research defines this as "lowest 1h low of the last 24 hours". Those 24
  hours are exactly the signal day, so it equals the daily low. Verified on 169
  signals: 0 mismatches.
- **Skip the trade** if the stop is less than **2%** or more than **25%** below
  the signal-day close (`MIN_RISK_PCT`, `MAX_RISK_PCT`). A stop closer than 2%
  sits inside normal hourly noise.

### Exit

| rule | detail |
|---|---|
| trailing stop | `stop = max(initial stop, highest price since entry × 0.75)` |
| when it starts | at once — but with a ~7% starting stop it only rises above that stop once price is ~24% up, and only passes the entry price once price is ~33% up |
| it never loosens | the peak only rises, so the stop only rises |
| time stop | sell after **365 days** (`TIME_STOP_BARS`) |
| no profit target | `minimal_roi = {"0": 100}` — the trail is the only way out in profit |

### Position size

```
stake = (account value × 1%) / stop distance
```

- Account value is freqtrade's `get_total_stake_amount()`: free cash plus money
  held in open trades.
- Freqtrade also caps each stake at the cash it has free. So when the account is
  full, the next trade gets less money or is refused.
- A 7% stop means a ~14% position. **Ten open trades can need more than the
  whole account.** In the backtest, freqtrade refused 2,129 entry signals.

### Concurrency and costs

| | |
|---|---|
| max open trades | **10**. `config-big.json` says 30 — always pass `--max-open-trades 10` |
| fees | freqtrade: 0.1% per side (Binance spot, confirmed on all 208 trades), no slippage. Research: 0.15% per side (fee + 0.05% slippage) |

---

## How to run it

All commands from `freqtrade-lab/`.

**1. Get the data** (daily for the signal, 1h for the stop, 15m for fills):

```bash
./.venv/Scripts/python.exe -m freqtrade download-data --config config-big.json --timeframes 1d 1h 15m --timerange 20190101-
```

**2. Backtest it in freqtrade:**

```bash
./.venv/Scripts/python.exe -m freqtrade backtesting --config config-big.json --strategy TrendlineBreakoutLTF --timeframe 1d --timeframe-detail 15m --timerange 20200101- --max-open-trades 10 --enable-protections
```

It is slow: the documented run took about 18 hours while other jobs shared the CPU. Output from that run:
[results/ft_ltf.txt](results/ft_ltf.txt), and the full trade list in
`user_data/backtest_results/backtest-result-2026-09-10_11-53-23.zip`.

**3. Re-run the research validation** (lookahead replay, fill resolution,
account simulation):

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe research/rf_final.py 10
```

**4. See what is breaking out now:**

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe research/scan_trendline.py 45
```

The scanner prints the parent strategy's **daily** stop. For this strategy,
use the signal day's low minus one 1h ATR.

**5. Paper trade** (`config-big.json` has `dry_run: true`):

```bash
./.venv/Scripts/python.exe -m freqtrade trade --config config-big.json --strategy TrendlineBreakoutLTF
```

Set `max_open_trades` to 10 in the config first.

---

## Measured performance — full detail

### Freqtrade

Run: 2026-09-10, freqtrade 2026.8, `--timeframe-detail 15m`, 2,441 days, 0.1% fee
per side on every trade. 15m data starts 2020-10-01, so the 11 trades opened
before then (3,206 USDT, 2.4% of the profit) were filled on daily candles only.

**Summary**

| metric | value |
|---|---|
| CAGR | 49.04% |
| total profit | 1,342% (134,208 USDT on 10,000) |
| max drawdown, closed trades | 20.75% (24,704 USDT), 2025-11-04 → 2026-04-12, 159 days |
| profit factor | 2.80 |
| expectancy | 1.25 (ratio) |
| SQN | 2.86 |
| mean-profit p-value | 0.0047 |
| Sharpe / Sortino (closed trades) | 0.32 / 2.67 |
| market change (buy and hold the basket) | +265% |
| rejected entry signals | 2,129 |

**How trades end**

| exit | trades | average | total USDT | notes |
|---|---|---|---|---|
| stop loss | 131 | −7.0% | −69,851 | median −6.9%, middle half −9.4% to −5.1%, worst −16.5% |
| trailing stop | 66 | +50.0% | +168,201 | median +27.8%; 22 over +50%, 10 over +100%; 13 closed at a loss |
| time stop (365 days) | 1 | +301% | +7,244 | |
| still open at the end | 10 | +22.0% | +28,614 | unrealised — 21% of all profit |

Winners average **+61.1%** (median +29.6%). Losers average **−7.3%**. Each
average win is **8.4×** an average loss. That is how a 31% win rate makes money.

**Year by year** (by exit date, compounding)

| year | trades | win% | return | best trade |
|---|---|---|---|---|
| 2020 | 14 | 42.9 | +47.5% | +126% |
| 2021 | 6 | 66.7 | +42.6% | +185% |
| 2022 | 39 | 20.5 | **+0.6%** | +80% |
| 2023 | 33 | 24.2 | +44.2% | +137% |
| 2024 | 46 | 34.8 | **+269.0%** | +367% |
| 2025 | 23 | 13.0 | **+0.5%** | +47% |
| 2026 (to Sep 7) | 47 | 40.4 | +27.4% | +89% (10 still open) |

No losing year. But two years were flat, and 2024 alone made 61% of the USDT
profit.

**By coin**

- 67 coins traded. **34 made money, 33 lost money.**
- 9 coins never signalled (TAO, S, INJ, TIA, SUI, ARB, LDO, PENDLE, JUP). Most
  are recent listings without 200 days of falling history.
- The top 1 / 3 / 5 / 10 coins made **20% / 46% / 67% / 93%** of the profit.
- Best: XLM +269%, ALGO +189%, DYDX +162%, BNB +137%, CRV +135% (of starting
  capital).
- Worst: MASK −32%, LTC −26%, ZIL −23%, APT −21%, BTC −19%.
- Without the top 5 coins the backtest still makes 44,928 USDT (+449%).

**Position size** (stake as % of account value at entry)

- Median **12.6%**, 90th percentile 22.8%, maximum 37.7%.
- The daily-stop version: median 4.8%, maximum 11.5%.
- At the peak, **99%** of the account sat in open trades (daily version: 67%).

### Drawdown, measured two ways

Freqtrade's headline drawdown (20.75%) and the research engine's (21.1%) count
**closed trades only**. The account value moves every day while trades are open,
so both engines were re-measured with open positions valued at each daily close:

- **freqtrade:** the wallet file inside the result zip, summed over USDT and
  every coin held. Its last snapshot (2026-09-07) leaves out the 10 open coins,
  so it is dropped, together with 143 earlier days where the file lists fewer
  coins than trades were open.
- **research engine:** closed profit from `tl_account.simulate_honest`, plus
  each open position's value × (daily close ÷ entry − 1). It shares nothing
  with freqtrade.

| | closed trades only | **open trades valued daily** |
|---|---|---|
| TrendlineBreakoutLTF — freqtrade | 20.8% | **38.4%** |
| TrendlineBreakoutLTF — research | 21.1% | **34.1%** |
| TrendlineBreakout (parent) — freqtrade | 21.0% | 28.7% |
| daily-stop control — research | 16.5% | 23.4% |

Worst drops in account value (freqtrade, TrendlineBreakoutLTF):

| drop | high | low | back to the high |
|---|---|---|---|
| **38.4%** | 2024-03-10 | 2024-09-18 | 2024-11-23 |
| 33.9% | 2025-10-09 | 2026-04-13 | 2026-05-09 |
| 25.7% | 2023-02-21 | 2023-10-13 | 2023-10-31 |
| 24.8% | 2022-04-04 | 2022-10-23 | 2023-01-15 |
| 16.9% | 2024-01-02 | 2024-01-24 | 2024-02-29 |

The account spent 335 of 2,297 days (15%) more than 20% below its high, and 94
days more than 30% below.

Calendar-year change in account value (freqtrade, open trades valued):

| 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 to Sep 6 |
|---|---|---|---|---|---|---|
| +76.5% | +19.1% | +1.3% | +153.4% | +108.6% | +3.1% | +24.4% |

These differ from the exit-date table above because a trade's gain counts as it
happens, not on the day it closes.

### Research engine

[rf_final.py](rf_final.py), 15m fills, exactly 1% risk per trade, max 10 open,
profit credited when a trade closes. Total position value is capped at 100% of
the account, as on spot — a trade that does not fit is made smaller, or skipped
if less than a quarter of it fits. Output: [results/rf_final.md](results/rf_final.md).

| coins | fills | win% | CAGR | PF | max drawdown | peak invested |
|---|---|---|---|---|---|---|
| fit basket | 107 | 32.7 | 33.7% | 4.18 | 15.8% | 101% |
| **held-out basket** | 108 | 33.3 | **34.6%** | 4.32 | 17.3% | 102% |
| **all 76 coins** | 174 | 29.9 | **48.3%** | 3.81 | 21.1% | 103% |
| all 76, **no** capital cap | 192 | 30.7 | 62.4% | 4.24 | 23.1% | 178% |

The daily-stop control in the same engine: 21.4% CAGR at 16.5% drawdown.

The held-out basket is the fairer number: those coins never influenced a single
choice. It earns 34.6% alone. The whole universe earns more because it has more
signals to fill the 10 slots.

Year by year (all 76, capped, by **entry** year): 2020 +49%, 2021 −1%, 2022
+7%, 2023 +117%, 2024 +130%, 2025 −0.4%, 2026 +29%. The split differs from
freqtrade's table because this one groups by entry date, and because freqtrade
shrinks stakes when cash runs short.

**Pooled R, held-out coins, 15m fills** (every signal, no slot limit, drawdown in
date order):

| | trades | win% | avg R | PF | maxDD_R | annual R / maxDD R |
|---|---|---|---|---|---|---|
| daily stop, 25% trail | 127 | 48.0 | +1.11 | 4.17 | 13.1 | 1.61 |
| **1h stop, 25% trail** | 126 | 36.5 | **+2.07** | 4.35 | 18.6 | **2.10** |

---

## Across coins and baskets

**Question:** does it only work on this universe, or only thanks to a few coins?
[baskets.py](baskets.py) runs the same strategy on many baskets, in the same
engine as the research numbers above: 15m fills, 10 slots, 1% risk, positions
capped at 100% of the account. Every basket uses the same 6.68-year span, with
open trades valued at the end, so baskets are comparable. On that basis the
whole universe reads **41.8% CAGR** (rf_final.py's 48.3% measures only from the
first entry to the last exit). "Real drawdown" below values open trades every
day.

### The short answer

- **Any big enough basket makes money.** 300 random 20-coin baskets: all 300
  profitable, median 17.5% CAGR. 300 random 38-coin baskets: all 300
  profitable, median 31.2%.
- **More coins means more return.** Ten slots sit idle unless enough coins
  signal. Median CAGR: 10 coins 8.4%, 20 coins 17.5%, 38 coins 31.2%, all 76
  coins 41.8%.
- **It survives losing its best coins.** Without the top 5 coins: 30.9% CAGR.
  Without the top 10: 22.1%. Without the top 15: 13.9%. None of them has a
  losing calendar year.
- **Weak spots:** majors (13.5% CAGR), gaming / NFT / social (0.9%), and coins
  listed on Binance in 2022 or later (3.6%).

### Reference

| basket | coins | trades filled | win% | avg R | PF | **CAGR** | drawdown, closed | **drawdown, real** | losing years |
|---|---|---|---|---|---|---|---|---|---|
| all coins | 76 | 174 | 29.9 | +1.95 | 3.96 | **41.8%** | 21.0% | **34.1%** | 0 of 7 |
| fit half (hash split) | 40 | 107 | 32.7 | +1.82 | 3.62 | 29.0% | 15.8% | 21.9% | 1 of 7 |
| held-out half (hash split) | 36 | 108 | 33.3 | +2.07 | 4.35 | 29.8% | 17.3% | 27.9% | 1 of 7 |

The two halves never share a coin, and they earn almost the same: 29.0% and
29.8%.

### Random baskets (300 per size, seed 7)

| coins per basket | CAGR 5th pct | median | 95th pct | real drawdown, median | baskets profitable | baskets with CAGR > drawdown |
|---|---|---|---|---|---|---|
| 10 | 2.4% | 8.4% | 17.7% | 15.1% | 99% | 14% |
| 20 | 8.5% | 17.5% | 27.1% | 18.9% | **100%** | 40% |
| 38 | 20.0% | 31.2% | 39.4% | 23.9% | **100%** | 81% |

### Take away the coins that carried it

Ranked by total R in this engine. This uses hindsight on purpose, to see what is
left.

| basket | trades filled | avg R | PF | **CAGR** | **real drawdown** | losing years |
|---|---|---|---|---|---|---|
| all coins | 174 | +1.95 | 3.96 | 41.8% | 34.1% | 0 of 7 |
| without top 3 (XLM ALGO ROSE) | 167 | +1.53 | 3.30 | 30.2% | 34.0% | 0 of 7 |
| without top 5 (+ MINA SKL) | 167 | +1.36 | 3.03 | 30.9% | 33.0% | 0 of 7 |
| without top 10 (+ STX ETH FET TRX BAND) | 159 | +0.98 | 2.41 | 22.1% | 30.2% | 0 of 7 |
| without top 15 (+ DOGE DYDX OP NEO BTC) | 146 | +0.69 | 1.99 | 13.9% | 30.0% | 0 of 7 |

Removing the winners lowers the return steadily, but it never turns it
negative. The drawdown barely moves, because the losing trades are spread
across every coin.

### Sectors

Small baskets have fewer signals than slots, so idle cash holds their CAGR
down. Compare avg R and PF across sizes. Compare CAGR only between baskets of
similar size.

| sector | coins | trades filled | win% | avg R | PF | CAGR | real drawdown |
|---|---|---|---|---|---|---|---|
| majors | 13 | 66 | 27.3 | +1.43 | 2.98 | 13.5% | 27.7% |
| other layer-1s | 25 | 75 | 36.0 | +2.24 | 4.36 | 25.4% | 16.3% |
| layer-2 / scaling | 5 | 11 | 54.5 | +6.50 | 15.05 | 9.8% | 10.9% |
| DeFi | 13 | 27 | 59.3 | +2.54 | 7.12 | 10.1% | 16.8% |
| AI / data / infra | 12 | 29 | 31.0 | +1.68 | 3.53 | 6.5% | 16.5% |
| gaming / NFT / social | 8 | 29 | 24.1 | +0.27 | 1.35 | 0.9% | 19.4% |
| everything except majors | 63 | 136 | 30.9 | +2.14 | 4.38 | 38.0% | 27.1% |

### Liquidity and listing age

| basket | coins | trades filled | avg R | PF | CAGR | real drawdown |
|---|---|---|---|---|---|---|
| most liquid third (by volume since 2024) | 25 | 82 | +1.48 | 3.16 | 18.5% | 30.6% |
| middle third | 25 | 53 | +3.42 | 7.54 | 26.4% | 17.0% |
| least liquid third | 26 | 93 | +1.48 | 3.05 | 16.8% | 29.5% |
| listed before 2020 | 28 | 116 | +2.14 | 4.04 | 34.9% | 28.0% |
| listed 2020-2021 | 31 | 90 | +1.89 | 4.08 | 22.8% | 19.0% |
| listed 2022 or later | 17 | 23 | +1.20 | 2.96 | 3.6% | 18.7% |

New listings rarely have 200 days of falling history, so they rarely signal.

### Every coin

72 of 76 coins traded; TAO, INJ, TIA and LDO never did. 45 coins have a
positive total R and 27 a negative one. The full per-coin table is in
`results/baskets.md`.

### Read these with care

- **The sector, liquidity and listing-age splits were made after seeing the
  data.** The liquidity ranking even uses volume from 2024 onward to sort
  trades from 2020. These tables show where the profit came from. They are not
  a filter to trade. Picking "layer-1s only" from them would repeat the
  single-coin overfitting this repo has already been burned by.
- **Trust the random baskets and the fit and held-out halves.** They choose
  coins without looking at the results, and they agree: the strategy works on
  any large basket, and a bigger basket does better.

---

## Evidence it is real

| check | result |
|---|---|
| **two engines agree** | CAGR 49.0% vs 48.3%; closed-trade drawdown 20.8% vs 21.1%; drawdown with open trades valued 38.4% vs 34.1% |
| **no lookahead** | 98 signals replayed with every later 1h bar deleted: 0 changed, in all four entry modes |
| **the freqtrade stop equals the research stop** | 169 signals, 0 mismatches |
| **the daily detector matches** | 331 signals, 0 mismatches (parent strategy) |
| **held-out coins** | the held-out basket earns 34.6% alone |
| **fill resolution** | same trades walked on 1h / 15m / 5m: avg R +0.437 / +0.475 / +0.425 |
| **not a lucky basket** | all 600 random 20- and 38-coin baskets profitable; the fit and held-out halves earn 29.0% and 29.8%; without its top 5 coins it still earns 30.9% |
| **not a lucky setting** | 599 of 600 grid cells positive on held-out coins; the chosen cell scores 2.54 held out and its ATR neighbours 2.46 and 2.35 ([RESULTS_refined_entries.md](RESULTS_refined_entries.md)) |

**Bugs caught on the way, all fixed before the numbers above:**

- The risk filter read the **next** bar's open, which is not known when the
  decision is made. The lookahead replay caught it.
- A guard required the entry bar to exist in the data. That was harmless when
  trading, but it broke the replay.
- Tightening the stop silently made positions bigger than the account. The
  capital cap now stops that; without it the result reads 62%, not 48%.
- The old account simulator ([portfolio.py](portfolio.py)) counted profit on
  entry, not exit. [tl_account.py](tl_account.py) replaces it.

---

## Known weaknesses

In order of how much they should worry you.

**1. A few trades carry everything.** The best 5 trades made 68% of the profit.
The top 10 coins made 93%. Half the coins that traded lost money. Miss one
XLM-style trade — a full account, a late fill, a skipped signal — and the
result changes a lot.

**2. It needs a crash first.** 2022 (+0.6%) and 2025 (+0.5%) were flat. A
falling trendline only exists after a fall, and the break only pays if a real
rally follows. In a slow grind down, it takes loss after loss.

**3. The most recent evidence is the weakest.** From 2025-04 onward, on the 40
coins with 5m data, there are only 67 trades. The fit basket is slightly
negative there (−0.01 R per trade). The held-out basket is +0.48 R per trade (15m fills).

**4. The real drawdown is about 38%, not 21%.** The 21% counts closed trades
only. A trade can rise 100% and give back 25% of its high before it exits, and
ten trades can do that at the same time. Valuing open trades every day, the
account fell **38.4%** from 2024-03-10 to 2024-09-18 and did not recover until
2024-11-23. The research engine, measured separately, finds 34.1%. See
[Drawdown, measured two ways](#drawdown-measured-two-ways). **Plan for a 40%
drop, not 21%.**

**5. Freqtrade's "balance" drawdown reads 99.2%. Ignore it.** The last wallet
snapshot (2026-09-07) lists only the 1,156 USDT of free cash and leaves out the
10 open coins, so the account looks almost empty on the final day. With that
day dropped, the account is worth 144,466 USDT.

**6. 21% of the profit is not banked.** Ten trades were still open when the
backtest ended. With those left out, CAGR is 44.2%.

**7. Big positions in thin markets.** A median stake of 12.6% (maximum 37.7%)
in a mid-cap coin on a breakout day will slip more than the 0.05% assumed. This
is the most likely place live results fall short.

**8. It is hard to sit through.** 7 trades in 10 lose. The worst run was 24
losses in a row. 131 trades hit the stop.

**9. Inherited from the parent.** The signals are correlated (coins break out
together). The coin list is survivors: coins delisted since 2020 are missing.
6.7 years is only about two market cycles.

---

## What is NOT part of this strategy, and why

| idea | result |
|---|---|
| wait for a 1h close above the breakout candle's high | worse than buying the next open |
| wait for price to retest the broken line | worse, and it misses a third of the trades |
| wait for a 1h EMA pullback | worse |
| use the broken trendline as the stop | no better than the daily stop |
| an R-based trail (3R, 6R, 9R) | it shrinks with the tighter stop and cancels the gain |
| a tight 15% trail | too tight; the move needs room |
| shorts | every short mirror in this repo lost money held out |

---

## Next steps

1. **Test coins outside the 76.** Inside the 76 this is done; see
   [Across coins and baskets](#across-coins-and-baskets). Every random 20-coin
   basket made money, and the result survives losing its best coins. Coins
   never seen at all are the stronger test. A bigger universe should also raise
   the return, because more signals fill idle slots. This needs more coin data
   downloaded.
2. **Cut the 38% drawdown without killing the return** — test fewer slots,
   0.5% risk, and a tighter trail after a large gain. (Measuring it is done.)
3. **Stress the costs** — rerun at 0.3% and 0.5% slippage per side.
4. **Paper trade** for at least a few months before real money.

---

## File map

| file | what it is |
|---|---|
| `user_data/strategies/TrendlineBreakoutLTF.py` | the freqtrade strategy |
| `user_data/strategies/TrendlineBreakout.py` | parent: the daily signal and sizing |
| `research/trendline.py` | the daily trendline detector (research version) |
| `research/refine.py` | 1h entry timing and 1h stop placement |
| `research/harness.py` | the R-multiple backtest engine (`trail_pct` added for this strategy) |
| `research/tl_account.py` | account simulator: profit on exit, capital cap |
| `research/rf_grid.py`, `rf_report.py` | the 600-permutation study |
| `research/rf_final.py` | lookahead replay, fill check, account simulation |
| `research/scan_trendline.py` | live scan of current breaks and near-breaks |
| `research/baskets.py` | the strategy on sectors, liquidity, listing age, random baskets and every coin |
| `research/results/ft_ltf.txt` | freqtrade output for this strategy |
| `research/results/ft_daily15m.txt` | freqtrade output for the parent, same settings |
| `research/results/rf_final.md` | research validation output |
| `research/results/rf_grid_report.md` | grid ranking and marginals |
| `research/results/baskets.md` | full basket output, including the per-coin table |

`research/results/` and `user_data/backtest_results/` are gitignored, so those
raw files exist only on the machine that ran them. Every number quoted in this
document is written out above, and the commands under
[How to run it](#how-to-run-it) regenerate the files.
