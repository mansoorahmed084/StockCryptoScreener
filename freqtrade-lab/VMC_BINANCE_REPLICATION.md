# VMC Daily Capitulation Divergence — Binance replication

**Date:** 2026-09-05
**Question:** does the repo's headline strategy still work on true Binance
candles, run through an engine that is not ours?

The original result in [STRATEGY_RESEARCH.md](../STRATEGY_RESEARCH.md) came from
CoinDCX candles through `backend/research/engine.py`. Both the data source and
the backtest engine were ours. This run changes both: real Binance spot candles,
executed by Freqtrade.

## Method

Strategy code: [user_data/strategies/VmcCapitulation.py](user_data/strategies/VmcCapitulation.py).

It **imports the repo's own indicator code** rather than reimplementing it:

- `backend.indicators.vumanchu.VuManChuCipherB` — WaveTrend, money flow, pivots,
  regular divergences
- `backend.screener.rs.classify_history` — the noise-filtered BTC regime gate
- `backend.config.load_config` — classifier params read from `config.yaml`

So the signal maths is identical to the screener's. Only the execution engine
and the data source differ.

Rules are the D2 spec verbatim: bull divergence, WT2 ≤ −45 at the pivot, pivot
confirmed 3 daily closes later, BTC daily regime not bear, stop at pivot low
− 0.5 × ATR(14), skip if that stop is further than 10% away, enter at the next
daily open, 1% equity risk, 40-bar time stop.

| Setting | Value |
|---|---|
| Universe | 29 Binance USDT spot pairs (majors, 2021-era listings) |
| Period | 2021-01-01 → 2026-09-03 |
| Candles | daily signals, **1h detail candles for intracandle fills** |
| Costs | 0.1% per side; re-run at 0.15% to include slippage |
| Sizing | 1% of equity risked per trade, 10,000 USDT start |

## Results

| Variant | Trades | Win % | Profit | Max DD | Avg hold |
|---|---|---|---|---|---|
| D2 — 1.5R target | 65 | **60.0%** | +41.4% | 9.7% | 7.1 d |
| D6 — 1.0R target | 65 | **66.2%** | +25.9% | 8.3% | 4.4 d |

At 0.15% per side (matching the research's fee + slippage) the win rates do not
move at all: 60.0% and 66.2%. Costs are not what decides this strategy.

Exit breakdown for the 1.0R variant — the mechanism is clean, nothing is
drifting out to the time stop:

| Exit | Trades | Win % | Avg profit |
|---|---|---|---|
| target_1.0R | 43 | 100% | +6.99% |
| stop_loss | 22 | 0% | −5.72% |
| time_stop | 0 | — | — |

## Against the original numbers

| Metric | CoinDCX research | Binance replication | Verdict |
|---|---|---|---|
| Trades/year | ~11 | ~11 (65 over 5.7y) | matches |
| Avg hold | ~7.5 d | 7.1 d | matches |
| Max drawdown | 9.1% | 9.7% | matches |
| Win % (1.5R) | 67.9% | 60.0% | **7.9 pts lower** |
| Win % (1.0R, IS) | 73.9% | 63.2% | **10.7 pts lower** |
| Win % (1.0R, OOS) | 81.8% (n=11) | 87.5% (n=8) | matches, tiny n |

Trade frequency, hold time and drawdown reproduce closely. That says the entry
logic ported faithfully. The win rate is the one number that moved, and it moved
down.

**This is not a failed replication.** STRATEGY_RESEARCH.md already stated the
95% confidence interval on the win rate as roughly 56–80% at n=56. 60% sits
inside that band, near the bottom. The honest reading is that the true rate is
likely in the low-to-mid 60s, and the 67.9% headline was the lucky end of the
range rather than the centre.

Both windows stayed positive, which is the part that matters:

| Window | 1.5R | 1.0R |
|---|---|---|
| In-sample (2021-01 → 2026-01) | 61.4%, +37.3% | 63.2%, +18.3% |
| Out-of-sample (2026-01 → 2026-09) | 50.0%, +3.0% | 87.5%, +6.4% |

Out-of-sample is 8 trades. Read nothing into it either way.

## Checks run

- `freqtrade lookahead-analysis` → **no bias detected** across 20 sampled trades.
  The 3-candle pivot confirmation delay holds up under an independent audit.
- Daily-only fills (no 1h detail) scored 54.0% / 56.2%. The 6–10 point gap is
  purely the fill model: without intraday candles a target touched inside the
  day is missed and the trade runs on to the stop. Any daily-candle backtest of
  an intraday-target strategy is pessimistic by roughly this much.

## Where this run differs from the original

Worth knowing before comparing the two line by line.

1. **Universe.** 29 Binance pairs here vs ~25 CoinDCX majors there. Not the same
   basket, and both carry survivorship bias — the coins were picked from today's
   listings.
2. **Fills.** Freqtrade checks exits at each 1h candle open. The research engine
   used daily conservative fills. Neither models a real limit book.
3. **Returns.** Freqtrade simulates a wallet; the research reported R-multiples.
   The percentage columns are not directly comparable. Win rate and drawdown are.
4. **The 10% risk cap** is measured against the confirmation-bar close, not the
   next open, because the next open is not knowable at signal time.

## Reproduce

```bash
cd freqtrade-lab
.venv/Scripts/freqtrade.exe download-data --config config-vmc.json --timeframes 1d 1h --timerange 20201001-
.venv/Scripts/freqtrade.exe backtesting --config config-vmc.json --strategy-list VmcCapitulation VmcCapitulation1R --timeframe 1d --timeframe-detail 1h --timerange 20210101-20260904 --cache none --fee 0.0015
.venv/Scripts/freqtrade.exe lookahead-analysis --config config-vmc.json --strategy VmcCapitulation --timeframe 1d --timerange 20220101-20260904
```

`config-vmc.json` is gitignored (it is a copy of `config.json` with the 29-pair
whitelist). Build it from `config.example.json` and swap in the whitelist listed
at the top of this file.

## Not tested here

The **4h Blow-off Fade** from [SHORT_TERM_STRATEGY.md](../SHORT_TERM_STRATEGY.md)
is short-only. This config is Binance **spot**, which cannot short. Testing it
needs `trading_mode: futures` and funding-rate data.
