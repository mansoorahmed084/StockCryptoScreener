# Moving the SMC bot to the Oracle VM

What runs in the cloud (deploy/docker-compose.yml):

| service | does |
|---|---|
| `smc` | scans 5 min after every 4h close; paper journal; CoinDCX dry-run check of each fresh call; sends each fresh call to Telegram with a **Place** button; NEW / CLOSED messages; an "ACTION: close it" message when a held trade's strategy exit comes |
| `tradebot` | `trade bot` for every account: your Place + Confirm taps, position checks, stop trails, the Sehe ledger scan. A trade is placed only after your two taps |
| `dashboard` | Streamlit on 127.0.0.1, for the Cloudflare Tunnel later (optional) |

No public port is opened. The bots only make outbound calls.

## Your steps (accounts and keys are yours to create)

1. **Create the VM** in Oracle Cloud (Always Free): region Mumbai or
   Hyderabad, Ubuntu 24.04, shape `VM.Standard.A1.Flex` (1 OCPU, 6 GB is
   plenty). Paste the public key from `~/.ssh/oracle_screener.pub`.
   **Reserve the public IP** so it never changes — the CoinDCX keys are bound
   to it.
2. **Create new CoinDCX API keys** for the main and Sehe accounts, bound to
   that IP, with futures trading. The laptop keys will not work from the VM.
3. **Send me the IP.** I run `deploy/setup-vm.sh` on it (Docker).
4. **Stop the laptop bots** so two bots never answer the same Telegram:
   ```powershell
   cd freqtrade-lab; .\schedule-smc-scan.ps1 -Remove
   ```
   and close the "Sehe trade bot" window.
5. I run `deploy/push-state.sh <ip>` (config.yaml, trading databases,
   journals — no keys).
6. **Put the keys on the VM** yourself:
   ```bash
   ssh -i ~/.ssh/oracle_screener ubuntu@<ip>
   nano ~/screener-secrets/.env      # fields as in deploy/env.example
   chmod 600 ~/screener-secrets/.env
   ```
7. I run `deploy/deploy.sh <ip>` and check the logs.

## Day to day

```bash
# logs
ssh -i ~/.ssh/oracle_screener ubuntu@<ip> 'cd ~/screener/deploy && sudo docker compose logs --tail 80 smc tradebot'
# copy the journal back and rebuild the pages on the laptop
scp -i ~/.ssh/oracle_screener ubuntu@<ip>:screener-state/journal/smc_paper.csv journal/
freqtrade-lab/.venv/Scripts/python.exe freqtrade-lab/research/smc_paper.py
# stop everything (panic stays available in Telegram via the bot)
ssh -i ~/.ssh/oracle_screener ubuntu@<ip> 'cd ~/screener/deploy && sudo docker compose stop smc tradebot'
```

## Why no AI agent in the order path

The strategy is fixed rules. Plain Python does it the same way every time,
costs nothing to run and can be tested (tests/test_smc_trade.py). An AI
agent (OpenClaw, or Claude through the API) would add cost per run, a chance
of a different answer each time, and a new way in for anyone who can put
text in front of it — while holding exchange keys. Use an AI for reading the
journal and reviewing results, never for placing orders.
