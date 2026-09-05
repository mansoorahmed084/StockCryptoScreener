# Backtest comparison — 2026-09-05

Data: Binance spot, 5 pairs (BTC, ETH, SOL, BNB, XRP), 180 days (2026-03-08 to 2026-09-05).
Start money: 1000 USDT. Max 3 open trades. 100 USDT per trade. Fees included.

## The 3 strategies

| Name | Style | Rule |
|---|---|---|
| `EmaCross` | trend follow | Buy when EMA20 crosses over EMA50 and price is above EMA200. Trailing stop. |
| `RsiDip` | mean reversion | Buy when RSI drops under 30 while above EMA200. Sell on RSI over 70 or small ROI. |
| `BbandsBreakout` | breakout | Buy when price breaks the upper Bollinger band on high volume. Sell at the middle band. |

## Full 180 days, 1h candles

| Strategy | Trades | Profit % | Win % | Max drawdown |
|---|---|---|---|---|
| EmaCross | 88 | **-5.47%** | 26.1% | 5.47% |
| RsiDip | 14 | **-0.16%** | 35.7% | 0.39% |
| BbandsBreakout | 309 | **+1.65%** | 41.4% | 4.82% |

## Same strategies, split in half

| Strategy | Half 1 (Mar–Jun) | Half 2 (Jun–Sep) | Swing |
|---|---|---|---|
| EmaCross | -2.85% | -2.62% | small |
| RsiDip | -0.26% | +0.11% | flips sign |
| BbandsBreakout | **-1.59%** | **+3.23%** | **flips sign, 4.8 points** |

BbandsBreakout is the "winner" over 180 days only because of the second half.
Over the first half it lost money. The edge is not stable.

## The demo strategy trap

`SampleStrategy` over 30 days looked great. Over 180 days it does not.

| Window | Trades | Profit % | Win % |
|---|---|---|---|
| 30 days (Aug) | 34 | +1.54% | 91.2% |
| 180 days | 198 | **-4.23%** | 86.4% |

It wins 86% of its trades and still loses money. The 27 losing trades are much
bigger than the 171 winning ones.

## What this teaches

1. A short backtest window proves nothing. Always test 6+ months.
2. A high win rate does not mean profit. Look at total profit and drawdown.
3. Split your test in half. If the two halves disagree, you have noise, not an edge.
4. Few trades means a weak result. RsiDip made only 14 trades in 6 months.

## Repeat any of these

```bash
.venv/Scripts/freqtrade.exe backtesting --config config.json --strategy-list EmaCross RsiDip BbandsBreakout --timeframe 1h --timerange 20260308-20260905 --cache none
```
