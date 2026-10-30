#!/usr/bin/env bash
# 刷机前的只读备份：进刷机模式，读出 bootloader、tpl、boot0/1、system0/1。只执行 identify 和 mread（读），不写任何东西。
#
#   UPDATE=<update 工具路径> bash backup_readonly.sh [输出目录]
#
# 音箱用数据线直插电脑（不要经过扩展坞），先拔掉音箱电源，看到"等待设备"后再插电。
# 读完拔电再插，音箱正常开机。
# data 分区（0x9400000，UBIFS，存设置和登录信息）不在这里读：刷机不写 data；
# 刷完能 SSH 以后用 xiaoai-bridge/README.md 里的 dd / tar 命令备份。
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
UPDATE=${UPDATE:-$HERE/tools/update}
PYTHON=${PYTHON:-python3}
OUT=${1:-$HERE/../work/backup/$(date +%Y%m%d-%H%M%S)}
[ -x "$UPDATE" ] || { echo "找不到刷机工具：${UPDATE}（见 xiaoai-bridge/README.md）"; exit 1; }
mkdir -p "$OUT"
LOG="$OUT/backup.log"

# 名字 大小：OH2P 实测（/proc/mtd）
PARTS=(
  "system0 0x2800000"
  "system1 0x2800000"
  "boot0 0x600000"
  "boot1 0x600000"
  "bootloader 0x200000"
  "tpl 0x800000"
)

echo "备份目录：$OUT" | tee -a "$LOG"
echo "等待设备……现在插上音箱电源（${WAIT:-240} 秒）" | tee -a "$LOG"

# 刷机设备上电后只出现约 1 秒，反复起 update 进程抓不住；aml_wait.py 在同一进程里盯着并发 identify（只读）
if ! LIBUSB_DEBUG=4 "$PYTHON" -I "$HERE/aml_wait.py" "${WAIT:-240}" 2>/dev/null | tee -a "$LOG" | grep -q "identify 成功"; then
  echo "没有连上。拔掉音箱电源，重新运行脚本再插电。" | tee -a "$LOG"
  exit 1
fi
"$UPDATE" identify 7 >>"$LOG" 2>&1

for p in "${PARTS[@]}"; do
  set -- $p
  name=$1 size=$2
  echo "== 读 ${name}（${size} 字节）" | tee -a "$LOG"
  "$UPDATE" mread store "$name" normal "$size" "$OUT/$name.img" >>"$LOG" 2>&1
  if [ -s "$OUT/$name.img" ] && [ "$(wc -c < "$OUT/$name.img" | tr -d ' ')" -eq $((size)) ]; then
    echo "   成功" | tee -a "$LOG"
  else
    echo "   失败（详见 backup.log），继续下一个" | tee -a "$LOG"
  fi
done

(cd "$OUT" && (md5 -r *.img 2>/dev/null || md5sum *.img) > md5.txt)
echo "完成。现在拔掉音箱电源再插上，正常开机。结果：$OUT" | tee -a "$LOG"
