# Sehe account — spot loss recovery plan

Written 2026-10-01. Review point: 2027-03-31 (end of the financial year);
working target 12 months (see "Decision 2026-10-01" in section 4).

## 1. The goal

The Sehe account holds spot coins that are worth less than we paid for them.
We trade **futures on the same coins** to win that loss back. When a coin's
futures profit covers its spot loss, we **close both** the futures trade and the
spot holding of that coin. Then that coin is done.

- Futures only. No new spot buys: each spot sell costs 1% TDS.
- Spot is sold **once per coin**, at the end, when its ledger reaches breakeven.
- We trade **2–3 coins at a time**: the ones with the best setup now, not the
  ones with the biggest loss.
- Capital: **≈ ₹3.7 lakh** in the Sehe INR futures wallet, in two parts
  (₹1 lakh now, ₹2.7 lakh after the first 20 trades pass).

## 2. Read this first: tax

As far as we know, Indian tax law (Section 115BBH) taxes crypto profit at a flat
30% and does **not** let a crypto loss reduce any other income. If that is right,
the futures profit is taxed at 30% and the spot loss gives no tax relief, so
"breakeven = no tax" does not hold. **Check this with a CA before the first
trade.** The plan below works the same either way; only the target changes:

| Case | Target futures profit |
|---|---|
| Spot loss can be set off | ≈ ₹1.93 lakh (the gap below) |
| Spot loss cannot be set off (30% on profit) | ≈ ₹2.76 lakh |

The 1% TDS on the final spot sell is a credit you claim back in your ITR. It
still locks cash, so each coin needs a small cushion (section 6).

## 3. The coin ledger (start values)

Paid = average cost of the coins still held, from the full spot trade history.
Now = value on 2026-10-01. USDT→INR at 99.81. Holdings bought for under $50 are
left out.

| Coin | Futures pair | Paid | Now | Gap to win back |
|---|---|---|---|---|
| RUNE | B-RUNE_USDT | $400 | $80 | $320 |
| DOT | B-DOT_USDT | $347 | $81 | $266 |
| AR | B-AR_USDT | $283 | $91 | $192 |
| TNSR | B-TNSR_USDT | $200 | $11 | $189 |
| BLUR | B-BLUR_USDT | $200 | $11 | $189 |
| GMT | B-GMT_USDT | $179 | $21 | $158 |
| ILV | B-ILV_USDT | $150 | $21 | $129 |
| INJ | B-INJ_USDT | $266 | $142 | $124 |
| SEI | B-SEI_USDT | $150 | $44 | $106 |
| IMX | B-IMX_USDT | $90 | $25 | $65 |
| TIA | B-TIA_USDT | $80 | $22 | $58 |
| OP | B-OP_USDT | $82 | $25 | $57 |
| BEAMX | B-BEAMX_USDT | $50 | $4 | $46 |
| ORDI | B-ORDI_USDT | $70 | $49 | $21 |
| COTI | B-COTI_USDT | $50 | $29 | $21 |
| AVAX | B-AVAX_USDT | $50 | $44 | $6 |
| ARB | B-ARB_USDT | $92 | $106 | already above cost |
| S | B-S_USDT | no buy found | $82 | cost unknown — left out |
| **Total** | | **$2,739** | | **≈ $1,933 ≈ ₹1.93 lakh** |

All 18 coins have an INR futures pair. The gap moves every day with the spot
price; the live ledger (section 9, tool 1) recomputes it.

