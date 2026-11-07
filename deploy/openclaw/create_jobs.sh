#!/bin/sh
# Run INSIDE the OpenClaw gateway container:
#   sudo docker exec <gateway> sh /home/node/.openclaw/workspace/smc/create_jobs.sh
# Creates (or, through the declaration keys, updates) these jobs:
#   smc-scan     a COMMAND job: the tested Python scan, no model involved,
#                5 minutes after every 4h close (00/04/08/12/16/20 UTC)
#   smc-monitor  an AGENT job on GPT-5.6 Terra, 7 minutes later: runs the one
#                read-only script report_input.sh (the exec tool is its only
#                tool: this OpenClaw has no separate file-read tool in cron
#                runs) and sends a short report to Telegram. It places nothing.
#   trade-bot    a COMMAND job every 5 minutes: start_trade_bot.sh starts the
#                CoinDCX trade bot when it is not running, but only while
#                trade_bot.on exists (trade_bot_switch.sh on|off).
set -e
W=/home/node/.openclaw/workspace/smc
TO=1265841645            # the owner's Telegram chat (same as the GST jobs)

# env -u: the container's empty TELEGRAM_BOT_TOKEN would hide the one in .env
SCAN="env -u TELEGRAM_BOT_TOKEN -u TELEGRAM_CHAT_ID $W/.venv/bin/python research/scan_smc.py --log --min-vol 5 --watch 3"
# With the trade bot on this server, the scan also does what the laptop scan
# did: Telegram NEW/CLOSED from the trade bot, the CoinDCX dry-run check, and
# a Place button for each fresh call. All three need the keys in smc/.env.
if [ -f "$W/trade_bot.on" ]; then SCAN="$SCAN --telegram --dcx-check --offer"; fi

openclaw cron add --declaration-key smc-scan --name smc-scan \
  --description "SMC Sweep-Break 4h scan + paper journal (deterministic Python, no model)" \
  --cron "5 0,4,8,12,16,20 * * *" --tz UTC --exact \
  --command "$SCAN" \
  --command-cwd "$W/freqtrade-lab" --timeout-seconds 900 --no-deliver

openclaw cron add --declaration-key trade-bot --name trade-bot \
  --description "Keep-alive: starts the CoinDCX trade bot (Place/Confirm taps) while trade_bot.on exists" \
  --cron "*/5 * * * *" --tz UTC --exact \
  --command "sh $W/start_trade_bot.sh" \
  --command-cwd "$W" --timeout-seconds 60 --no-deliver

openclaw cron add --declaration-key smc-monitor --name smc-monitor \
  --description "SMC Sweep-Break monitor: GPT-5.6 Terra reads the scan and journal, reports to Telegram" \
  --cron "12 0,4,8,12,16,20 * * *" --tz UTC --exact \
  --session isolated --model openai/gpt-5.6-terra --tools exec --light-context \
  --timeout-seconds 300 --announce --channel telegram --to "$TO" \
  --message "$(cat "$W/smc_monitor_prompt.txt")"

openclaw cron list | grep -E "smc-|trade-bot|Name"
