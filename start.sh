#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ═══════════════════════════════════════════════════════════════════
#  Target Info Search — 一键启动 (后端 + 前端)
# ═══════════════════════════════════════════════════════════════════

# ── 默认配置 ──────────────────────────────────────────────────────
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
NO_OPEN="${NO_OPEN:-false}"
INSTALL_FRONTEND="${INSTALL_FRONTEND:-false}"
TIMEOUT_SEC="${TIMEOUT_SEC:-60}"

# ── 辅助函数 ──────────────────────────────────────────────────────

# 获取本机局域网 IP
get_lan_ip() {
    local ip=""
    # 方法1: 遍历活跃网卡
    if command -v ifconfig &>/dev/null; then
        ip=$(ifconfig 2>/dev/null | grep -Eo 'inet (addr:)?([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)' \
            | grep -Eo '([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)' \
            | grep -v '^127\.' \
            | head -1)
    fi
    # 方法2: ip addr (Linux)
    if [ -z "$ip" ] && command -v ip &>/dev/null; then
        ip=$(ip addr 2>/dev/null | grep -Eo 'inet [0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' \
            | awk '{print $2}' \
            | grep -v '^127\.' \
            | head -1)
    fi
    # 方法3: route get (macOS)
    if [ -z "$ip" ]; then
        ip=$(route -n get default 2>/dev/null | grep 'interface' | head -1 || true)
        if [ -n "$ip" ]; then
            local iface
            iface=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
            ip=$(ifconfig "$iface" 2>/dev/null | grep -Eo 'inet [0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' \
                | awk '{print $2}' \
                | head -1)
        fi
    fi
    echo "$ip"
}

# 等待 URL 就绪
wait_for_url() {
    local url="$1"
    local label="$2"
    local timeout="${3:-$TIMEOUT_SEC}"
    local deadline
    deadline=$(($(date +%s) + timeout))

    echo -n "⏳ 等待 ${label} 就绪..."
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null | grep -qE '^(2|3|4)'; then
            echo " ✅"
            return 0
        fi
        sleep 1
    done
    echo " ❌ 超时"
    return 1
}

# 释放端口
kill_port() {
    local port="$1"
    local pids
    if command -v lsof &>/dev/null; then
        pids=$(lsof -ti ":$port" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo "🔧 释放端口 $port (PID: $pids)..."
            kill -9 $pids 2>/dev/null || true
            sleep 0.5
        fi
    fi
}

# 清理子进程
cleanup() {
    echo ""
    echo "🛑 正在停止服务..."
    [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true
    [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
    wait 2>/dev/null || true
    echo "✅ 已停止"
}

# ═══════════════════════════════════════════════════════════════════
#  环境检测
# ═══════════════════════════════════════════════════════════════════

# Python
if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON_BIN="$(command -v python3)"
elif command -v python &>/dev/null; then
    PYTHON_BIN="$(command -v python)"
else
    echo "❌ 未找到 Python 解释器,请先创建 .venv 或安装 Python" >&2
    exit 1
fi
echo "🐍 Python : $PYTHON_BIN ($($PYTHON_BIN --version 2>&1))"

# Node / npm
if ! command -v npm &>/dev/null; then
    echo "❌ 未找到 npm,请先安装 Node.js" >&2
    exit 1
fi
echo "🎨 Node   : $(node --version 2>&1) / npm $(npm --version 2>&1)"

# ── 安装 Python 依赖 ──────────────────────────────────────────────
if ! "$PYTHON_BIN" -c "import fastapi" 2>/dev/null; then
    echo "📦 正在安装 Python 依赖..."
    "$PYTHON_BIN" -m pip install -r "$SCRIPT_DIR/requirements.txt" --quiet
fi

# ── 安装前端依赖 ──────────────────────────────────────────────────
if [ ! -d "$SCRIPT_DIR/frontend/node_modules" ] || [ "$INSTALL_FRONTEND" = "true" ]; then
    echo "📦 正在安装前端依赖..."
    (cd "$SCRIPT_DIR/frontend" && npm install --silent)
fi

# ═══════════════════════════════════════════════════════════════════
#  释放端口 & 检测 LAN IP
# ═══════════════════════════════════════════════════════════════════

kill_port "$PORT"
kill_port "$FRONTEND_PORT"

LAN_IP=$(get_lan_ip)
if [ -n "$LAN_IP" ]; then
    echo "🌐 LAN IP : $LAN_IP"
fi

# 前端 API 代理地址：有 LAN IP 就用它，否则用 localhost
if [ "$HOST" = "0.0.0.0" ] && [ -n "$LAN_IP" ]; then
    export VITE_API_BASE="http://${LAN_IP}:${PORT}"
else
    export VITE_API_BASE="http://127.0.0.1:${PORT}"
fi

# ═══════════════════════════════════════════════════════════════════
#  启动服务
# ═══════════════════════════════════════════════════════════════════

trap cleanup EXIT INT TERM

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🚀 Target Info Search — 启动中..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 启动后端
echo "🔧 启动后端 (FastAPI) ..."
"$PYTHON_BIN" -m uvicorn backend.app.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --log-level info &
BACKEND_PID=$!

# 启动前端
echo "🎨 启动前端 (Vite) ..."
(cd "$SCRIPT_DIR/frontend" && npx vite --host "$HOST" --port "$FRONTEND_PORT") &
FRONTEND_PID=$!

# ── 等待就绪 ──────────────────────────────────────────────────────
wait_for_url "http://127.0.0.1:${PORT}/" "后端" || true
wait_for_url "http://127.0.0.1:${FRONTEND_PORT}/" "前端" || true

# ── 打印访问信息 ──────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ 服务已启动!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  前端页面 : http://127.0.0.1:${FRONTEND_PORT}"
echo "  后端 API  : http://127.0.0.1:${PORT}"
echo "  API 文档  : http://127.0.0.1:${PORT}/docs"
if [ -n "$LAN_IP" ]; then
    echo "  ─────────────────────────────────────────"
    echo "  局域网访问:"
    echo "  前端页面 : http://${LAN_IP}:${FRONTEND_PORT}"
    echo "  后端 API  : http://${LAN_IP}:${PORT}"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  按 Ctrl+C 停止所有服务"
echo ""

# ── 打开浏览器 ────────────────────────────────────────────────────
if [ "$NO_OPEN" != "true" ]; then
    if command -v open &>/dev/null; then
        open "http://127.0.0.1:${FRONTEND_PORT}" 2>/dev/null || true
    elif command -v xdg-open &>/dev/null; then
        xdg-open "http://127.0.0.1:${FRONTEND_PORT}" 2>/dev/null || true
    fi
fi

# ── 等待进程退出 ──────────────────────────────────────────────────
wait -n "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
