#!/bin/bash
set -e

# ============================================================
#  Target Info Search — Docker 一键构建 & 启动脚本
# ============================================================

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

ENV_FILE="$ROOT/.env"
CONTAINER_NAME="target-info-search"
IMAGE_NAME="target-info-search"
PORT=8000

# ---- 颜色 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; }

# ---- 1. 检测依赖 ----
for cmd in docker; do
    if ! command -v $cmd &>/dev/null; then
        err "未找到 $cmd，请先安装 Docker Desktop: https://www.docker.com"
        exit 1
    fi
done

if ! docker info &>/dev/null 2>&1; then
    err "Docker 未运行，请先启动 Docker Desktop。"
    exit 1
fi

# ---- 2. 检测 .env ----
if [ ! -f "$ENV_FILE" ]; then
    warn "未找到 .env 文件，使用 .env.example 创建默认配置..."
    if [ -f "$ROOT/.env.example" ]; then
        cp "$ROOT/.env.example" "$ENV_FILE"
        warn "请编辑 $ENV_FILE 填入你的 DEEPSEEK_API_KEY"
        warn "没有 API Key 也可以启动，但 LLM 增强功能将不可用"
    else
        echo "DEEPSEEK_API_KEY=" > "$ENV_FILE"
    fi
fi

# 加载环境变量
set -a
source "$ENV_FILE" 2>/dev/null || true
set +a

if [ -z "$DEEPSEEK_API_KEY" ] || [ "$DEEPSEEK_API_KEY" = "YourKEY" ]; then
    warn "DEEPSEEK_API_KEY 未设置或为默认值，LLM 文献增强将跳过。"
fi

# ---- 3. 构建前端 (宿主机) ----
log "构建前端静态文件..."
FRONTEND_DIR="$ROOT/frontend"
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    log "安装前端依赖..."
    cd "$FRONTEND_DIR" && npm install
fi
cd "$FRONTEND_DIR" && npm run build
cd "$ROOT"
log "前端构建完成 ✅"

# ---- 4. 构建 Docker 镜像 ----
log "开始构建 Docker 镜像: $IMAGE_NAME ..."
docker compose build 2>&1 | while IFS= read -r line; do
    echo "  $line"
done
log "镜像构建完成 ✅"

# ---- 5. 停止旧容器 ----
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log "停止旧容器..."
    docker compose down 2>/dev/null || true
fi

# ---- 6. 启动服务 ----
log "启动服务..."
docker compose up -d

# ---- 7. 等待健康检查 ----
log "等待服务就绪..."
MAX_WAIT=60
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
    if curl -sf http://127.0.0.1:$PORT/api/health > /dev/null 2>&1; then
        log "服务已就绪 ✅"
        break
    fi
    sleep 2
    ELAPSED=$((ELAPSED + 2))
    echo -n "."
done
echo ""

if [ $ELAPSED -ge $MAX_WAIT ]; then
    err "服务启动超时，请检查日志: docker compose logs"
    exit 1
fi

# ---- 8. 打印访问地址 ----
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Target Info Search 已启动！${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

# 获取本机局域网 IP
LAN_IP=$(ifconfig 2>/dev/null | grep -Eo 'inet (addr:)?([0-9]*\.){3}[0-9]*' | grep -Eo '([0-9]*\.){3}[0-9]*' | grep -v '127.0.0.1' | head -1)

echo -e "  ${CYAN}本机访问:${NC}    http://localhost:$PORT"
if [ -n "$LAN_IP" ]; then
    echo -e "  ${CYAN}局域网访问:${NC}  http://$LAN_IP:$PORT"
fi
echo ""
echo -e "  ${CYAN}健康检查:${NC}    http://localhost:$PORT/api/health"
echo -e "  ${CYAN}查看日志:${NC}    docker compose logs -f"
echo -e "  ${CYAN}停止服务:${NC}    docker compose down"
echo ""
echo -e "${GREEN}============================================${NC}"
