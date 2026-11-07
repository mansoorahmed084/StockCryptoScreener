#!/bin/sh
# Run INSIDE the OpenClaw gateway container (Debian, python3, no pip):
#   sudo docker exec <gateway> sh /home/node/.openclaw/workspace/smc/setup_smc.sh
# Builds the Python environment the SMC scan needs, inside the workspace, so
# it survives container restarts. Re-run it if an image update changes the
# container's Python version (the venv points at /usr/bin/python3).
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
.venv/bin/python -m pip install -q --upgrade numpy pandas numba httpx pyyaml
.venv/bin/python -c "import numpy, pandas, numba, httpx; print('ok', numpy.__version__, pandas.__version__, numba.__version__, httpx.__version__)"
