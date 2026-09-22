#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu VM: Docker, cloudflared, and swap on small
# machines (a 1 GB VM runs out of memory while pip builds the image).
set -euo pipefail

sudo apt-get update -y
sudo apt-get install -y ca-certificates curl docker.io docker-compose-v2
sudo systemctl enable --now docker

# cloudflared from Cloudflare's apt repository
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list >/dev/null
sudo apt-get update -y
sudo apt-get install -y cloudflared

mem_mb=$(awk '/MemTotal/ {print int($2 / 1024)}' /proc/meminfo)
if [ "$mem_mb" -lt 2048 ] && [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
fi

docker --version
cloudflared --version
