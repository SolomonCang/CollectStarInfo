# ============================================================
#  Target Info Search — Dockerfile (纯 Python 运行时)
#  前端在宿主机通过 npm run build 预构建
# ============================================================
FROM python:3.12-slim

WORKDIR /app

# 复制预下载的 Linux wheel 包，离线安装 (免网络)
COPY docker-wheels/ /tmp/wheels/
RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels/ \
    astroquery astropy pandas requests PyYAML fastapi "uvicorn[standard]" numpy \
    && rm -rf /tmp/wheels/

# 复制后端源码
COPY backend/ ./backend/
COPY src/ ./src/
COPY config.yaml ./config.yaml
COPY targets_input.txt ./targets_input.txt

# 复制前端预构建产物 (先在宿主机执行: cd frontend && npm run build)
COPY frontend/dist/ ./frontend/dist/

# 创建输出目录
RUN mkdir -p results data/lightcurves

EXPOSE 8000

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
