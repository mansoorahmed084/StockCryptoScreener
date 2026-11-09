#!/bin/sh
# Run INSIDE the OpenClaw gateway container:
#   sudo docker exec <gateway> sh /home/node/.openclaw/workspace/desk/create_desk_jobs.sh
# Creates (or, through the declaration keys, updates) the Market Desk jobs.
# All are COMMAND jobs: plain Python, no model. They write to the Supabase
# project MarketDesk (MARKET_DESK_DB_URL in desk/.env) and send the desk's
# Telegram cards. Paper only: nothing here places an order.
#   desk-tick     every 5 min      paper fills / stops / targets, alerts,
#                                  prices, and the heatmap every 15 min
#   desk-night    21:30 UTC        backtest + news (03:00 IST), no Telegram
#                                  card (it would wake the owner)
#   desk-morning  03:15 UTC        screen + trade plans (08:45 IST)
set -e
D=/home/node/.openclaw/workspace/desk
# env -u: the container's empty TELEGRAM_* would hide the ones in desk/.env
PY="env -u TELEGRAM_BOT_TOKEN -u TELEGRAM_CHAT_ID $D/.venv/bin/python -m market_desk"

openclaw cron add --declaration-key desk-tick --name desk-tick \
  --description "Market Desk: paper trades, price alerts, prices + heatmap (Python, no model)" \
  --cron "*/5 * * * *" --tz UTC --exact \
  --command "$PY tick" \
  --command-cwd "$D" --timeout-seconds 240 --no-deliver

openclaw cron add --declaration-key desk-night --name desk-night \
  --description "Market Desk: backtest the rules + read the news (Python, no model)" \
  --cron "30 21 * * *" --tz UTC --exact \
  --command "$PY night --quiet" \
  --command-cwd "$D" --timeout-seconds 1200 --no-deliver

openclaw cron add --declaration-key desk-morning --name desk-morning \
  --description "Market Desk: screen the watchlist + write trade plans (Python, no model)" \
  --cron "15 3 * * *" --tz UTC --exact \
  --command "$PY morning" \
  --command-cwd "$D" --timeout-seconds 900 --no-deliver

openclaw cron list
