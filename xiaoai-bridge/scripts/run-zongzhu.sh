#!/bin/bash
# 接宗主后端时启动 bridge（前台运行，Ctrl+C 停止）。
#
#   OPEN_XIAOAI_TOKEN_FILE=<token 文件> ./scripts/run-zongzhu.sh
#   或 OPEN_XIAOAI_TOKEN=<token> ./scripts/run-zongzhu.sh
#
# token 要和音箱上 /data/open-xiaoai/token.txt 一样（speaker/client/install_client.sh 写进去的那份）。
# 打开小智协议（XIAOZHI_ENABLE）和本机 HTTP 接口（API_SERVER_ENABLE，127.0.0.1:9092）。
#
# 可选（config.py 从这些环境变量读，没设就用默认值）：
#   ZONGZHU_OTA_URL        宗主后端的 OTA 地址，默认 http://127.0.0.1:8003/xiaozhi/ota/
#   ZONGZHU_WEBSOCKET_URL  宗主后端的 WebSocket 地址，默认 ws://127.0.0.1:8000/xiaozhi/v1/
#   ZONGZHU_DEVICE_ID      后端认这台音箱用的 ID（MAC 地址格式），默认用这台电脑的网卡地址
#   ZONGZHU_WAKE_WORDS     唤醒词，多个用英文逗号隔开，默认 你好宗主,宗主你好
set -e
cd "$(dirname "$0")/.."

# uv / cargo / rustup 常见的安装位置
export PATH="$HOME/.local/bin:/opt/homebrew/opt/rustup/bin:$HOME/.cargo/bin:$PATH"

if [ -z "${OPEN_XIAOAI_TOKEN:-}" ] && [ -n "${OPEN_XIAOAI_TOKEN_FILE:-}" ]; then
  OPEN_XIAOAI_TOKEN="$(cat "$OPEN_XIAOAI_TOKEN_FILE")"
fi
[ -n "${OPEN_XIAOAI_TOKEN:-}" ] || { echo "要设置 OPEN_XIAOAI_TOKEN 或 OPEN_XIAOAI_TOKEN_FILE"; exit 1; }
export OPEN_XIAOAI_TOKEN
export XIAOZHI_ENABLE=1
export API_SERVER_ENABLE=1

exec ./scripts/start.sh
