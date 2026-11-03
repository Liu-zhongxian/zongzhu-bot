#!/bin/sh
# 音箱开机脚本，放在 /data/init.sh，由补丁固件的 /etc/rc.local 在后台调用。
# 启动 open-xiaoai Client，连 server.txt 里的地址；Client 退出就 5 秒后重启。
# 不联网下载任何东西；不等外网；出任何问题只影响 Client，不影响小爱本身。
# 临时停用：touch /data/open-xiaoai/disabled（删掉这个文件再重启就恢复）

WORK=/data/open-xiaoai
LOG=/tmp/open-xiaoai.log

[ -x "$WORK/client" ] || exit 0
SERVER=$(cat "$WORK/server.txt" 2>/dev/null)
[ -n "$SERVER" ] || exit 0
[ -f "$WORK/token.txt" ] && OPEN_XIAOAI_TOKEN=$(cat "$WORK/token.txt") && export OPEN_XIAOAI_TOKEN

# 等小爱自己的服务先起来
sleep 20

while [ ! -f "$WORK/disabled" ]; do
    echo "$(date '+%F %T') 启动 client -> $SERVER" > "$LOG"
    "$WORK/client" "$SERVER" >> "$LOG" 2>&1
    echo "$(date '+%F %T') client 退出，代码 $?" >> "$LOG"
    sleep 5
done
