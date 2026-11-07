#!/bin/sh
# Run INSIDE the OpenClaw gateway container:
#   sudo docker exec <gateway> sh /home/node/.openclaw/workspace/smc/create_jobs.sh
# Creates (or, through the declaration keys, updates) the two SMC jobs:
#   smc-scan     a COMMAND job: the tested Python scan, no model involved,
#                5 minutes after every 4h close (00/04/08/12/16/20 UTC)
#   smc-monitor  an AGENT job on GPT-5.6 Terra, 7 minutes later: runs the one
#                read-only script report_input.sh (the exec tool is its only
#                tool: this OpenClaw has no separate file-read tool in cron
#                runs) and sends a short report to Telegram. It places nothing.
set -e
W=/home/node/.openclaw/workspace/smc
TO=1265841645            # the owner's Telegram chat (same as the GST jobs)

openclaw cron add --declaration-key smc-scan --name smc-scan \
  --description "SMC Sweep-Break 4h scan + paper journal (deterministic Python, no model)" \
  --cron "5 0,4,8,12,16,20 * * *" --tz UTC --exact \
  --command "$W/.venv/bin/python research/scan_smc.py --log --min-vol 5 --watch 3" \
  --command-cwd "$W/freqtrade-lab" --timeout-seconds 900 --no-deliver

openclaw cron add --declaration-key smc-monitor --name smc-monitor \
  --description "SMC Sweep-Break monitor: GPT-5.6 Terra reads the scan and journal, reports to Telegram" \
  --cron "12 0,4,8,12,16,20 * * *" --tz UTC --exact \
  --session isolated --model openai/gpt-5.6-terra --tools exec --light-context \
  --timeout-seconds 300 --announce --channel telegram --to "$TO" \
  --message "$(cat "$W/smc_monitor_prompt.txt")"

openclaw cron list | grep -E "smc-|Name"
