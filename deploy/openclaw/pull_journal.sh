#!/usr/bin/env bash
# Copy the SMC paper journal from the OpenClaw EC2 workspace to the laptop
# and rebuild journal/SMC_PAPER.md and the SMC block of TRADE_JOURNAL.md.
#   deploy/openclaw/pull_journal.sh
set -euo pipefail
HOST="${OPENCLAW_HOST:-ubuntu@13.206.103.15}"
KEY="${OPENCLAW_KEY:-$HOME/Downloads/myClawNew.pem}"
cd "$(git rev-parse --show-toplevel)"
scp -i "$KEY" -o BatchMode=yes "$HOST:openclaw/workspace/smc/journal/smc_paper.csv" journal/smc_paper.csv
freqtrade-lab/.venv/Scripts/python.exe freqtrade-lab/research/smc_paper.py
