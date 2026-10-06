# Scalp journal

Paper trades of the exhaustion scalp scanner ([SCALP.md](../SCALP.md)). Every
call is replayed the same way and scored in **R**: 1R is the distance from
entry to the stop. A stop hit is −1R. Reaching T1 and then T2 is usually
between +1R and +2R. **Not financial advice. No real money.**

- The calls are in [scalps.csv](scalps.csv). This command adds a scan's calls:
  `.venv/Scripts/python.exe -m backend.cli scalp --top 300 --journal`.
  The same coin and side is skipped if it was called in the last 4 hours.
- This command replays every call and refreshes the tables below:
  `.venv/Scripts/python.exe -m backend.cli scalp-journal`.
  The notes are written by hand, and a refresh never changes them.

## Rules

- **Entry:** a "triggered" call enters at the price when the scan ran. An
  "armed" call enters on the first candle of its timeframe that closes through
  the trigger, within 4 candles. Otherwise it **expires**. If price reaches the
  stop before the trigger, the call is **invalid**.
- **Stop before T1:** −1R.
- **At T1:** half the position is closed and the stop moves to break-even. The
  rest rides to T2 (or back to break-even) for at most 16 more candles, then
  closes at market.
- **Time stop:** if neither T1 nor the stop is reached within 8 candles, the
  trade closes at that candle's close.
- **Both in one candle:** if a candle touches both the stop and a target, it
  counts as the stop.
- **Exit checks** use 1-minute candles (coarser for calls older than a day).
  Fees are not included.

## Scoreboard

<!-- AUTO:SUMMARY -->
<!-- /AUTO:SUMMARY -->

## What works and what doesn't

_No calls yet._ Questions to answer once there are enough trades:

- Does a higher score win more often?
- Do short scalps after pumps work better than long scalps after dumps?
- Is 5m better than 15m?
- Do "triggered" calls beat "armed" ones?
- Does funding against the trade (squeeze risk) really cost us?
- How often does T1 come before the stop?

## Daily notes

## Calls

<!-- AUTO:TRADES -->
<!-- /AUTO:TRADES -->
