#!/bin/sh
# Run INSIDE the OpenClaw gateway container (Debian, python3, no pip):
#   sudo docker exec <gateway> sh /home/node/.openclaw/workspace/desk/setup_desk.sh
# Builds the Market Desk's own Python environment in workspace/desk/.venv,
# apart from the SMC scan's env. Re-run after an OpenClaw image update that
# changes the container's Python version.
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv --without-pip .venv
fi
if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  python3 - <<'EOF'
import urllib.request
urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", "/tmp/get-pip.py")
EOF
  .venv/bin/python /tmp/get-pip.py -q
fi
.venv/bin/python -m pip install -q --upgrade numpy pandas httpx pyyaml "psycopg[binary]"
.venv/bin/python -c "import numpy, pandas, httpx, yaml, psycopg; print('ok', pandas.__version__, psycopg.__version__)"
