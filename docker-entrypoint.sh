#!/bin/bash
set -e

# 如果设置了 DEEPSEEK_API_KEY 环境变量，写入 config.yaml
if [ -n "$DEEPSEEK_API_KEY" ]; then
    echo "[entrypoint] Injecting DEEPSEEK_API_KEY into config.yaml"
    sed -i "s|api_key:.*|api_key: \"$DEEPSEEK_API_KEY\"|" /app/config.yaml
fi

echo "[entrypoint] Starting FastAPI on 0.0.0.0:8000"
exec python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
