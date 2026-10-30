#!/usr/bin/env bash
# 编译音箱上跑的 open-xiaoai Client（Rust，MIT），按固定提交下载源码。
#
#   bash build_client.sh [输出目录]
#
# 用 coderzc/open-xiaoai 的 fork：比原版多一处，连接时带 OPEN_XIAOAI_TOKEN（Bearer token），bridge 靠它认人。
# 音箱是 ARM 32 位硬浮点、glibc 2.25，所以目标是 armv7-unknown-linux-gnueabihf.2.25。
# 需要：git、rustup（加目标 armv7-unknown-linux-gnueabihf）、zig、cargo-zigbuild。
#   brew install rustup zig && rustup default stable && rustup target add armv7-unknown-linux-gnueabihf
#   cargo install --locked cargo-zigbuild
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
OPEN_XIAOAI_REPO=https://github.com/coderzc/open-xiaoai.git
OPEN_XIAOAI_REV=14e1034ba75698be7d3f331b9822b7043deaf032
TARGET=armv7-unknown-linux-gnueabihf

OUT=${1:-$HERE/../work/client}
export PATH="/opt/homebrew/opt/rustup/bin:$HOME/.cargo/bin:$PATH"
for cmd in git cargo zig cargo-zigbuild; do
  command -v "$cmd" >/dev/null || { echo "缺少 ${cmd}（见脚本开头）"; exit 1; }
done
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
SRC="$OUT/open-xiaoai"

if [ ! -d "$SRC/.git" ]; then
  git init -q "$SRC"
fi
for try in 1 2 3; do
  git -C "$SRC" fetch -q --depth 1 "$OPEN_XIAOAI_REPO" "$OPEN_XIAOAI_REV" && break
  [ "$try" = 3 ] && { echo "连不上 GitHub，稍后重试"; exit 1; }
  sleep 3
done
git -C "$SRC" checkout -q FETCH_HEAD

echo "== 编译（${OPEN_XIAOAI_REV:0:7}，$TARGET.2.25）"
(cd "$SRC/packages/client-rust" && cargo zigbuild --release --locked --target "$TARGET.2.25")
cp "$SRC/packages/client-rust/target/$TARGET/release/client" "$OUT/client"
file "$OUT/client"
(shasum -a 256 "$OUT/client" 2>/dev/null || sha256sum "$OUT/client")
echo "完成：$OUT/client"
