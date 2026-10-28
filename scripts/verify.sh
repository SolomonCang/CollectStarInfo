#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python_bin=${PYTHON_BIN:-$repo/.venv/bin/python}
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
# Test code copies have no production settings, key files, warehouse or reports.
cp -R "$repo/backend" "$repo/src" "$repo/tests" "$temporary/"
mkdir "$temporary/scripts"
cp "$repo/scripts/"*.py "$temporary/scripts/"
(
  cd "$temporary"
  env PERSISTENCE_BACKEND=sqlite-warehouse \
    WAREHOUSE_ROOT="$temporary/warehouse" \
    WORKSPACE_DATABASE_URL="sqlite:///$temporary/warehouse/db/target_info.sqlite" \
    DEEPSEEK_API_KEY_FILE=/dev/null PYTHONDONTWRITEBYTECODE=1 \
    "$python_bin" -m unittest discover -s tests -p 'test_*.py' -v
)
cd "$repo/frontend"
npm test
