#!/bin/bash
# 接宗主后端时启动 bridge（前台运行，Ctrl+C 停止）。
#
#   OPEN_XIAOAI_TOKEN_FILE=<token 文件> ./scripts/run-zongzhu.sh
#   或 OPEN_XIAOAI_TOKEN=<token> ./scripts/run-zongzhu.sh
#
# token 要和音箱上 /data/open-xiaoai/token.txt 一样（speaker/client/install_client.sh 写进去的那份）。
# 打开小智协议（XIAOZHI_ENABLE，连 config.py 里的宗主后端地址）和本机 HTTP 接口（API_SERVER_ENABLE，127.0.0.1:9092）。
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
