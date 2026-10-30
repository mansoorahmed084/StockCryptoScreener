#!/usr/bin/env bash
# One-time move of the bot's state from the laptop to the VM: config.yaml,
# the trade bot's databases and the journals. Run it once, BEFORE the bots
# start on the VM, with the laptop's bots stopped (the Windows task removed
# and the trade bot window closed), so the databases are not being written.
#
#   deploy/push-state.sh <vm-ip>          refuses if the VM already has state
#   deploy/push-state.sh <vm-ip> --force  overwrite the VM's state
#
# The .env with keys is NOT copied: the VM needs its own IP-bound CoinDCX
# keys (deploy/env.example).
set -euo pipefail

HOST="${1:?usage: deploy/push-state.sh <vm-ip> [--force]}"
FORCE="${2:-}"
KEY="${SCREENER_KEY:-$HOME/.ssh/oracle_screener}"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "ubuntu@$HOST")
SCP=(scp -i "$KEY" -o StrictHostKeyChecking=accept-new)

cd "$(git rev-parse --show-toplevel)"
"${SSH[@]}" 'mkdir -p ~/screener-secrets ~/screener-state/data_cache ~/screener-state/journal ~/screener-state/logs'
if [ "$FORCE" != "--force" ] && "${SSH[@]}" 'ls ~/screener-state/data_cache/*.db >/dev/null 2>&1'; then
  echo "The VM already has state in ~/screener-state. Nothing copied (use --force to overwrite)."
  exit 1
fi

"${SCP[@]}" config.yaml "ubuntu@$HOST:screener-secrets/config.yaml"
db=()
for f in data_cache/trading*.db data_cache/recovery_*.csv data_cache/alerts.db \
         data_cache/chart.db data_cache/watchlists.json; do
  [ -f "$f" ] && db+=("$f")
done
"${SCP[@]}" "${db[@]}" "ubuntu@$HOST:screener-state/data_cache/"
"${SCP[@]}" journal/* "ubuntu@$HOST:screener-state/journal/"
echo "Copied config.yaml, ${#db[@]} data files and the journal to $HOST."
"${SSH[@]}" 'ls -la ~/screener-secrets ~/screener-state/data_cache ~/screener-state/journal'
