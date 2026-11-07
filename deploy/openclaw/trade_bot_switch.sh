#!/bin/sh
# Run INSIDE the OpenClaw gateway container:
#   sh /home/node/.openclaw/workspace/smc/trade_bot_switch.sh check|on|off|status
#
#   check   the .env has every key name (values are never printed), and the
#           CoinDCX keys work from this server: `trade status` for each account
#   on      make trade_bot.on, start the bot now, and add the laptop's extra
#           scan flags (Telegram NEW/CLOSED, CoinDCX dry-run check, Place offer)
#   off     remove trade_bot.on, stop the bot, and take those flags off again
#   status  is the bot running, and its last log lines
set -u
W=/home/node/.openclaw/workspace/smc
cd "$W" || exit 1
PY=.venv/bin/python
running() { pgrep -f "[d]eploy/trade_bot_bg.py" >/dev/null; }

case "${1:-status}" in
  check)
    [ -f .env ] || { echo "no $W/.env yet"; exit 1; }
    bad=0
    for k in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID COINDCX_API_KEY COINDCX_API_SECRET; do
      if grep -Eq "^$k=.+" .env; then echo "  $k: set"; else echo "  $k: MISSING"; bad=1; fi
    done
    [ "$bad" = 0 ] || exit 1
    # sehe is optional: without its keys the bot watches main only (and runs
    # no Sehe ledger scan). After adding them, restart the bot: off, then on.
    accts=main
    if grep -Eq "^COINDCX_API_KEY_SEHE=.+" .env && grep -Eq "^COINDCX_API_SECRET_SEHE=.+" .env; then
      accts="main sehe"
    else
      echo "  sehe keys: not set (the bot will watch main only)"
    fi
    for a in $accts; do
      echo "== trade status --account $a"
      $PY -m backend.cli trade status --account "$a" || bad=1
    done
    [ "$bad" = 0 ] && echo "check ok" || { echo "check FAILED (a 401 means the key is not bound to this server's IP)"; exit 1; }
    ;;
  on)
    touch trade_bot.on
    sh start_trade_bot.sh
    sh create_jobs.sh >/dev/null && echo "scan flags: --telegram --dcx-check --offer added"
    ;;
  off)
    rm -f trade_bot.on
    pkill -f "[d]eploy/trade_bot_bg.py" && echo "trade bot stopped" || echo "trade bot was not running"
    sh create_jobs.sh >/dev/null && echo "scan flags: back to scan + journal only"
    ;;
  status)
    if running; then echo "trade bot running"; else echo "trade bot NOT running"; fi
    [ -f trade_bot.on ] && echo "switch: on" || echo "switch: off"
    tail -n 8 data_cache/trade_bot.log 2>/dev/null
    ;;
  *) echo "usage: trade_bot_switch.sh check|on|off|status"; exit 2 ;;
esac
