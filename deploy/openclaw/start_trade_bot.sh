#!/bin/sh
# Keep-alive for the CoinDCX trade bot (every account) inside the OpenClaw
# gateway container. The OpenClaw job "trade-bot" runs this every 5 minutes.
# When the bot is not running, it starts deploy/trade_bot_bg.py in the
# background, so the bot is back within 5 minutes after a gateway restart.
#
# The bot runs only while the switch file trade_bot.on exists. Make and
# remove it with trade_bot_switch.sh (deploy/openclaw/move_trade_bot.ps1 does
# that from the laptop). Two bots on one Telegram bot fight over the taps,
# so the laptop bot must be stopped first.
#
# The bot places a trade only after the owner taps Place and then Confirm.
W=/home/node/.openclaw/workspace/smc
cd "$W" || exit 1
running() { pgrep -f "[d]eploy/trade_bot_bg.py" >/dev/null; }

if [ ! -f trade_bot.on ]; then echo "trade bot off (no trade_bot.on)"; exit 0; fi
if [ ! -f .env ]; then echo "trade bot NOT started: no .env with the keys"; exit 1; fi
if running; then echo "trade bot running"; exit 0; fi

mkdir -p data_cache
# The OpenClaw container sets TELEGRAM_BOT_TOKEN to an empty string, and
# load_dotenv never overrides a set variable: without this the bot would not
# read the trade bot's token from .env, and its buttons would be off.
unset TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
setsid nohup .venv/bin/python deploy/trade_bot_bg.py >/dev/null 2>&1 </dev/null &
sleep 5
if running; then echo "trade bot started"; exit 0; fi
echo "trade bot did not start. Last log lines:"
tail -n 5 data_cache/trade_bot.log 2>/dev/null
exit 1
