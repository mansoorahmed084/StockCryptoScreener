# Market Desk

A research and paper-trading desk. It is **separate from the screener**: it has
its own folder, its own settings ([desk.yaml](desk.yaml)), its own database
(`data_cache/market_desk.db`) and its own app on port 8503. It only *reads*
candles through the chart workspace's data code (Binance for crypto, Yahoo
for NSE / BSE / US stocks). It changes no screener code.

**Paper only.** The desk never sends a real order.

It does the "trading desk" loop from the OpenStock + Grok posts, with free
data and no AI agent:

| Step | What the desk does | File |
|---|---|---|
| Research (night) | Headlines for every watchlist symbol (Google News; Finnhub for US stocks if `FINNHUB_API_KEY` is in `.env`), headline tone, news spikes, crypto Fear & Greed, Binance funding | `news.py` |
| Screen (morning) | Ranks the watchlist 0-100: trend (EMA 20/50/200), RSI, EMA slope, volume | `screen.py` |
| Backtest (night) | Tests 3 rules on 5 years of daily candles with fees and slippage. Keeps a rule only if it also works on **control symbols** that are not on the watchlist | `backtest.py` |
| Plan (morning) | For kept rules that fire today: buy-stop entry, stop, target | `plans.py` |
| Trade (all day) | Paper trades: fills, stops, targets, time exits, with a hard risk layer | `paper.py` |
| Alerts | Price alerts for crypto and stocks | `alerts.py` |
| Heatmap | India sectors, US sectors, crypto groups: 1 day / 1 week / 1 month | `heatmap.py` |

Telegram cards (tagged `· desk`) go to the `TELEGRAM_*` chat in `.env`.
Switch them off with `notify.telegram: false` in `desk.yaml`.

## Run it

```bash
.venv/Scripts/python.exe -m streamlit run market_desk/app.py --server.port 8503
```

Then open http://localhost:8503. The sidebar buttons run each job by hand.

Commands:

```bash
.venv/Scripts/python.exe -m market_desk night      # backtest + news (about 1 min)
.venv/Scripts/python.exe -m market_desk morning    # screen + plans
.venv/Scripts/python.exe -m market_desk tick       # paper trades + alerts, once
.venv/Scripts/python.exe -m market_desk watch      # everything, on the schedule
.venv/Scripts/python.exe -m market_desk status
.venv/Scripts/python.exe -m market_desk alert add NSE:RELIANCE above 1500 --note "breakout"
```

`watch` runs the tick every 5 minutes, the night job at 03:00 IST and the
morning job at 08:45 IST (`schedule` in `desk.yaml`). It must stay running;
for "laptop closed", run it on a server.

## In the cloud (open it from anywhere)

Since 2026-11-10 the desk runs without the laptop:

| Part | Where | What |
|---|---|---|
| Data | Supabase project **MarketDesk** (`kblyeideezamwokclqno`, org "Automation", the AutomatedPosting account, free plan, Mumbai) | schema `desk`, not exposed by the REST API |
| Jobs | EC2 server, OpenClaw, `workspace/desk/` | `desk-tick` every 5 min, `desk-night` 03:00 IST (no Telegram card), `desk-morning` 08:45 IST |
| Page | Streamlit Community Cloud, `market_desk/app.py` | view mode: reads Supabase, runs no jobs |
| Screener page | same app, second page "Screener" (`screener_page.py`) | the screener's own results, saved by the `screener-snap` job (`screener_snap.py`) every 30 min |

The **Screener** page shows four parts of the laptop dashboard, read-only:
the relative-strength matrix with the market regime, BTC Strength for the
top 50 coins, the Pattern Scanner over the top 50 Binance perpetuals
(15m / 1h / 4h / 1d) and the liquidation levels + market read for the top
10. The server runs the screener's code (it needs `config.yaml` in
`workspace/desk/`), because Binance refuses Streamlit Cloud's US servers.
Not on the cloud: the Trade page (CoinDCX keys stay on the server), the
Chart Workspace and chart drawing, and the per-coin Chart Patterns page.

Two database logins (made by `market_desk/sql/setup.py`):

- `desk_writer`: the server jobs and the laptop (`MARKET_DESK_DB_URL` in `.env`).
- `desk_viewer`: the cloud page (`MARKET_DESK_VIEW_DB_URL` in `.env`). It reads
  everything and may add or remove alerts. Nothing else.

