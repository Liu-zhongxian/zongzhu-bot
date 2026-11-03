# 宗主后端的 Docker 镜像（G21）。在仓库根目录编译：
#   docker compose -f deploy/docker/compose.yaml build
# 镜像里只有后端代码和依赖；配置、模型、私人文件用挂载，见 compose.yaml 和 deploy/docker/README.md。
FROM python:3.10-slim

# libopus0：板子的声音是 Opus；ffmpeg：合成语音转码
RUN apt-get update \
    && apt-get install -y --no-install-recommends libopus0 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /opt/zongzhu/server

# 依赖和 Mac 上用的同一套（版本按 lock 文件锁住）
COPY requirements-macos.txt requirements-macos.lock.txt /opt/zongzhu/
RUN pip install --no-cache-dir -r /opt/zongzhu/requirements-macos.txt -c /opt/zongzhu/requirements-macos.lock.txt

COPY xiaozhi-esp32-server/main/xiaozhi-server/ ./

# 8000 板子的 WebSocket，8003 OTA 和网关页面，4399 小米音箱
EXPOSE 8000 8003 4399
CMD ["python", "app.py"]
