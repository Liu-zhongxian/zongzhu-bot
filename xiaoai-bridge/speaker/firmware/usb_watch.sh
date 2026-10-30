#!/usr/bin/env bash
# 诊断用：连续记录 USB 设备的出现/消失（厂商 ID:产品 ID 名字），看音箱上电时有没有出现晶晨刷机设备（1b8e:c003）。只读。
# 用法：bash usb_watch.sh <秒数> <日志文件>
dur=${1:-60}; log=${2:-/dev/stdout}; end=$((SECONDS + dur)); prev=""
while [ $SECONDS -lt $end ]; do
  cur=$(ioreg -p IOUSB -l -w0 | awk -F' = ' '/"idVendor"/{v=$2} /"idProduct"/{p=$2} /"USB Product Name"/{n=$2} /^[ |]*}/{if(v!=""){printf "%04x:%04x %s\n", v, p, n; v=""}}' | sort -u)
  if [ "$cur" != "$prev" ]; then
    { echo "== $(date +%H:%M:%S.%N 2>/dev/null || date +%T)"; diff <(echo "$prev") <(echo "$cur") | grep '^[<>]'; } >> "$log"
    prev=$cur
  fi
done
