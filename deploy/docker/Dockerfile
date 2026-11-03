# 宗主后端的 Docker 镜像（G21、G21b）。在仓库根目录编译：
#   docker compose -f deploy/docker/compose.yaml build
# 镜像里只有后端代码、依赖和各板的唤醒词资源包；配置、模型、私人文件在挂载的 /zongzhu，见 deploy/docker/README.md。
FROM python:3.10-slim

# libopus0：板子的声音是 Opus；ffmpeg：合成语音转码
RUN apt-get update \
    && apt-get install -y --no-install-recommends libopus0 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

# 依赖和 Mac 上用的同一套（版本按 lock 文件锁住）
COPY requirements-macos.txt requirements-macos.lock.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements-macos.txt -c /tmp/requirements-macos.lock.txt

# 照仓库的目录摆：后端找唤醒词资源包默认就是往上几层的 firmware/ 和 web/boards.json（core/gateway/wake_assets.py）
WORKDIR /zongzhu-repo/xiaozhi-esp32-server/main/xiaozhi-server
COPY xiaozhi-esp32-server/main/xiaozhi-server/ ./
COPY firmware/ /zongzhu-repo/firmware/
COPY web/boards.json /zongzhu-repo/web/boards.json
COPY examples/backend.config.yaml examples/grok-bot-webhook.example.json /zongzhu-repo/examples/
COPY deploy/docker/zongzhu_docker.py /zongzhu-repo/deploy/docker/zongzhu_docker.py

# 配置和模型在挂载的 /zongzhu 里；链接过去，配置里的相对路径和在 Mac 上一样
RUN ln -s /zongzhu/data data \
    && ln -s /zongzhu/models/sherpa-onnx-x-asr-zipformer-transducer-zh-en-punct-int8-2026-06-03 \
             models/sherpa-onnx-x-asr-zipformer-transducer-zh-en-punct-int8-2026-06-03 \
    && ln -s /zongzhu/models/sherpa-onnx-kws-open-xiaoai models/sherpa-onnx-kws-open-xiaoai

# 8000 板子的 WebSocket，8003 OTA 和网关页面，4399 小米音箱
EXPOSE 8000 8003 4399
ENTRYPOINT ["python", "/zongzhu-repo/deploy/docker/zongzhu_docker.py"]
CMD ["serve"]
