# SMC Sweep-Break on OpenClaw (AWS EC2)

Since 2026-11-07 the SMC scan and its monitoring run inside OpenClaw on the
EC2 server (`ubuntu@13.207.59.231`, Mumbai, key `myClawNew.pem`), so they run
when the laptop is off. The laptop's Windows scan task is disabled.

| OpenClaw job | kind | when (UTC) | does |
|---|---|---|---|
| `smc-scan` | command, no model | :05 past 00, 04, 08, 12, 16, 20 | the tested Python scan (`scan_smc.py --log --min-vol 5 --watch 3`); updates the paper journal |
| `smc-monitor` | agent, **openai/gpt-5.6-terra** | :12 past the same hours | runs `report_input.sh` (its only tool is exec, its only command that script) and sends a short report to Telegram chat 1265841645 through the OpenClaw bot |

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
ssh -i ~/Downloads/myClawNew.pem ubuntu@13.207.59.231 'sudo docker exec $(sudo docker ps -qf name=openclaw-gateway) openclaw cron list'

# after changing the scan code: commit, then copy it again
git archive --format=tar HEAD freqtrade-lab/research/{harness,smc,smc_loop,smc_account,smc_oos,smc_paper,scan_smc,smc_trade}.py \
    backend/__init__.py backend/data/{__init__,binance_futures,futures}.py \
  | ssh -i ~/Downloads/myClawNew.pem ubuntu@13.207.59.231 'tar -x -C ~/openclaw/workspace/smc'

# after changing the prompt or the schedule: copy the files, then
ssh -i ~/Downloads/myClawNew.pem ubuntu@13.207.59.231 'sudo docker exec $(sudo docker ps -qf name=openclaw-gateway) sh /home/node/.openclaw/workspace/smc/create_jobs.sh'

# an OpenClaw image update changed the container's Python: rebuild the env
ssh -i ~/Downloads/myClawNew.pem ubuntu@13.207.59.231 'sudo docker exec $(sudo docker ps -qf name=openclaw-gateway) sh /home/node/.openclaw/workspace/smc/setup_smc.sh'
```

## What did not move

* **Place-button offers and the CoinDCX dry-run check** stay off on EC2: the
  CoinDCX keys are bound to the home IP, and the taps are handled by the trade
  bot on the laptop. To bring them back, create CoinDCX keys bound to
  13.207.59.231 and move the trade bot there too.
* **The trade bot** (`Trade bot (all accounts)`) still runs on the laptop.
* Back to the laptop: `Enable-ScheduledTask -TaskName 'SMC Sweep-Break scan'`
  and disable both OpenClaw jobs (`openclaw cron disable <id>`).
