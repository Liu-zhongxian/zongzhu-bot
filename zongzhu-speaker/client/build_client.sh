#!/usr/bin/env bash
# 编译音箱上跑的 open-xiaoai Client（Rust，MIT），源码在同目录 client-rust/。
#
#   bash build_client.sh [输出目录]
#
# 源码来自 coderzc/open-xiaoai 14e1034：比原版多一处，连接时带 OPEN_XIAOAI_TOKEN（Bearer token），bridge 靠它认人。
# 音箱是 ARM 32 位硬浮点、glibc 2.25，所以目标是 armv7-unknown-linux-gnueabihf.2.25。
# 需要：rustup（加目标 armv7-unknown-linux-gnueabihf）、zig、cargo-zigbuild。
#   brew install rustup zig && rustup default stable && rustup target add armv7-unknown-linux-gnueabihf
#   cargo install --locked cargo-zigbuild
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET=armv7-unknown-linux-gnueabihf

OUT=${1:-$HERE/../work/client}
export PATH="/opt/homebrew/opt/rustup/bin:$HOME/.cargo/bin:$PATH"
for cmd in cargo zig cargo-zigbuild; do
  command -v "$cmd" >/dev/null || { echo "缺少 ${cmd}（见脚本开头）"; exit 1; }
done
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)

echo "== 编译（$TARGET.2.25）"
# 编译产物放在输出目录里，不弄脏源码目录
(cd "$HERE/client-rust" && CARGO_TARGET_DIR="$OUT/target" cargo zigbuild --release --locked --target "$TARGET.2.25")
cp "$OUT/target/$TARGET/release/client" "$OUT/client"
file "$OUT/client"
(shasum -a 256 "$OUT/client" 2>/dev/null || sha256sum "$OUT/client")
echo "完成：$OUT/client"
