#!/usr/bin/env bash
# 把 Client 和开机脚本装到刷好补丁固件的音箱上（通过 SSH，root 密码是 build_image.sh 时设的）。
#
#   bash install_client.sh <音箱 IP> <bridge 地址，如 ws://192.168.1.10:4399> <token 文件> [client 文件]
#
# 写入音箱：
#   /data/open-xiaoai/client      Client 程序（默认用 build_client.sh 的输出）
#   /data/open-xiaoai/server.txt  bridge 地址
#   /data/open-xiaoai/token.txt   连接 token（和 bridge 的 OPEN_XIAOAI_TOKEN 相同，权限 600）
#   /data/init.sh                 开机脚本（补丁固件的 /etc/rc.local 会在后台调用它）
# 只写这几个文件；已经在跑的 Client 会被停掉，开机脚本 5 秒后用新的重新启动。
# 停用：SSH 进音箱 touch /data/open-xiaoai/disabled 后重启；撤销：删掉 /data/init.sh 和 /data/open-xiaoai/。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
[ $# -ge 3 ] || { sed -n '2,4p' "$0"; exit 1; }
SPEAKER=$1 SERVER=$2 TOKEN_FILE=$3
CLIENT=${4:-$HERE/../work/client/client}
[ -f "$CLIENT" ] || { echo "找不到 ${CLIENT}（先运行 build_client.sh）"; exit 1; }
[ -s "$TOKEN_FILE" ] || { echo "token 文件是空的：$TOKEN_FILE"; exit 1; }
case "$SERVER" in ws://*) ;; *) echo "bridge 地址要以 ws:// 开头"; exit 1 ;; esac

# 音箱的 dropbear 比较老，新版 OpenSSH 要打开 ssh-rsa；共用一条连接，密码只输一次
CTL=$(mktemp -u "${TMPDIR:-/tmp}/xiaoai-ssh.XXXXXX")
SSH=(ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa -o IPQoS=none
     -o ControlMaster=auto -o ControlPath="$CTL" -o ControlPersist=60 "root@$SPEAKER")
trap '"${SSH[@]}" -O exit >/dev/null 2>&1 || true' EXIT

echo "== 连接音箱（输入 root 密码）"
"${SSH[@]}" 'mkdir -p /data/open-xiaoai && cat /usr/share/mico/version | grep -E "option (ROM|HARDWARE)"'

echo "== 写入文件"
# 先写临时文件再改名：Client 正在跑时直接覆盖会报 "Text file busy"
"${SSH[@]}" 'cat > /data/open-xiaoai/client.new && chmod 755 /data/open-xiaoai/client.new && mv /data/open-xiaoai/client.new /data/open-xiaoai/client' < "$CLIENT"
printf '%s\n' "$SERVER" | "${SSH[@]}" 'cat > /data/open-xiaoai/server.txt'
"${SSH[@]}" 'umask 077; cat > /data/open-xiaoai/token.txt; chmod 600 /data/open-xiaoai/token.txt' < "$TOKEN_FILE"
"${SSH[@]}" 'cat > /data/init.sh.new && chmod 755 /data/init.sh.new && mv /data/init.sh.new /data/init.sh' < "$HERE/init.sh"

echo "== 核对"
local_sum=$( (shasum -a 256 "$CLIENT" 2>/dev/null || sha256sum "$CLIENT") | cut -d' ' -f1)
remote_sum=$("${SSH[@]}" 'sha256sum /data/open-xiaoai/client' | cut -d' ' -f1)
[ "$local_sum" = "$remote_sum" ] || { echo "Client 校验不一致"; exit 1; }
"${SSH[@]}" 'sh -n /data/init.sh && cat /data/open-xiaoai/server.txt && ls -l /data/init.sh /data/open-xiaoai'

echo "== 启动"
# 开机脚本在跑就只停 Client，它 5 秒后会用新程序重启；没在跑（第一次装）就在后台启动开机脚本
"${SSH[@]}" 'if ps | grep -v grep | grep -q "sh /data/init.sh"; then killall client 2>/dev/null; echo "已让开机脚本重启 Client"; else (sh /data/init.sh >/dev/null 2>&1 &); echo "已启动开机脚本（约 20 秒后连 bridge）"; fi'
echo "完成。日志在音箱的 /tmp/open-xiaoai.log。"