With `MARKET_DESK_DB_URL` in `.env`, the laptop's CLI and app use Supabase
too. **Do not run `watch` on the laptop**: the server already runs the jobs.

The server saves the heatmap (every 15 min) and the last prices (every tick)
in Supabase. The cloud page needs no market data of its own, which matters
because Binance refuses US servers, and Streamlit Cloud runs in the US.

### Put the page on Streamlit Cloud (owner's steps)

1. Go to https://share.streamlit.io and sign in with GitHub.
2. **Create app** → repo `mansoorahmed084/StockCryptoScreener`, branch
   `master`, main file `market_desk/app.py`.
3. **Advanced settings** → Python 3.12, and paste these secrets:
   ```toml
   MARKET_DESK_DB_URL = "postgresql://desk_viewer.kblyeideezamwokclqno:PASSWORD@aws-0-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require"
   MARKET_DESK_MODE = "view"
   MARKET_DESK_PASSWORD = "your-page-password"
   ```
   The first value is **not** this example: it is the text after
   `MARKET_DESK_VIEW_DB_URL=` in `.env` (it starts with
   `postgresql://desk_viewer.`). Never the writer line. Inside the quotes go
   only the link and your page password, with no `< >`.

   This copies the ready line to the clipboard (Windows PowerShell):
   ```powershell
   $u = ((Get-Content .env | Select-String '^MARKET_DESK_VIEW_DB_URL=').Line -split '=', 2)[1].Trim(); Set-Clipboard "MARKET_DESK_DB_URL = `"$u`""
   ```
4. **Deploy**. The repo is private, so the app is private: only you, plus
   any viewers you invite under Settings → Sharing.

### Server tasks

```bash
# job status
ssh -i ~/Downloads/myClawNew.pem ubuntu@13.206.103.15 'sudo docker exec $(sudo docker ps -qf name=openclaw-gateway) openclaw cron list'

# after changing desk code: commit, then copy it again
git archive --format=tar HEAD backend market_desk \
  | ssh -i ~/Downloads/myClawNew.pem ubuntu@13.206.103.15 'tar -x -C ~/openclaw/workspace/desk'
```

Setup from scratch: `deploy/openclaw/setup_desk.sh` (Python env),
`deploy/openclaw/create_desk_jobs.sh` (the 3 jobs), and `workspace/desk/.env`
with `MARKET_DESK_DB_URL` (writer) and the two `TELEGRAM_*` lines. Any
OpenClaw agent that can run commands can read that file.

## How a rule is kept or killed

Each rule is tested per market (crypto, India, US), on all watchlist trades
together. It is **kept** only when all of these are true:

1. at least 30 trades,
2. at least +0.05R a trade after fees and slippage,
3. profit factor at least 1.1,
4. the same +0.05R bar on the **control symbols**.

Point 4 is the important one. A rule tested on a hand-picked list can look
good by luck. Symbols that the rule has never seen catch that.

Fill and exit rules (`sim.py`) are the same for the backtest and the paper
trades: a buy stop fills at the entry, or at the open after a gap; a candle
that touches the stop and the target counts as a loss; a gap through the
stop fills at the open; after 20 closed candles the trade closes.

### First result (2026-11-09): all 9 rules killed

| Market | Best rule | Watchlist | Control symbols |
|---|---|---|---|
| Crypto | breakout20 | +0.30R, 141 trades | +0.01R, 158 trades |
| US | breakout20 | +0.13R, 229 trades | +0.00R, 311 trades |
| India | breakout20 | +0.07R, 199 trades | −0.01R, 283 trades |

The watchlist numbers look good only because the watchlist is coins and
stocks that went up. On other symbols, the same rules break even after fees.
So the desk writes **no trade plans** today. That is the correct answer: it
will not paper-trade a rule with no edge. The heatmap, screen, news and
alerts still work.

## What it does not do

- **No X or Reddit.** Both need paid or signed-in API access now. Reddit
  returns 403 to free requests.
- **No AI reading.** Tone is a word count over headlines. It does not read
  articles and it misses sarcasm.
- **Long only, daily candles only.**
- Stocks are about 15 minutes delayed (Yahoo). Alerts check the last price on
  each tick, so a short wick between ticks can be missed.
- Paper equity is in "units" (100,000 to start). Profit is counted in R, so
  INR and USD symbols can share one account.

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests/test_market_desk.py -q
```
