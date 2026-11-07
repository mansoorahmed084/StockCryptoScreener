# SMC Sweep-Break on OpenClaw (AWS EC2)

Since 2026-11-07 the SMC scan and its monitoring run inside OpenClaw on the
EC2 server (`ubuntu@13.206.103.15`, Mumbai, key `myClawNew.pem`), so they run
when the laptop is off. The laptop's Windows scan task is disabled.

| OpenClaw job | kind | when (UTC) | does |
|---|---|---|---|
| `smc-scan` | command, no model | :05 past 00, 04, 08, 12, 16, 20 | the tested Python scan (`scan_smc.py --log --min-vol 5 --watch 3`); updates the paper journal |
| `smc-monitor` | agent, **openai/gpt-5.6-terra** | :12 past the same hours | runs `report_input.sh` (its only tool is exec, its only command that script) and sends a short report to Telegram chat 1265841645 through the OpenClaw bot |
| `trade-bot` | command, no model | every 5 min | keep-alive for the CoinDCX trade bot; does nothing until `trade_bot.on` exists (see below) |

The scan is a command job on purpose: the same rules every time, as tested
against the backtest. Terra only reads the result and writes the message. It
places no orders and gives no advice.

## Files in the OpenClaw workspace

`/home/ubuntu/openclaw/workspace/smc/` on the host is
`/home/node/.openclaw/workspace/smc/` in the gateway container:

| path | what |
|---|---|
| `freqtrade-lab/research/*.py`, `backend/...` | the scan code, copied from git HEAD |
| `.venv/` | Python 3.11 env with numpy, pandas, numba, httpx (`setup_smc.sh`) |
| `journal/smc_paper.csv`, `journal/SMC_PAPER.md` | the paper journal (now the master copy) |
| `freqtrade-lab/user_data/logs/smc_scan.log` | every scan run |
| `report_input.sh`, `smc_monitor_prompt.txt`, `create_jobs.sh` | the monitor job |

## Common tasks

```bash
# journal back to the laptop (rebuilds SMC_PAPER.md and the TRADE_JOURNAL block)
deploy/openclaw/pull_journal.sh

# job status and the last runs
ssh -i ~/Downloads/myClawNew.pem ubuntu@13.206.103.15 'sudo docker exec $(sudo docker ps -qf name=openclaw-gateway) openclaw cron list'

# after changing the scan code: commit, then copy it again
git archive --format=tar HEAD freqtrade-lab/research/{harness,smc,smc_loop,smc_account,smc_oos,smc_paper,scan_smc,smc_trade}.py \
    backend deploy/trade_bot_bg.py \
  | ssh -i ~/Downloads/myClawNew.pem ubuntu@13.206.103.15 'tar -x -C ~/openclaw/workspace/smc'

# after changing the prompt or the schedule: copy the files, then
ssh -i ~/Downloads/myClawNew.pem ubuntu@13.206.103.15 'sudo docker exec $(sudo docker ps -qf name=openclaw-gateway) sh /home/node/.openclaw/workspace/smc/create_jobs.sh'

# an OpenClaw image update changed the container's Python: rebuild the env
ssh -i ~/Downloads/myClawNew.pem ubuntu@13.206.103.15 'sudo docker exec $(sudo docker ps -qf name=openclaw-gateway) sh /home/node/.openclaw/workspace/smc/setup_smc.sh'
```

## The trade bot on the server (moved 2026-11-07 17:52 IST, main only)

The CoinDCX trade bot (`trade bot`, every account: Place / Confirm taps,
position checks, stop trails, the Sehe ledger scan) can run inside the same
OpenClaw container. The owner chose this over a separate container. **Any
OpenClaw agent that can run commands can read `smc/.env`, so the exchange
keys are readable by those agents.**

| part | what |
|---|---|
| `trade-bot` job | command job every 5 min: `start_trade_bot.sh` starts `deploy/trade_bot_bg.py` when it is not running, only while `smc/trade_bot.on` exists |
| `trade_bot_switch.sh` | `check` (key names + `trade status` per account), `on`, `off`, `status` |
| `smc/.env` | Telegram lines (copied) + the CoinDCX keys (owner pastes them) |
| `smc/data_cache/` | `trading.db`, `trading_sehe.db`, `recovery_sehe.csv`, `trade_bot.log` |
| scan flags | while `trade_bot.on` exists, `create_jobs.sh` adds `--telegram --dcx-check --offer` to `smc-scan` |

Before the first move (owner):

1. Fixed IP: done 2026-11-07. Elastic IP `13.206.103.15`
   (`eipalloc-0134dc1a1598ea58e`) is on instance `i-0d065d9ea84fad130`; the
   old `13.207.59.231` is gone. If the server is ever deleted, release it.
2. CoinDCX: new API keys for main and sehe, bound to `13.206.103.15`, futures on.
3. Paste them:
   ```bash
   ssh -i ~/Downloads/myClawNew.pem ubuntu@13.206.103.15
   nano ~/openclaw/workspace/smc/.env
   ```

Then from the laptop:

```powershell
deploy\openclaw\move_trade_bot.ps1 -Check   # keys work from the server?
deploy\openclaw\move_trade_bot.ps1          # laptop -> server
deploy\openclaw\move_trade_bot.ps1 -Back    # server -> laptop
```

Sehe keys are optional: without them the bot watches main only and runs no
Sehe ledger scan. After pasting them into `smc/.env`, restart the bot so it
finds the account (`trade_bot_switch.sh off`, then `on`, inside the
container).

The move stops the laptop bot and disables its log-in task (two bots on one
Telegram bot fight over the taps), copies the three state files, and turns
the server bot on. While the bot is on the server, use Telegram for trades:
the laptop dashboard's Trade page reads the old laptop database.

* Back to the laptop for the scan as well: `move_trade_bot.ps1 -Back`, then
  `Enable-ScheduledTask -TaskName 'SMC Sweep-Break scan'` and disable the
  OpenClaw jobs (`openclaw cron disable <id>`).
