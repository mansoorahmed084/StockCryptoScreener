# Crypto Relative-Strength Screener

A self-hosted dashboard that shows which crypto coins are **outperforming or
underperforming** their base pairs (BTC, ETH, USDT, INR, and an equal-weight alt
index) across many timeframes at once — `1w / 1d / 4h / 1h / 15m / 3m` — with
multi-condition AND/OR filters, noise-filtered strength scoring, custom
indicators (VuManChu Cipher B), alerts, and a backtest harness.

Primary data source: **CoinDCX** (public candles, no API key required).

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full design.

## Quick start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Print a relative-strength matrix from the command line:

```bash
python -m backend.cli matrix --coins SOL,ETH --base BTC
```

Run the dashboard (Phase 2):

```bash
streamlit run frontend/streamlit_app.py
```

Run the API (Phase 4):

```bash
uvicorn backend.api.app:app --reload
```

## Testing

```bash
pytest
```

Unit tests use synthetic candle series and need no network access.

## Configuration

Everything is driven by [config.yaml](config.yaml): coin universe, bases,
timeframes, liquidity floor, sector tags, and the per-timeframe noise-filter
thresholds. Secrets (Telegram, future order keys) live in `.env` — see
[.env.example](.env.example). The screener itself needs **no keys**.

## Status — all phases implemented ✅

- **Phase 0** — setup, config
- **Phase 1** — CoinDCX data layer, ratio builder, noise-filtered RS engine, universe/liquidity, data quality, CLI
- **Phase 2** — Streamlit dashboard, filter engine, sector RS, regime header
- **Phase 3** — charts, indicators (WaveTrend + VuManChu Cipher B), alerts (Telegram), signal journal, backtest harness
- **Phase 4** — FastAPI backend API
- **Phase 5** — CoinDCX futures funding signal, scheduled alert scanner, Docker deployment

## Commands

```bash
python -m backend.cli markets                 # sanity-check the data source
python -m backend.cli matrix --base BTC,USDT  # print the RS matrix
python -m backend.cli report --base USDT --timeframes 15m,4h,1d,1w
                                              # multi-TF bullish confluence
                                              # + VuManChu divergence report
python -m backend.cli scan                    # evaluate presets, fire alerts
python -m backend.cli watch --interval 5      # always-on alert scanner
python -m backend.cli backtest --coin SOL --base BTC --timeframe 1d
```

## Deployment

```bash
docker compose up -d          # dashboard :8501, API :8000, alert watcher
```

Put `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` in `.env` to enable alert delivery.
