# Exhaustion scalps

A separate scanner for quick counter-moves. It looks for coins that moved a lot
(up or down), whose trend is getting weaker, while the price has not turned
yet. It scores each one on several indicators, so only setups where many of
them agree come out.

**Not financial advice.** Counter-trend scalps are the riskiest kind of trade:
strong trends can run much further than any indicator expects. Use small size,
a hard stop, and quick exits.

## Run it

```bash
.venv/Scripts/python.exe -m backend.cli scalp                  # top 100, 15m candles
.venv/Scripts/python.exe -m backend.cli scalp --top 300        # include the smaller movers
.venv/Scripts/python.exe -m backend.cli scalp --tf 5m          # faster scalps
.venv/Scripts/python.exe -m backend.cli scalp --min-score 4    # stricter
```

The code is in `backend/screener/scalp.py`, and the tests are in `tests/test_scalp.py`.

## What it looks for

Below is the setup after an **up-move**, which gives a **short scalp**. A
down-move is the exact mirror and gives a **long scalp**.

### 1. The coin moved a lot

Over the last 24 hours of candles, the coin passes if either of these is true:

- **Big move:** it moved at least **8%** (`--min-move`).
- **Stretched:** it sits **3 ATRs** or more from its 24h VWAP. ATR is the average
  size of one candle. VWAP is the average price paid, weighted by volume.

Coins with less than **$5M** of 24h volume are skipped, because their order books are too thin.

### 2. Price hasn't followed yet

The last close must still be within **1.5 ATR** of the move's high. If price has
already dropped far from the high, the scalp is gone, and the coin is skipped.

### 3. The trend is weakening: confluence score

The scanner compares the last 2 highs of the move. The second high can be the
newest closed candle. That way the setup is caught while the push is still
going, not after.

Each check that agrees adds 1 point:

| Check | Meaning (for a short after an up-move) |
|---|---|
| `rsi_div` | Price made a higher high, but RSI made a lower high (bearish divergence). |
| `wt_div` | The same on WaveTrend (VuManChu Cipher B's wave). The first high must be overbought (53 or more). |
| `macd_div` | The same on the MACD histogram: the push has less force. |
| `vol_fade` | The second push traded less volume than the first. |
| `cvd_fade` | Cumulative taker buys minus sells (CVD) did not make a new high. Buyers are not confirming. |
| `rsi_ext` | RSI was overbought (70 or more) at the first high. |
| `htf_ext` | The 1h RSI is overbought too. |
| `crowded` | Funding is 0.02% or more, so longs are paying and crowded. If funding is negative instead (shorts crowded, squeeze risk), the coin **loses** a point. |

A setup needs **3 points or more** (`--min-score`) to show.

### 4. The trade plan

| | Short scalp (after an up-move) | Long scalp (after a down-move) |
|---|---|---|
| **Trigger** | A candle closes below the low of the 3 candles before it. | A candle closes above the high of the 3 candles before it. |
| **Stop** | A quarter ATR above the move's high. | A quarter ATR below the move's low. |
| **T1** | EMA 20 | EMA 20 |
| **T2** | 38.2% retracement of the move | 38.2% retracement of the move |
| **T3** | The 24h VWAP | The 24h VWAP |

- **armed** means waiting for the trigger. **triggered** means the last closed candle just broke it.
- Setups are kept only if the reward to T2 is at least **1.5 times** the risk.
- The output also shows funding and the 24h change in open interest. Rising open
  interest into a fading move means more late traders who may have to exit.

## How to trade it

1. **Wait for the trigger.** Do not short a pump while it is still printing new highs.
   The divergence says the trend is weak. The trigger says it has started to turn.
2. **Use small size.** These trades go against the trend.
3. **Use the stop, every time.** If price makes a new high above the stop, the
   setup was wrong.
4. **Take part of the profit at T1, then move the stop to break-even.** T1 is usually
   close, about 0.4–0.7R. Let the rest run to T2.
5. **Check BTC first.** Skip short scalps when BTC is breaking out hard, and skip
   long scalps when BTC is breaking down.
6. **Mind the time.** On 15m candles, a scalp that has not reached T1 within about
   2 hours is losing its reason to exist.

## Scalp journal

Every call can be tracked as a paper trade in [journal/SCALP_JOURNAL.md](journal/SCALP_JOURNAL.md),
scored in R (1R is the risk to the stop). It follows the plan above: wait for
the trigger, take half at T1, move the stop to break-even, run the rest to T2,
and use the time stop.

```bash
.venv/Scripts/python.exe -m backend.cli scalp --top 300 --journal   # add a scan's calls
.venv/Scripts/python.exe -m backend.cli scalp-journal               # replay all calls, refresh the tables
```

The calls are rows in `journal/scalps.csv`. The same coin and side is skipped
if it was called in the last 4 hours (`--skip-hours`). The replay code is in
`backend/scalp_journal.py`.

## Limits

- Divergences can repeat: a third higher high with a third weaker RSI happens
  often in strong trends. The trigger and the stop are what protect you.
- Funding and open interest come from Binance futures. The trades themselves
  happen on CoinDCX, so prices there can differ slightly.
- The scanner has **not been backtested yet**. Treat its first weeks as paper
  trades, and judge it on results before trusting the score.
