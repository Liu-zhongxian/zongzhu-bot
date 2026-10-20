#!/bin/bash
# 宗主后端一键安装（macOS）。
#
# 用法（在“终端”里粘贴运行）：
#   /bin/bash -c "$(curl -fsSL <网页地址>/install-mac.sh)"
#
# 做的事：
#   1. 用 Homebrew 安装 Python 3.10、FFmpeg、Opus
#   2. 下载后端代码到 ~/zongzhu（ZONGZHU_DIR 可改），已有配置不会被覆盖
#   3. 建 Python 虚拟环境并安装依赖
#   4. 询问 Bot Webhook 地址和 token，写进 private/grok-bot-webhook.json
#   5. 按本机局域网 IP 生成后端配置
#   6. 下载语音识别模型 SenseVoiceSmall（约 900MB）
#   7. 显示网页第 4 步要填的电脑地址，可以直接启动后端
#
# 重复运行就是更新：代码会换成最新版，配置、模型和 Bot 设置保留。
set -euo pipefail

REPO="Liu-zhongxian/zongzhu-bot"
REF="${ZONGZHU_REF:-main}"
DIR="${ZONGZHU_DIR:-$HOME/zongzhu}"
SERVER_DIR="xiaozhi-esp32-server/main/xiaozhi-server"
CONFIG="$SERVER_DIR/data/.config.yaml"
WEBHOOK="private/grok-bot-webhook.json"

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m注意：%s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m出错：%s\033[0m\n' "$*" >&2; exit 1; }
ask()  { local reply; read -r -p "$1" reply </dev/tty || true; printf '%s' "$reply"; }

[ "$(uname -s)" = Darwin ] || die "这个脚本只支持 macOS。其他系统请按仓库 README「后端」一节手动安装。"

say "检查 Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && eval "$("$b" shellenv)" && break
  done
fi
command -v brew >/dev/null 2>&1 || die "没有找到 Homebrew。请先按 https://brew.sh 的说明安装，再重新运行本脚本。"
BREW_PREFIX=$(brew --prefix)
if [ "$BREW_PREFIX" != /opt/homebrew ]; then
  warn "检测到 Intel Mac（Homebrew 在 ${BREW_PREFIX}）。本项目只在 Apple 芯片上测试过。"
fi

say "安装 Python 3.10、FFmpeg、Opus（已安装的会跳过）"
brew install python@3.10 ffmpeg opus
PYTHON="$BREW_PREFIX/opt/python@3.10/bin/python3.10"
[ -x "$PYTHON" ] || die "找不到 $PYTHON"

say "下载后端代码到 $DIR"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl -fL --progress-bar "https://codeload.github.com/$REPO/tar.gz/$REF" -o "$TMP/src.tar.gz"
mkdir -p "$TMP/src"
tar -xzf "$TMP/src.tar.gz" -C "$TMP/src" --strip-components 1
mkdir -p "$DIR"
# 不带 --delete：本机的配置、模型、日志都保留。
rsync -a "$TMP/src/xiaozhi-esp32-server" "$DIR/"
for f in start.sh requirements-macos.txt LICENSE README.md; do cp "$TMP/src/$f" "$DIR/"; done
rsync -a "$TMP/src/examples" "$DIR/"
chmod +x "$DIR/start.sh"
cd "$DIR"

say "安装 Python 依赖（第一次需要几分钟）"
[ -x .venv/bin/python ] || "$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -r requirements-macos.txt

mkdir -p logs private/bot-replies "$SERVER_DIR/data"
chmod 700 private private/bot-replies

say "设置 Bot Webhook"
if [ -f "$WEBHOOK" ] && ! grep -q YOUR_BOT_WEBHOOK_URL "$WEBHOOK"; then
  echo "已有 ${DIR}/${WEBHOOK}，保留不变。"
else
  echo "后端会把识别出的文字 POST 到你的 Bot。现在不知道可以直接回车，以后再改 ${DIR}/${WEBHOOK}。"
  url=$(ask "Bot Webhook 地址（https://…）：")
  token=""
  if [ -n "$url" ]; then
    read -r -s -p "Bot Webhook token（输入时不显示）：" token </dev/tty || true
    echo
  fi
  ZZ_URL="$url" ZZ_TOKEN="$token" ZZ_REPLIES="$DIR/private/bot-replies" .venv/bin/python - "$WEBHOOK" <<'PY'
import json, os, sys
path = sys.argv[1]
with open("examples/grok-bot-webhook.example.json", encoding="utf-8") as f:
    data = json.load(f)
data["reply_dir"] = os.environ["ZZ_REPLIES"]
if os.environ["ZZ_URL"]:
    data["url"] = os.environ["ZZ_URL"]
    data["token"] = os.environ["ZZ_TOKEN"]
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY
  chmod 600 "$WEBHOOK"
  [ -n "$url" ] || warn "还没填 Bot 地址，后端能启动，但说话不会转给 Bot。"
fi

say "生成后端配置"
IFACE=$(route -n get default 2>/dev/null | awk '/interface:/ {print $2}' || true)
IP=$(ipconfig getifaddr "${IFACE:-en0}" 2>/dev/null || ipconfig getifaddr en0 2>/dev/null || true)
[ -n "$IP" ] || die "查不到本机局域网 IP，请先连上 Wi-Fi 再运行。"
if [ -f "$CONFIG" ]; then
  echo "已有 ${DIR}/${CONFIG}，保留不变（里面的 IP 如有变化请手动改）。"
else
  sed "s/192\.168\.1\.100/$IP/g" examples/backend.config.yaml > "$CONFIG"
  chmod 600 "$CONFIG"
fi

say "下载语音识别模型（约 900MB，已下载的会跳过）"
(cd "$SERVER_DIR" && "$DIR/.venv/bin/python" -c "from modelscope import snapshot_download; snapshot_download('iic/SenseVoiceSmall', local_dir='models/SenseVoiceSmall')")

HOSTNAME_LOCAL="$(scutil --get LocalHostName 2>/dev/null || true)"
printf '\n\033[1;32m安装完成。\033[0m\n\n'
echo "回到网页第 4 步，在「电脑的地址」里填下面任意一个："
[ -n "$HOSTNAME_LOCAL" ] && printf '  \033[1m%s.local\033[0m   （推荐，IP 变了也能用）\n' "$HOSTNAME_LOCAL"
printf '  \033[1m%s\033[0m\n\n' "$IP"
echo "以后启动后端：$DIR/start.sh（在前台运行，关掉终端就停了）"
echo "第一次启动时 macOS 如果询问是否允许 Python 接受传入连接，请选「允许」。"

start=$(ask $'\n现在启动后端吗？[Y/n] ')
case "$start" in
  n|N|no|NO) ;;
  *) exec "$DIR/start.sh" ;;
esac
