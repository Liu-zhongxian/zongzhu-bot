#!/bin/bash
# 本机点歌（可选）：下载 go-music-dl 和 mpv 到仓库根目录的 local-music/（不进 Git）。
#
#   bash tools/local_music_setup.sh
#
# 版本和 SHA-256 写死在下面（取自各自 GitHub 发布页），校验不过就停下。
# 不用 Homebrew 装 mpv：brew 会连带装一份 ffmpeg，和后端用的 ffmpeg-full 冲突。
# 装完照提示把 local_music 一节写进 data/.config.yaml，再重启后端。
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEST="$ROOT/local-music"
GMD_VERSION=v1.1.3
MPV_VERSION=v0.41.0

say() { printf '\n==> %s\n' "$*"; }
fail() { printf '\n出错：%s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Darwin ] || fail "只支持 macOS。"
ARCH=$(uname -m)
MACOS=$(sw_vers -productVersion | cut -d. -f1)

case "$ARCH" in
  arm64)
    GMD_ASSET=go-music-dl_darwin_arm64.tar.gz
    GMD_SHA=15f684d095f84350847cc4f35db2353400480c22cb87c83b75dd36fbbf66ce02
    if [ "$MACOS" -ge 26 ]; then
      MPV_ASSET=mpv-$MPV_VERSION-macos-26-arm.zip; MPV_SHA=09820c0d84f6687446b84eb9df81fcf6a26ebe869cee58ea1857d7948cfb7c71
    elif [ "$MACOS" -ge 15 ]; then
      MPV_ASSET=mpv-$MPV_VERSION-macos-15-arm.zip; MPV_SHA=489cf6a54f57c54f86ad8d7cedaf5bb26848770d58dc059021214e2f689ee799
    elif [ "$MACOS" -ge 14 ]; then
      MPV_ASSET=mpv-$MPV_VERSION-macos-14-arm.zip; MPV_SHA=5c96f9b21355fc0a11d2e2161ad65f33031070e9fb3f6bd9865fb459b94587e6
    else
      fail "mpv 官方包需要 macOS 14 或更高版本。"
    fi
    ;;
  x86_64)
    GMD_ASSET=go-music-dl_darwin_amd64.tar.gz
    GMD_SHA=9fcf115cf750899fb2dcca60dd95dc86a2a4806071d4041aea2a14ef0dde2e10
    [ "$MACOS" -ge 15 ] || fail "mpv 官方 Intel 包需要 macOS 15 或更高版本。"
    MPV_ASSET=mpv-$MPV_VERSION-macos-15-intel.zip; MPV_SHA=41003617ab4f7784394b5ddea7ce51b3e0838e8cfc8166ad1a378b2eda3b583c
    ;;
  *) fail "不认识的处理器架构：${ARCH}" ;;
esac

fetch() {  # 下载并核对 SHA-256：fetch <网址> <保存到> <sha256>
  curl -fL --progress-bar --retry 3 -o "$2" "$1" || fail "下载失败：$1"
  [ "$(shasum -a 256 "$2" | cut -d' ' -f1)" = "$3" ] || { rm -f "$2"; fail "校验不一致，已删除：$(basename "$2")"; }
}

mkdir -p "$DEST/go-music-dl" "$DEST/mpv"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

say "下载 go-music-dl ${GMD_VERSION}（${GMD_ASSET}）"
fetch "https://github.com/guohuiyuan/go-music-dl/releases/download/$GMD_VERSION/$GMD_ASSET" "$TMP/gmd.tar.gz" "$GMD_SHA"
tar xzf "$TMP/gmd.tar.gz" -C "$DEST/go-music-dl" music-dl LICENSE README.md
chmod +x "$DEST/go-music-dl/music-dl"

say "下载 mpv ${MPV_VERSION}（${MPV_ASSET}）"
fetch "https://github.com/mpv-player/mpv/releases/download/$MPV_VERSION/$MPV_ASSET" "$TMP/mpv.zip" "$MPV_SHA"
unzip -q -o "$TMP/mpv.zip" -d "$TMP/mpv"
rm -rf "$DEST/mpv/mpv.app"
tar xzf "$TMP/mpv/mpv.tar.gz" -C "$DEST/mpv"
"$DEST/mpv/mpv.app/Contents/MacOS/mpv" --version | head -1

say "装好了。把下面这一节加进 xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml，再重启后端："
cat <<'EOF'

local_music:
  enabled: true
  go_music_dl: ../../../local-music/go-music-dl/music-dl
  port: 18080
  mpv: ../../../local-music/mpv/mpv.app/Contents/MacOS/mpv
  socket: ../../../local-music/mpv.sock

EOF
echo "想听网易云会员歌曲：后端启动后打开 http://localhost:18080/music/setup 建管理员（token 在 local-music/go-music-dl/service.log），"
echo "再在设置里扫码登录。注意 go-music-dl 会监听所有网卡，同一局域网的设备都能访问这个端口。"