**Update 2026-10-01 (live ledger):** with costs in INR at each trade day's
USDT/INR rate, 17 coins are active and the ledger needs **≈ ₹1.91 lakh**. But
most coins hold coins with **no buy in the CoinDCX trade history** (e.g. 334 of
516 ARB): bought on another exchange or in the app's simple Buy screen. They
are costed at today's value for now, so the real loss is higher (you see
**over $7,000** across both accounts in the app). Put each coin's real cost
(the app's "Invested") into `data_cache/recovery_sehe.csv`; the targets in
section 5 then grow with it. Six coins have no buy at all and are skipped until
their cost is set: JOE, KSM, MOVR, PROM, S, XTZ.

**A coin's ledger** = futures profit taken on that pair (after fees and funding)
+ (spot value now − paid). It is closed when the ledger is ≥ 0 plus the cushion.

Note the double effect: a **long** on a coin we hold gains on both legs (the
futures trade and the spot value). A **short** is also a hedge: it gains while
the spot leg loses. So longs close a gap faster when the trend is up; shorts
stop the gap from growing when the trend is down.

## 4. How a trade is chosen: top down

Every trade needs all four steps to agree. If one step says no, there is no trade.

**Step 1 — BTC first (1D and 4H).**
- Trend: price vs EMA 20/50/200, higher highs / higher lows or the reverse.
- Key levels, daily order blocks, liquidation heatmap clusters.
- BTC dominance: rising BTC.D is bad for alt longs.
- Result: **risk-on** (alt longs allowed), **risk-off** (shorts only), or
  **chop** (only A+ setups, smaller size).
- No alt long while BTC 4H is making lower lows.

**Step 2 — the coin's big picture (1D and 4H).**
- Trend and structure, daily order blocks (purple zones), triangles and wedges.
- Strength vs BTC: the coin/BTC chart and the BTC Strength page. Longs go to
  coins stronger than BTC; shorts to coins weaker than BTC.
- Room to the next big level: there must be space for at least 3R.

**Step 3 — entry on the low timeframe (15m, then 5m).**
- Break of the pattern line or range, then a retest that holds.
- VuManChu: wave cross in the trade's direction, money flow agreeing.
- Volume above its recent average on the break.
- Liquidation clusters as targets (price is pulled to them).

**Step 4 — exit.**
- Stop beyond the structure that proves the idea wrong (never inside noise).
- At 2R: take half off, stop to breakeven.
- The rest trails under the last closed 15m candle (`--trail-candle 15m`) so a
  coin that runs 20–40% is not cut early. On a strong 1H trend, switch the
  trail to 1h.
- Exits are not fixed: our research showed the best exit changes per setup
  type. We record each exit and review after 20 trades.

### The setups we take

| Setup | When | Direction |
|---|---|---|
| A. Breakout | Coin breaks a 4H/1D range, triangle or wedge on volume; BTC risk-on | Long |
| B. Order-block retest | Pullback into a daily order block in the 1D trend's direction | Either |
| C. Failed breakout / rejection | Coin rejects 4H/1D resistance while BTC is weak | Short |
| D. Pump exhaustion | Coin up 30%+ in a day, 15m structure breaks down | Short, half size |

Only setups with **reward ≥ 2R** to the first target. A+ means all four steps
agree, BTC is risk-on (for a long) and the target is ≥ 3R away.

### Real costs (CoinDCX app, 2026-10-01)

The app's Coins P&L page shows Sehe invested **$8,782**, worth $1,054 now
(−$7,728). With the app's "Invested" per coin in the ledger (buys under $50
left out), **25 coins** are active and the gap is **≈ ₹7.36 lakh** — almost
4x the first estimate. The tables above are now too low; `trade recovery
--account sehe` is the live number.

- **S (Sonic) alone is ₹1.79 lakh** (invested $1,866, now $80) — a quarter of
  the whole gap.
- Next: GMT ₹61k, ARB ₹61k, INJ ₹43k, OP ₹40k, ORDI ₹37k.
- Smallest (quick wins first): BEAMX ₹4.6k, GMX ₹5.8k, XTZ ₹5.9k, KSM ₹6.4k,
  PROM ₹6.6k, MOVR ₹7k.
- SEI was not in the screenshots; its cost is still from the trade history.

**What this means for ₹1 lakh:** winning back ₹7.36 lakh in 6 months is +636%,
about **39% a month** compounded. That is not a realistic target. So:

| Way | Capital | Monthly return needed | Note |
|---|---|---|---|
| Full recovery, ₹1 lakh | ₹1 lakh | ≈ 39% | not realistic |
| Full recovery, more capital | ≈ ₹3.7 lakh | ≈ 20% | very aggressive |
| Full recovery, more capital | ≈ ₹9.5 lakh | ≈ 10% | hard |
| **Partial recovery, ₹1 lakh** | ₹1 lakh | ≈ 20% | close the small coins one by one |

### Decision 2026-10-01: full recovery, more capital, more time

The owner chose **full recovery** with **≈ ₹3.7 lakh** of futures capital, and
the deadline may move past 2027-03-31. Coins are still closed one by one as
each reaches breakeven, smallest gaps with a good setup first. 2027-03-31 is
now a **review point**: coins closed before it fall in FY 2026-27, the rest in
FY 2027-28. (If the 30% tax applies, every target is ~1.43x higher.)

₹3.7 lakh must grow to cover ₹7.36 lakh, i.e. about **3x the capital**:

| Time | Return needed per month (compounded) |
|---|---|
| 6 months (2027-03-31) | ≈ 20% |
| 9 months (2027-06-30) | ≈ 13% |
| 12 months (2027-09-30) | ≈ 10% |

Working target: **12 months at ~10% a month**, faster when the market gives it.

**Capital in two parts (recommended):**
1. **₹1 lakh now.** Limits stay as set for ₹1 lakh (section 9, tool 2).
2. **₹2.7 lakh after the first 20 trades pass** the milestone below. Then the
   `trading.accounts.sehe.limits` numbers are raised to the ₹3.7 lakh column.

This way a bad start costs part of ₹1 lakh, not part of ₹3.7 lakh.

## 5. Size and risk

Big moves are real, so A+ setups get real size; the hard limits below stop one
bad week from ending the plan. All sizes are % of the wallet, so they grow with
profit and shrink with loss.

