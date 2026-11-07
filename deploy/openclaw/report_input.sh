#!/bin/sh
# Prints what the Terra monitor job reports on: the last scan run from the
# log, then the journal's summary, open and closed tables. Read-only.
W=/home/node/.openclaw/workspace/smc
LOG=$W/freqtrade-lab/user_data/logs/smc_scan.log
echo "NOW: $(date -u '+%Y-%m-%d %H:%M UTC')"
if [ -f "$W/auto_trade.on" ]; then echo "AUTO TRADING: ON"; else echo "AUTO TRADING: OFF"; fi
if pgrep -f "[d]eploy/trade_bot_bg.py" >/dev/null; then echo "TRADE BOT: running"
elif [ -f "$W/trade_bot.on" ]; then echo "TRADE BOT: NOT RUNNING (it should be)"
else echo "TRADE BOT: off"; fi
echo "=== LAST SCAN RUN ==="
if [ -f "$LOG" ]; then
  awk '/^===== /{buf=""} {buf=buf $0 "\n"} END{printf "%s", buf}' "$LOG"
else
  echo "no scan log yet"
fi
echo "=== JOURNAL ==="
sed -n '/<!-- AUTO:SUMMARY -->/,/<!-- \/AUTO:CLOSED -->/p' "$W/journal/SMC_PAPER.md"
