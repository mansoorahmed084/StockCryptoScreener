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
_Updated 30 Oct 2026 07:48 IST._

- Calls logged: 6 (1 on time, 5 late). Open now: 6.
- **Closed, on time:** none yet
- Closed, all: none yet
<!-- /AUTO:SUMMARY -->

## Open trades

<!-- AUTO:OPEN -->
| # | coin | side | entered | entry | stop | 6R target | exit if a 4h candle closes | now | now R | late | CoinDCX | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | BTC | short | 30 Oct 05:30 | 77962.6 | 82485.4 | 50825.6 | next run | 77006.2 | +0.21 | no | yes |  |
| 2 | ADA | short | 29 Oct 09:30 | 0.1973 | 0.212882 | 0.103808 | above 0.2106 | 0.1883 | +0.58 | yes | yes |  |
| 3 | AVAX | short | 29 Oct 09:30 | 8.591 | 9.26298 | 4.55911 | above 9.169 | 8.25 | +0.51 | yes | yes |  |
| 4 | HBAR | short | 22 Oct 13:30 | 0.0814 | 0.087434 | 0.045196 | above 0.07727 | 0.06903 | +2.05 | yes | yes |  |
| 5 | ICP | short | 29 Oct 09:30 | 2.547 | 2.71772 | 1.52269 | above 2.687 | 2.377 | +1.00 | yes | yes |  |
| 6 | AXS | short | 29 Oct 09:30 | 0.9231 | 0.988857 | 0.528556 | above 0.9789 | 0.8317 | +1.39 | yes | yes |  |
<!-- /AUTO:OPEN -->

## Closed trades

<!-- AUTO:CLOSED -->
_none_
<!-- /AUTO:CLOSED -->

## Last scan

<!-- AUTO:SCAN -->
```
SMC Sweep-Break scan 2026-10-30 02:18 UTC, 170 coins. Last closed 4h candle: 2026-10-29 20:00 UTC (closed 00:00 UTC). Next scan after 04:00 UTC.

NEW  - signal on the candle that just closed; enter at this candle's open: 1
coin  side entry (4h open)    stop stop % 6R target     now now R CoinDCX vol $M
 BTC SHORT         77962.6 82485.4    5.8   50825.6 77006.2 +0.21     yes  23396

OPEN - trades the strategy holds now: 5
coin  side     entered days  entry     stop 6R target exit on 4h close     now now R CoinDCX
 ADA SHORT 10-29 04:00  0.9 0.1973 0.212882  0.103808     above 0.2106  0.1883 +0.58     yes
AVAX SHORT 10-29 04:00  0.9  8.591  9.26298   4.55911      above 9.169    8.25 +0.51     yes
HBAR SHORT 10-22 08:00  7.8 0.0814 0.087434  0.045196    above 0.07727 0.06903 +2.05     yes
 ICP SHORT 10-29 04:00  0.9  2.547  2.71772   1.52269      above 2.687   2.377 +1.00     yes
 AXS SHORT 10-29 04:00  0.9 0.9231 0.988857  0.528556     above 0.9789  0.8317 +1.39     yes

CLOSED - ended on the last closed candle: 0

Rules: risk 0.5-1% of equity per trade, at most 10 open. Size = risk / stop %. Backtest, not advice.
```
<!-- /AUTO:SCAN -->
