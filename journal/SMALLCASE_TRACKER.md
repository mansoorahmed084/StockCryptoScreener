# Smallcase tracker

The long-term portfolio for the children, one third each: **Safe Haven
Model** and **Metal Tracker** (free Windmill smallcases), and **Nippon India
Large Cap Fund** (Direct, Growth). The large cap fund replaced Growth &
Income Model on 27 Oct 2026. **Data only, not financial advice. No orders
are placed from here. You buy and sell in Zerodha (smallcase and Coin).**

- Add each buy to [smallcase_buys.csv](smallcase_buys.csv): `date` (YYYY-MM-DD),
  `id`, `amount` in Rs, and an optional `note`.
  The ids are Safe Haven `SCMO_0015`, Metal Tracker `SCTR_0008` and
  Nippon India Large Cap `MF_118632`.
- This command refreshes the tables below:
  `.venv/Scripts/python.exe -m backend.smallcase_tracker --sip 50000`.
  A scheduled task runs it on the 1st of each month.

## Rules

- **Value:** each buy gets units at the smallcase index (or the fund's NAV) on
  its date. Today's value is units × today's index. For the smallcases, whole
  shares, charges and your own timing of the rebalances are not counted, so the
  real account can differ a little.
- **Drift:** a holding's share of the total minus its target (33.3%).
- **More than 5 points off:** put the next SIP into the light ones. There is no
  sale, so there is no tax.
- **More than 10 points off:** also think about selling part of the heavy one.
  A sale has tax: 20% on gains held under 1 year, 12.5% after 1 year.
- **Manager rebalance:** each smallcase is rebalanced every quarter. Accept it
  in Zerodha when it shows up. The fund needs no rebalance from you.

## Summary

<!-- AUTO:SUMMARY -->
_Updated 27 Oct 2026. Smallcase values use the public smallcase index, so the real account can differ a little. Fund values use the NAV._

**No buys yet.** Add each buy to [smallcase_buys.csv](smallcase_buys.csv).
<!-- /AUTO:SUMMARY -->

## Alerts

<!-- AUTO:ALERTS -->
- ✅ Nothing to do. The mix is within the limits and no rebalance is due.
<!-- /AUTO:ALERTS -->

## Mix

<!-- AUTO:MIX -->
| Holding | Invested | Value | Gain | Share now | Target | Drift |
|---|---|---|---|---|---|---|
| Safe Haven Model | Rs 0 | Rs 0 | — | 0.0% | 33.3% | — |
| Metal Tracker | Rs 0 | Rs 0 | — | 0.0% | 33.3% | — |
| Nippon India Large Cap Fund (Direct, Growth) | Rs 0 | Rs 0 | — | 0.0% | 33.3% | — |
<!-- /AUTO:MIX -->

## Next SIP

<!-- AUTO:NEXT -->
How to split the next Rs 50,000, to move the mix back to target:

| Holding | Amount |
|---|---|
| Safe Haven Model | Rs 16,667 |
| Metal Tracker | Rs 16,667 |
| Nippon India Large Cap Fund (Direct, Growth) | Rs 16,667 |
<!-- /AUTO:NEXT -->

## Returns

1M, 3M and 1Y are plain returns. 3Y and 5Y are yearly growth (CAGR).

<!-- AUTO:RETURNS -->
| Holding | 1M | 3M | 1Y | 3Y CAGR | 5Y CAGR | Last rebalance | Next rebalance |
|---|---|---|---|---|---|---|---|
| Safe Haven Model | -6.7% | -5.3% | +5.6% | +14.2% | +15.0% | 2026-09-15 | 2026-12-14 |
| Metal Tracker | -7.0% | +2.3% | +18.2% | +23.0% | +19.9% | 2026-09-17 | 2026-12-17 |
| Nippon India Large Cap Fund (Direct, Growth) | -3.2% | -5.8% | -9.6% | +11.0% | +10.9% | — | — |
<!-- /AUTO:RETURNS -->
