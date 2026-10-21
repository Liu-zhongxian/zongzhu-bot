#!/bin/bash
# 宗主后端一键安装（macOS）。
#
# 用法（在“终端”里粘贴运行）：
#   /bin/bash -c "$(curl -fsSL <网页地址>/install-mac.sh)"
#
# 做的事：
#   1. 检查 Python 3.10、FFmpeg、Opus，只用 Homebrew 安装缺的（不更新 Homebrew，不升级已装的软件）
#   2. 下载后端代码到 ~/zongzhu（ZONGZHU_DIR 可改），已有配置不会被覆盖
#   3. 建 Python 虚拟环境并安装依赖
#   4. 询问 Bot Webhook 地址和 token，写进 private/grok-bot-webhook.json
#   5. 按本机局域网 IP 生成后端配置
#   6. 下载语音识别模型 X-ASR（sherpa-onnx int8 版，约 174MB；Hugging Face 下不动时换 hf-mirror.com）
#   7. 显示网页第 4 步要填的电脑地址，让用户选择启动方式：开机自启（tools/autostart.sh）或自己手动启动
#
# 重复运行就是更新：代码会换成最新版，配置、模型和 Bot 设置保留。
set -euo pipefail

REPO="Liu-zhongxian/zongzhu-bot"
REF="${ZONGZHU_REF:-main}"
DIR="${ZONGZHU_DIR:-$HOME/zongzhu}"
SERVER_DIR="xiaozhi-esp32-server/main/xiaozhi-server"
CONFIG="$SERVER_DIR/data/.config.yaml"
WEBHOOK="private/grok-bot-webhook.json"
# 语音识别模型，目录名要和 config.yaml 里 SherpaXASR 的 model_dir 一致
XASR="sherpa-onnx-x-asr-zipformer-transducer-zh-en-punct-int8-2026-06-03"

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m注意：%s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m出错：%s\033[0m\n' "$*" >&2; exit 1; }
ask()  { local reply; read -r -p "$1" reply </dev/tty || true; printf '%s' "$reply"; }

[ "$(uname -s)" = Darwin ] || die "这个脚本只支持 macOS。其他系统请按仓库 docs/GUIDE.md「手动安装」的「2. 后端」一节安装。"

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

say "检查 Python 3.10、FFmpeg、Opus（已有的不重装）"
# Install only what is missing, without updating Homebrew or upgrading what the
# user has. Installing ffmpeg next to an existing ffmpeg-full once upgraded x265
# under it and broke that ffmpeg-full (2026-10-21).
export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_UPGRADE=1 HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK=1
works() { "$@" >/dev/null 2>&1; }
missing=""  # a word list: /bin/bash 3.2 treats an empty array as unbound under set -u

PYTHON=""
for p in "$BREW_PREFIX/opt/python@3.10/bin/python3.10" "$(command -v python3.10 || true)"; do
  if [ -n "$p" ] && works "$p" -c 'import sys, venv, ensurepip; assert sys.version_info[:2] == (3, 10)'; then
    PYTHON="$p"
    break
  fi
done
if [ -n "$PYTHON" ]; then echo "Python 3.10：已有（${PYTHON}），跳过"; else missing="$missing python@3.10"; fi

FFMPEG=""
for f in "$(command -v ffmpeg || true)" "$BREW_PREFIX/bin/ffmpeg" "$BREW_PREFIX/opt/ffmpeg-full/bin/ffmpeg"; do
  if [ -n "$f" ] && works "$f" -version; then
    FFMPEG="$f"
    break
  fi
done
if [ -n "$FFMPEG" ]; then
  echo "FFmpeg：已有（${FFMPEG}），跳过"
elif brew list --versions ffmpeg-full >/dev/null 2>&1; then
  die "已安装的 ffmpeg-full 无法运行（多半是它依赖的库被升级过）。请先运行 brew upgrade ffmpeg-full，再重新运行本脚本。为了不弄坏它，脚本不会在旁边另装 ffmpeg。"
else
  missing="$missing ffmpeg"
fi

if [ -e "$BREW_PREFIX/lib/libopus.dylib" ]; then echo "Opus：已有，跳过"; else missing="$missing opus"; fi

if [ -n "$missing" ]; then
  echo "需要安装：$missing"
  # shellcheck disable=SC2086  # formula names, split on purpose
  brew install $missing
fi
[ -n "$PYTHON" ] || PYTHON="$BREW_PREFIX/opt/python@3.10/bin/python3.10"
[ -x "$PYTHON" ] || die "找不到 Python 3.10（${PYTHON}）"

say "下载后端代码到 $DIR"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl -fL --progress-bar "https://codeload.github.com/$REPO/tar.gz/$REF" -o "$TMP/src.tar.gz"
mkdir -p "$TMP/src"
tar -xzf "$TMP/src.tar.gz" -C "$TMP/src" --strip-components 1
mkdir -p "$DIR"
# 不带 --delete：本机的配置、模型、日志都保留。
rsync -a "$TMP/src/xiaozhi-esp32-server" "$DIR/"
for f in start.sh requirements-macos.txt requirements-macos-funasr.txt LICENSE README.md; do cp "$TMP/src/$f" "$DIR/"; done
rsync -a "$TMP/src/examples" "$DIR/"
mkdir -p "$DIR/tools"
cp "$TMP/src/tools/autostart.sh" "$TMP/src/tools/launcher.c" "$DIR/tools/"
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

say "下载语音识别模型 X-ASR（约 174MB，已下载的会跳过）"
MODEL_DIR="$SERVER_DIR/models/$XASR"
mkdir -p "$MODEL_DIR"
# 文件名 和 最小字节数：小于它说明没下完（或下到的是错误页），重新下载
for item in encoder-epoch-99-avg-1.int8.onnx:150000000 decoder-epoch-99-avg-1.onnx:10000000 \
            joiner-epoch-99-avg-1.int8.onnx:2000000 tokens.txt:50000 bpe.model:100000; do
  name=${item%%:*}
  min=${item##*:}
  dest="$MODEL_DIR/$name"
  if [ -f "$dest" ] && [ "$(stat -f %z "$dest")" -ge "$min" ]; then
    echo "${name}：已有，跳过"
    continue
  fi
  ok=""
  for host in "${HF_ENDPOINT:-https://huggingface.co}" https://hf-mirror.com; do
    echo "${name} ← ${host}"
    if curl -fL --retry 2 --connect-timeout 15 --progress-bar "$host/csukuangfj2/$XASR/resolve/main/$name" -o "$dest.part" \
        && [ "$(stat -f %z "$dest.part")" -ge "$min" ]; then
      mv "$dest.part" "$dest"
      ok=1
      break
    fi
    rm -f "$dest.part"
  done
  [ -n "$ok" ] || die "语音识别模型 ${name} 下载失败。检查网络后重新运行本脚本（已下载的文件会跳过）。"
done

if grep -qE '^[[:space:]]+ASR:[[:space:]]*FunASR' "$CONFIG"; then
  warn "你的后端配置仍在用 FunASR。新版默认用 X-ASR（更准、更快、内存约 0.5GB），模型已经下好。"
  echo "  想换：把 ${DIR}/${CONFIG} 里 selected_module 下的 ASR: FunASR 改成 ASR: SherpaXASR，再重启后端。"
  echo "  继续用 FunASR 也可以：依赖已在 .venv 里；新建的 .venv 需要再装 requirements-macos-funasr.txt。"
fi

HOSTNAME_LOCAL="$(scutil --get LocalHostName 2>/dev/null || true)"
printf '\n\033[1;32m安装完成。\033[0m\n\n'
echo "回到网页第 4 步，在「电脑的地址」里填下面任意一个："
[ -n "$HOSTNAME_LOCAL" ] && printf '  \033[1m%s.local\033[0m   （推荐，IP 变了也能用）\n' "$HOSTNAME_LOCAL"
printf '  \033[1m%s\033[0m\n\n' "$IP"
echo "第一次启动时 macOS 如果询问是否允许 Python 接受传入连接，请选「允许」。"

if launchctl print "gui/$(id -u)/com.zongzhu.backend" >/dev/null 2>&1; then
  # 之前选了开机自启：更新代码后重启，让新代码生效，不再重新询问
  bash "$DIR/tools/autostart.sh" restart || warn "重启没有成功，运行 bash $DIR/tools/autostart.sh status 查看原因。"
  exit 0
fi

# 两种启动方式由用户自己选，没有默认项：不回答就一直问，没有终端可问时按手动处理，不替用户开自启。
echo
echo "选择后端的启动方式："
echo "  1) 开机自启：登录后自动在后台运行，退出会自动拉起，运行期间 Mac 不会因空闲睡眠"
echo "  2) 手动启动：需要时自己运行 $DIR/start.sh（在前台运行，关掉终端就停了）"
mode=""
while [ "$mode" != 1 ] && [ "$mode" != 2 ]; do
  if ! read -r -p "请输入 1 或 2：" mode 2>/dev/null </dev/tty; then
    mode=2
    echo
    echo "没有可交互的终端，先按手动启动处理。"
  fi
done

if [ "$mode" = 1 ]; then
  if bash "$DIR/tools/autostart.sh" enable; then
    echo "以后查看状态：bash $DIR/tools/autostart.sh status；取消自启：bash $DIR/tools/autostart.sh disable"
  else
    warn "自启没有设置成功，可以先前台运行 $DIR/start.sh，再运行 bash $DIR/tools/autostart.sh status 查看原因。"
  fi
  exit 0
fi

echo "以后启动后端：$DIR/start.sh"
echo "想改成开机自启：bash $DIR/tools/autostart.sh enable"
start=$(ask $'\n现在启动后端吗？[Y/n] ')
case "$start" in
  n|N|no|NO) ;;
  *) exec "$DIR/start.sh" ;;
esac
