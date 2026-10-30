#!/usr/bin/env bash
# 把补丁版系统写进音箱的一边（A/B 两边中的 SLOT），另一边不动，当退路。
#   1. 官方内核（boot.img.encrypt）写进 boot<SLOT>，读回来逐字节核对
#   2. 补丁版系统（root-patched.squashfs）写进 system<SLOT>，读回来逐字节核对
#   3. 前两步都核对通过，才改启动参数：boot_part=boot<SLOT>（可选 bootdelay），saveenv
# 任何一步失败就停下，不改启动参数，音箱照旧从原来那一边启动。
#
#   SLOT=0 UPDATE=<update 工具路径> [BOOTDELAY=15] bash flash_slot.sh <build_image.sh 的输出目录>
#
# SLOT 选**现在没在用**的那一边（xiaoai-bridge/README.md 第 4 步写了怎么判断）。内核和系统必须是同一个官方包里的。
# 音箱用数据线直插电脑，先拔掉音箱电源，看到"等待设备"后再插电。
# 已经写好 boot、只想重写 system 时加 SKIP_BOOT=1。
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
UPDATE=${UPDATE:-$HERE/tools/update}
PYTHON=${PYTHON:-python3}
SLOT=${SLOT:-}
[ "$SLOT" = 0 ] || [ "$SLOT" = 1 ] || { echo "要指定 SLOT=0 或 SLOT=1"; exit 1; }
[ $# -ge 1 ] || { echo "用法：SLOT=0 bash flash_slot.sh <build_image.sh 的输出目录>"; exit 1; }
KERNEL="$1/boot.img.encrypt"
ROOTFS="$1/root-patched.squashfs"
OUT="$1/flash-$(date +%Y%m%d-%H%M%S)"
[ -x "$UPDATE" ] || { echo "找不到刷机工具：${UPDATE}（见 xiaoai-bridge/README.md）"; exit 1; }
[ -f "$KERNEL" ] && [ -f "$ROOTFS" ] || { echo "找不到 $KERNEL 或 $ROOTFS"; exit 1; }
mkdir -p "$OUT"
LOG="$OUT/flash.log"

say() { echo "$*" | tee -a "$LOG"; }

# 写进去以后读回来，和源文件逐字节比（分区比文件大，只比文件那么长）
write_and_verify() {
  local part=$1 file=$2 readsize=$3
  local n
  for n in 1 2; do
    say "== 第 $n 次：写 $(basename "$file") -> $part"
    "$UPDATE" partition "$part" "$file" >>"$LOG" 2>&1
    "$UPDATE" mread store "$part" normal "$readsize" "$OUT/$part.readback" >>"$LOG" 2>&1
    # macOS 的 cmp -n 遇到读回文件比源文件长会报 EOF，所以先截成同样长度再比
    if head -c "$(wc -c < "$file" | tr -d ' ')" "$OUT/$part.readback" | cmp -s - "$file"; then
      say "   读回核对一致"
      return 0
    fi
    say "   读回核对不一致（详见 flash.log）"
  done
  return 1
}

say "写入 boot$SLOT / system${SLOT}；另一边不动"
say "等待设备……插上音箱电源（${WAIT:-240} 秒）"
if ! LIBUSB_DEBUG=4 "$PYTHON" -I "$HERE/aml_wait.py" "${WAIT:-240}" 2>/dev/null | tee -a "$LOG" | grep -q "identify 成功"; then
  say "没有连上，什么都没写。"
  exit 1
fi
"$UPDATE" identify 7 >>"$LOG" 2>&1

if [ -n "${SKIP_BOOT:-}" ]; then
  say "== 跳过 boot${SLOT}（上一轮已写入并核对过）"
else
  write_and_verify "boot$SLOT" "$KERNEL" 0x600000 || { say "boot$SLOT 写入失败，停下。启动参数没改。"; exit 1; }
fi
write_and_verify "system$SLOT" "$ROOTFS" 0x2800000 || { say "system$SLOT 写入失败，停下。启动参数没改。"; exit 1; }

say "== 改启动参数"
if [ -n "${BOOTDELAY:-}" ]; then
  "$UPDATE" bulkcmd "setenv bootdelay $BOOTDELAY" 2>&1 | tee -a "$LOG"
fi
"$UPDATE" bulkcmd "setenv boot_part boot$SLOT" 2>&1 | tee -a "$LOG"
"$UPDATE" bulkcmd "saveenv" 2>&1 | tee -a "$LOG"
if tail -n 20 "$LOG" | grep -q "ERR\|failed"; then
  say "启动参数可能没改成功（见上面的输出）。boot$SLOT/system$SLOT 已经写好，可以重新进刷机模式只做这一步。"
  exit 2
fi
say "完成。拔掉音箱电源再插上，等它开机后用 SSH 检查。"
