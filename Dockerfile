# ============================================================
#  Target Info Search — Dockerfile (纯 Python 运行时)
#  前端在宿主机通过 npm run build 预构建
# ============================================================
FROM python:3.12-slim

WORKDIR /app

# 安装与服务器镜像一致的完整依赖（含 SQLite/PostgreSQL、认证和密钥加密）。
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端源码
COPY backend/ ./backend/
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY migrations/ ./migrations/
COPY config.yaml ./config.yaml
COPY targets_input.txt ./targets_input.txt

# 复制前端预构建产物 (先在宿主机执行: cd frontend && npm run build)
COPY frontend/dist/ ./frontend/dist/

# 创建输出目录
RUN mkdir -p results data/lightcurves warehouse/db warehouse/objects/lightcurves warehouse/cache warehouse/secrets

EXPOSE 8000

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
