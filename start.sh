#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-/home/cang/personal_serve/.venv/bin/python}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

exec "$PYTHON_BIN" -m uvicorn backend.app.main:app --host "$HOST" --port "$PORT"