| Item | Rule | at ₹1 lakh | at ₹3.7 lakh |
|---|---|---|---|
| Risk per A+ trade | 3% of the wallet | ₹3,000 | ₹11,100 |
| Risk per normal trade | 1.5% | ₹1,500 | ₹5,550 |
| Leverage | up to 5x; up to 10x only on A+ with `--override`, stop ≤ 5% | | |
| Open at the same time | 2–3 coins, never more than 3 positions | | |
| Adding to a winner | stop at breakeven first; max 2 adds, each half the first size | | |
| Daily loss stop | −6% of the wallet → no new trades that day | ₹6,000 | ₹22,200 |
| Weekly loss stop | −15% → stop for the week and review | ₹15,000 | ₹55,500 |
| Hard stop for the plan | wallet −35% from its high → stop everything and review | ₹65,000 left | ₹2.4 lakh left |

With 3% risk on A+ trades, ~10% a month needs the average trade to make about
+0.25R over ~20 trades a month. We check the real number at each milestone:

| Milestone | Pass | Then |
|---|---|---|
| After 20 trades | expectancy ≥ +0.25R, wallet not below ₹85,000 | add the ₹2.7 lakh; raise the limits |
| Every month | on pace for ~10% a month (ledger "to go" falling) | keep going |
| Any time | hard stop hit | stop, review, no new money until the review is done |

## 6. Closing a coin at breakeven

1. The ledger shows the coin at **≥ 0 + cushion**. Cushion = 1.5% of the spot
   value (1% TDS + spot fee + slippage).
2. Close any open futures trade on that coin:
   `.venv/Scripts/python.exe -m backend.cli trade close COIN --account sehe`
3. Sell the spot holding of that coin in the CoinDCX app (one sell, 1% TDS).
4. Mark the coin **done** in the ledger. Its futures profit stays in the wallet
   and works for the next coin.

(With the app's real costs, ARB is far below cost too; it is in the ledger.)

## 7. The daily routine

The **trade bot** runs all day (`deploy/trade_bot_sehe.bat`). No commands.

1. **The bot scans** the ledger coins every 15 minutes with the scanner's rules
   and sends each ready setup to Telegram with a **Place** button.
2. **Claude scans** on request (best IST hours from PRODUCT.md): BTC regime,
   the open coins, then the rest of the ledger for the best 2–3 top-down setups
   (section 4). Each one goes to Telegram the same way, with its reason:
   `trade propose COIN long --sl X --tp Y --risk R --tf 15m --why "..." --account sehe`.
   Logged in `journal/trades.csv`.
3. **You tap Place**: the bot re-checks at the current price and shows the
   fresh size, stop, target and R. **Confirm** (within 2 minutes) places it with
   its stop and target; **Skip** drops it. Claude never places or closes a trade.
4. **The bot watches**: stop on the exchange, trailing, breakeven.
5. **End of day**: journal updated, ledger updated, any coin at breakeven flagged.

## 8. Rules that do not bend

- Every trade has a stop on the exchange from the first second.
- No revenge trades after a loss. No moving a stop further away.
- No trade against BTC's 4H trend unless it is setup C or D.
- No trade in the 30 minutes before big US data (CPI, FOMC, NFP).
- Funding rate above 0.1% per 8h against us → skip or shorten the hold.

## 9. Tools (built 2026-10-01; details in PRODUCT.md, Trade page)

1. **Recovery ledger**: `trade recovery --account sehe` — per coin: paid, spot
   value now, futures P&L on that pair, ledger, what is still to go, and a
   BREAKEVEN flag. Costs live in `data_cache/recovery_sehe.csv`.
2. **Per-account limits**: `trading.accounts.sehe.limits` — risk ₹3,000,
   margin ₹20,000, leverage 10x (above 5x still needs `--override`),
   3 positions, daily loss ₹6,000. Main keeps its own limits.
3. **Adds to a winner**: `trade add COIN --risk R --account sehe` — only once
   the stop is at or past the average price; max 2 adds; the stop is re-sent
   on the whole position.
4. **Spot coins** on the Trade page, for each account (the ledger, once started).
5. **Telegram trade bot**: `trade bot --account sehe` / `deploy/trade_bot_sehe.bat`
   — watch + scan + Place/Confirm buttons; `trade propose` for setups found in chat.

## 10. Before the first trade

- [ ] CA confirms the tax case (section 2).
- [ ] ₹1,00,000 moved into the Sehe **INR futures** wallet (it has none yet);
      ₹2.7 lakh more after the 20-trade milestone.
- [ ] Sehe API key bound to the trading machine's IP.
- [x] Tools 1–4 built and tested.
- [ ] Real costs typed into `data_cache/recovery_sehe.csv` for coins bought elsewhere.
- [ ] One `trade preview --account sehe` checked end to end.

## Account name

The second CoinDCX account is **sehe**. Its keys in `.env` are
`COINDCX_API_KEY_SEHE` / `COINDCX_API_SECRET_SEHE`. Use `--account sehe` on
every `trade` command.
