#!/usr/bin/env bash
# Ship the committed code (HEAD) to the Oracle VM and rebuild the dashboard.
# Uncommitted changes are not shipped: commit first.
#
#   deploy/deploy.sh <vm-ip>        or   SCREENER_VM=<vm-ip> deploy/deploy.sh
set -euo pipefail

HOST="${1:-${SCREENER_VM:?usage: deploy/deploy.sh <vm-ip>}}"
KEY="${SCREENER_KEY:-$HOME/.ssh/oracle_screener}"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "ubuntu@$HOST")

cd "$(git rev-parse --show-toplevel)"
echo "Shipping $(git rev-parse --short HEAD) to $HOST"
git archive --format=tar HEAD | "${SSH[@]}" '
  rm -rf ~/screener.new && mkdir ~/screener.new &&
  tar -x -C ~/screener.new &&
  rm -rf ~/screener && mv ~/screener.new ~/screener'
"${SSH[@]}" '
  cd ~/screener/deploy &&
  sudo docker compose up -d --build &&
  sudo docker image prune -f >/dev/null &&
  sudo docker compose ps'
