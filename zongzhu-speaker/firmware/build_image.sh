#!/usr/bin/env bash
# 用小米官方固件包做补丁版系统镜像。只在电脑上做，不碰音箱。
#
#   bash build_image.sh <官方 mico_all_*.bin> [输出目录]
#
# 补丁是同目录 patches/ 里的 4 个，来自 open-xiaoai（packages/client-patch/patches，MIT，见 ../LICENSE.open-xiaoai）：
#   开 SSH（dropbear）、设 root 密码、串口给 shell、PAM 改回普通认证、禁 OTA、开机跑 /data/init.sh。
# root 密码运行时输入（不回显），镜像里只存 md5crypt 密码串（随机 8 位盐）；也可以用环境变量
# SPEAKER_ROOT_PASSWORD 传入。
#
# 输出目录里：
#   root-patched.squashfs  补丁版系统，写进 system0 或 system1
#   boot.img.encrypt       官方内核原样，写进同一边的 boot0 或 boot1
#   extracted/             官方包解开的各段
# 需要：python3、patch、openssl，以及 Homebrew 的 squashfs（unsquashfs、mksquashfs）。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PATCHES="$HERE/patches"
SYSTEM_MAX=$((0x2800000))  # system0 / system1 分区大小

[ $# -ge 1 ] || { sed -n '2,4p' "$0"; exit 1; }
BIN=$1
OUT=${2:-$HERE/../work/build}
for cmd in python3 patch openssl unsquashfs mksquashfs; do
  command -v "$cmd" >/dev/null || { echo "缺少 $cmd"; exit 1; }
done
[ ! -e "$OUT" ] || { echo "$OUT 已存在，换一个输出目录或先删掉"; exit 1; }

# macOS 默认 umask 022 会在解包时去掉组写权限，镜像就和官方的不一样了
umask 0
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)

echo "== 解开官方包（校验 CRC32 和 MD5）"
python3 -I "$HERE/mico_extract.py" "$BIN" "$OUT/extracted"

if [ -z "${SPEAKER_ROOT_PASSWORD:-}" ]; then
  read -rsp "音箱 root 密码（SSH 登录用）：" SPEAKER_ROOT_PASSWORD; echo
  read -rsp "再输一次：" again; echo
  [ "$SPEAKER_ROOT_PASSWORD" = "$again" ] || { echo "两次不一样"; exit 1; }
fi
[ -n "$SPEAKER_ROOT_PASSWORD" ] || { echo "密码不能为空"; exit 1; }
# md5crypt 的盐最多 8 个字符（不用 tr </dev/urandom | head：pipefail 下 tr 收到 SIGPIPE 会让脚本退出）
SALT=$(openssl rand -base64 12 | tr -dc 'A-Za-z0-9' | cut -c1-8)
HASH=$(printf '%s' "$SPEAKER_ROOT_PASSWORD" | openssl passwd -1 -salt "$SALT" -stdin)

echo "== 解开官方系统，打补丁"
unsquashfs -q -no-xattrs -ignore-errors -d "$OUT/rootfs" "$OUT/extracted/root.squashfs" >/dev/null 2>&1 || true
[ -f "$OUT/rootfs/etc/shadow" ] || { echo "解开 root.squashfs 失败"; exit 1; }
cp -a "$OUT/rootfs" "$OUT/rootfs-patched"
for p in "$PATCHES"/0*.patch; do
  sed "s|{SSH_PASSWORD}|$HASH|g" "$p" | (cd "$OUT/rootfs-patched" && patch -p1 -s --no-backup-if-mismatch)
  echo "   $(basename "$p")"
done

echo "== 打包"
# 参数同 open-xiaoai client-patch；/dev/console 普通用户解不出来，用 -p 补上
mksquashfs "$OUT/rootfs-patched" "$OUT/root-patched.squashfs" -comp xz -b 131072 -noappend -all-root \
  -always-use-fragments -no-xattrs -no-exports -p "dev/console c 600 0 0 5 1" -quiet -no-progress
size=$(wc -c < "$OUT/root-patched.squashfs" | tr -d ' ')
[ "$size" -le "$SYSTEM_MAX" ] || { echo "镜像 $size 字节，超过分区大小 $SYSTEM_MAX"; exit 1; }

echo "== 核对：和官方系统比，只能有补丁改的 8 个文件不同"
python3 -I "$HERE/sqfs_list_diff.py" "$OUT/extracted/root.squashfs" "$OUT/root-patched.squashfs" > "$OUT/check-listing.txt"
unsquashfs -q -no-xattrs -ignore-errors -d "$OUT/check" "$OUT/root-patched.squashfs" >/dev/null 2>&1 || true
python3 -I "$HERE/tree_diff.py" "$OUT/rootfs" "$OUT/check" > "$OUT/check-files.txt"
cat "$OUT/check-files.txt"
expected=$(printf '%s\n' bin/flash.sh bin/ota etc/inittab etc/init.d/dropbear etc/init.d/wireless \
  etc/pam.d/common-auth etc/rc.local etc/shadow | LC_ALL=C sort)
got=$(awk '$1 == "改动" {print $2} $1 != "改动" {print "意外：" $0}' "$OUT/check-files.txt" | LC_ALL=C sort)
[ "$got" = "$expected" ] || { echo "改动的文件和预期不一样，不要刷这个镜像"; exit 1; }
grep -q "^条目数 \([0-9]*\) -> \1$" "$OUT/check-listing.txt" || { echo "条目数变了，不要刷这个镜像"; cat "$OUT/check-listing.txt"; exit 1; }
line=$(head -1 "$OUT/check/etc/shadow" | cut -d: -f2)
[ "$(printf '%s' "$SPEAKER_ROOT_PASSWORD" | openssl passwd -1 -salt "$(echo "$line" | cut -d'$' -f3)" -stdin)" = "$line" ] \
  || { echo "shadow 里的密码串验证不过"; exit 1; }

cp "$OUT/extracted/boot.img.encrypt" "$OUT/boot.img.encrypt"
rm -rf "$OUT/rootfs" "$OUT/rootfs-patched" "$OUT/check"
echo "完成（$size 字节，上限 ${SYSTEM_MAX}）："
(cd "$OUT" && md5 -r root-patched.squashfs boot.img.encrypt 2>/dev/null || md5sum root-patched.squashfs boot.img.encrypt)
