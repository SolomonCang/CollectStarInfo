#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
runtime_home=${COLLECTSTARINFO_RUNTIME_HOME:-$HOME/.local/share/collectstarinfo}
export PATH="$runtime_home/node/bin:$PATH"
python_bin=${PYTHON_BIN:-python3.12}
if [[ ! -x .venv/bin/python ]]; then "$python_bin" -m venv .venv; fi
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 is required"'
node -e 'if (+process.versions.node.split(".")[0] < 22) process.exit(1)'
.venv/bin/python -m pip install --disable-pip-version-check --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r requirements-server.lock
(
  cd frontend
  npm ci --no-audit --no-fund
)
PYTHON_BIN="$repo/.venv/bin/python" bash scripts/verify.sh
(
  cd frontend
  VITE_API_BASE= npm run build -- --base=/apps/stars/
)
.venv/bin/python scripts/smoke-runtime.py
