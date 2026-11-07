# SMC Sweep-Break — paper trades

Every call the live scan makes, logged automatically every 4 hours by
`freqtrade-lab/research/scan_smc.py --log`. Rules and backtest:
[STRATEGY_SMC_SweepBreak.md](../freqtrade-lab/research/STRATEGY_SMC_SweepBreak.md).
Times are IST. Entry = the backtest's fill (the 4h open after the signal);
"seen" = the price when the scan ran. "Late" = logged after its entry candle
had closed (a missed run, or open before logging began); late trades are
kept out of the on-time numbers.

Backtest expectation, for comparison: about 38% wins, +0.25R a trade, and
losing streaks of 10+ are normal. Judge it after 30+ closed on-time trades.

## Notes

_Hand-written notes go here. The scan never changes this section._

<!-- AUTO:SUMMARY -->
_Updated 07 Nov 2026 23:09 IST._

- Calls logged: 15 (4 on time, 11 late). Open now: 5.
- **Closed, on time:** 4 trades, win 0%, avg -0.82R, total -3.3R (= -1.6% of an account at 0.5% risk)
- Closed, all: 10 trades, win 20%, avg -0.10R, total -1.0R (= -0.5% of an account at 0.5% risk)
- On time, longs: 1 trades, win 0%, avg -0.94R, total -0.9R (= -0.5% of an account at 0.5% risk)
- On time, shorts: 3 trades, win 0%, avg -0.78R, total -2.4R (= -1.2% of an account at 0.5% risk)
- Price had moved -0.14R on average by the time the scan ran (+ = in the trade's favour).
<!-- /AUTO:SUMMARY -->

## Open trades

<!-- AUTO:OPEN -->
| # | coin | side | entered | entry | stop | 6R target | exit if a 4h candle closes | now | now R | late | CoinDCX | CoinDCX dry run | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 | AVAX | short | 29 Oct 09:30 | 8.591 | 9.26298 | 4.55911 | above 8.472 | 8.202 | +0.58 | yes | yes |  |  |
| 4 | HBAR | short | 22 Oct 13:30 | 0.0814 | 0.087434 | 0.045196 | above 0.06919 | 0.06728 | +2.34 | yes | yes |  |  |
| 7 | RE | short | 12 Oct 21:30 | 0.4304 | 0.457171 | 0.269776 | above 0.3257 | 0.294 | +5.09 | yes | yes |  |  |
| 9 | IMX | short | 29 Oct 09:30 | 0.1348 | 0.144885 | 0.0742912 | above 0.123 | 0.1194 | +1.53 | yes | yes |  |  |
| 14 | ENSO | short | 29 Oct 09:30 | 0.6155 | 0.658096 | 0.359922 | above 0.4952 | 0.4659 | +3.51 | yes | yes |  |  |
<!-- /AUTO:OPEN -->

## Closed trades

<!-- AUTO:CLOSED -->
| # | coin | side | entered | exited | entry | exit | why | R | late |
|---|---|---|---|---|---|---|---|---|---|
| 15 | FIL | short | 04 Nov 09:30 | 04 Nov 17:30 | 0.8372 | 0.898503 | stop | -1.02 | no |
| 13 | JST | short | 31 Oct 01:30 | 06 Nov 21:30 | 0.13568 | 0.1432 | 4h CHoCH | -0.80 | no |
| 12 | ENJ | short | 29 Oct 13:30 | 04 Nov 17:30 | 0.02471 | 0.02491 | 4h CHoCH | -0.15 | yes |
| 11 | SUN | long | 30 Oct 05:30 | 31 Oct 05:30 | 0.017146 | 0.01598 | 4h CHoCH | -0.94 | no |
| 10 | LUNC | short | 07 Oct 09:30 | 04 Nov 05:30 | 0.05076 | 0.0402 | 28 days | +3.25 | yes |
| 8 | G | short | 25 Oct 17:30 | 01 Nov 05:30 | 0.003666 | 0.00395537 | stop | -1.02 | yes |
| 6 | AXS | short | 29 Oct 09:30 | 05 Nov 05:30 | 0.9231 | 0.884 | 4h CHoCH | +0.58 | yes |
| 5 | ICP | short | 29 Oct 09:30 | 04 Nov 17:30 | 2.547 | 2.598 | 4h CHoCH | -0.32 | yes |
| 2 | ADA | short | 29 Oct 09:30 | 04 Nov 17:30 | 0.1973 | 0.1979 | 4h CHoCH | -0.05 | yes |
| 1 | BTC | short | 30 Oct 05:30 | 04 Nov 17:30 | 77962.6 | 80274.3 | 4h CHoCH | -0.53 | no |
<!-- /AUTO:CLOSED -->

## Last scan

<!-- AUTO:SCAN -->
```
SMC Sweep-Break scan 2026-11-07 12:05 UTC, 147 coins. Last closed 4h candle: 2026-11-07 08:00 UTC (closed 12:00 UTC). Next scan after 16:00 UTC.

NEW  - signal on the candle that just closed; enter at this candle's open: 0

OPEN - trades the strategy holds now: 2
coin  side     entered days  entry     stop 6R target exit on 4h close     now now R CoinDCX
AVAX SHORT 10-29 04:00  9.3  8.591  9.26298   4.55911      above 8.472   8.257 +0.50     yes
HBAR SHORT 10-22 08:00 16.2 0.0814 0.087434  0.045196    above 0.06919 0.06791 +2.24     yes

CLOSED - ended on the last closed candle: 0

Rules: risk 0.5-1% of equity per trade, at most 10 open. Size = risk / stop %. Backtest, not advice.

WATCH - setups the forming 4h candle would trigger (it closes 16:00 UTC, in 234 min). Daily trend and sweep are already in place; only the close is missing. Entry = next 4h open, so the stop % and target move with it: 0
```
<!-- /AUTO:SCAN -->
