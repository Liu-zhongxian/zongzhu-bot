#!/bin/bash
# 宗主后端开机自启（macOS launchd，用户级）。
#
# 用法：bash tools/autostart.sh enable|disable|restart|status
#   enable   登录后自动启动后端，进程退出后自动拉起；马上启动并等服务可访问
#   disable  停止后台服务，取消开机自启
#   restart  重启后台服务（更新代码、改配置后）
#   status   自检：自启、端口、OTA、配置里的 IP、Webhook 配置。有异常时退出码为 1
#
# launchd 启动的是 ~/Applications/ZongzhuBackend.app（由 tools/launcher.c 编译），再由它运行
# start.sh：仓库在“桌面”“文稿”等受保护目录时，macOS 才会弹窗询问是否允许“宗主后端”访问。
# 后端运行期间用 caffeinate -i 防止 Mac 空闲睡眠（合盖仍会睡眠）。
# 日志：logs/backend.stdout.log、logs/backend.stderr.log。
# 一个用户只有一份自启文件，指向最后一次运行 enable 的那份安装。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SERVER="$ROOT/xiaozhi-esp32-server/main/xiaozhi-server"
CONFIG="$SERVER/data/.config.yaml"
LABEL="com.zongzhu.backend"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
OUT_LOG="$ROOT/logs/backend.stdout.log"
ERR_LOG="$ROOT/logs/backend.stderr.log"
APP="$HOME/Applications/ZongzhuBackend.app"
APP_BIN="$APP/Contents/MacOS/zongzhu-backend"

ok()   { printf '  \033[32m正常\033[0m  %s\n' "$*"; }
bad()  { printf '  \033[31m异常\033[0m  %s\n' "$*"; FAILED=1; }
note() { printf '  \033[33m提示\033[0m  %s\n' "$*"; }
die()  { printf '\033[31m出错：%s\033[0m\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Darwin ] || die "只支持 macOS。"

# 配置里某个键的值（只取第一处，去掉引号和行尾注释）
config_value() {
  [ -f "$CONFIG" ] || return 0
  sed -n "s/^[[:space:]]*$1:[[:space:]]*//p" "$CONFIG" | head -n 1 | sed 's/[[:space:]]#.*//; s/^["'\'']//; s/["'\'']$//'
}
http_port() { local p; p="$(config_value http_port)"; echo "${p:-8003}"; }
ws_port()   { local p; p="$(config_value port)"; echo "${p:-8000}"; }
listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
ota_up()    { curl -s -m 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$1/xiaozhi/ota/" 2>/dev/null | grep -q '^200$'; }
loaded()    { launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; }
# 自启文件指向的安装目录（启动器的第一个参数）
owner()     { /usr/libexec/PlistBuddy -c 'Print :ProgramArguments:1' "$PLIST" 2>/dev/null || true; }
mine()      { [ -f "$PLIST" ] && [ "$(owner)" = "$ROOT" ]; }
lan_ip() {
  local iface
  iface="$(route -n get default 2>/dev/null | awk '/interface:/ {print $2}')"
  ipconfig getifaddr "${iface:-en0}" 2>/dev/null || ipconfig getifaddr en0 2>/dev/null || true
}

# 编译启动器应用。源码不变时不重编，系统已给的授权就一直有效
build_app() {
  local src
  src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/launcher.c"
  [ -f "$src" ] || die "没有找到 ${src}。"
  if [ -x "$APP_BIN" ] && [ "$APP_BIN" -nt "$src" ]; then
    return 0
  fi
  command -v clang >/dev/null 2>&1 || die "需要 clang 编译启动器。运行 xcode-select --install 安装命令行工具后重试。"
  mkdir -p "$APP/Contents/MacOS"
  clang -O2 -Wall -o "$APP_BIN" "$src"
  cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>$LABEL</string>
  <key>CFBundleName</key><string>宗主后端</string>
  <key>CFBundleDisplayName</key><string>宗主后端</string>
  <key>CFBundleExecutable</key><string>zongzhu-backend</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><true/>
  <key>NSDesktopFolderUsageDescription</key><string>宗主后端要读取桌面上的项目目录来运行语音后端。</string>
  <key>NSDocumentsFolderUsageDescription</key><string>宗主后端要读取文稿里的项目目录来运行语音后端。</string>
  <key>NSDownloadsFolderUsageDescription</key><string>宗主后端要读取下载里的项目目录来运行语音后端。</string>
</dict>
</plist>
EOF
  codesign --force --sign - "$APP" >/dev/null 2>&1 || true
  echo "已生成启动器：${APP}"
}

xml_escape() { local s="${1//&/&amp;}"; s="${s//</&lt;}"; printf '%s' "${s//>/&gt;}"; }

write_plist() {
  local root
  root="$(xml_escape "$ROOT")"
  mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml_escape "$APP_BIN")</string>
    <string>$root</string>
  </array>
  <key>WorkingDirectory</key><string>$root</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$(xml_escape "$OUT_LOG")</string>
  <key>StandardErrorPath</key><string>$(xml_escape "$ERR_LOG")</string>
</dict>
</plist>
EOF
}

# 等 OTA 接口能访问（启动时要加载语音识别模型，一般十几秒；第一次还要等用户点授权）
wait_ready() {
  local port i
  port="$(http_port)"
  echo "等待服务启动 ...（如果弹出“宗主后端”想访问文件夹的窗口，请点“允许”）"
  for ((i = 0; i < 90; i++)); do
    if ota_up "$port"; then
      echo "服务已启动：http://127.0.0.1:$port/xiaozhi/ota/"
      return 0
    fi
    sleep 2
  done
  printf '\033[31m服务 180 秒内没有启动成功。\033[0m 最近的报错（%s）：\n' "$ERR_LOG" >&2
  tail -n 15 "$ERR_LOG" >&2 2>/dev/null || true
  if grep -q 'Operation not permitted' "$ERR_LOG" 2>/dev/null; then
    echo "macOS 没有允许“宗主后端”读取这个目录（${ROOT}）。" >&2
    echo "到 系统设置 → 隐私与安全性 → 文件与文件夹 → 宗主后端，打开对应的文件夹，然后运行 restart。" >&2
  fi
  return 1
}

enable() {
  [ -x "$ROOT/.venv/bin/python" ] || die "没有找到 $ROOT/.venv，请先按 README 安装后端。"
  [ -f "$CONFIG" ] || die "没有找到后端配置 ${CONFIG}。"
  if ! loaded && { listening "$(http_port)" || listening "$(ws_port)"; }; then
    die "端口 $(ws_port)/$(http_port) 已被占用，多半是前台运行的 start.sh。先在那个终端按 Ctrl-C 停掉，再运行 enable。"
  fi
  if [ -f "$PLIST" ] && ! mine; then
    echo "自启原来指向 $(owner)，改为指向这里：$ROOT"
  fi
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  build_app
  mkdir -p "$ROOT/logs"
  : > "$ERR_LOG"
  write_plist
  launchctl bootstrap "$DOMAIN" "$PLIST"
  echo "已开启开机自启（${PLIST}）。"
  wait_ready
}

disable() {
  if [ -f "$PLIST" ] && ! mine; then
    die "自启指向另一份安装（$(owner)），没有改动。请在那份安装里运行 disable。"
  fi
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "已停止后台服务，并取消开机自启。"
}

restart() {
  mine || die "这份安装没有开启自启。先运行 enable。"
  if loaded; then
    launchctl kickstart -k "$DOMAIN/$LABEL"
  else
    launchctl bootstrap "$DOMAIN" "$PLIST"
  fi
  wait_ready
}

status() {
  FAILED=0
  local port wsp url host ip local_name webhook mode
  port="$(http_port)"; wsp="$(ws_port)"
  echo "宗主后端自检（${ROOT}）"

  if mine; then
    ok "开机自启已开启"
  elif [ -f "$PLIST" ]; then
    bad "开机自启指向另一份安装：$(owner)"
  else
    note "没有开启开机自启（bash tools/autostart.sh enable）"
  fi
  if loaded; then ok "后台服务已加载"; elif mine; then bad "自启文件在，但后台服务没有加载"; fi

  listening "$wsp" && ok "WebSocket 端口 $wsp 在监听" || bad "WebSocket 端口 $wsp 没有监听"
  listening "$port" && ok "HTTP 端口 $port 在监听" || bad "HTTP 端口 $port 没有监听"
  ota_up "$port" && ok "OTA 接口返回 200" || bad "OTA 接口不可访问：http://127.0.0.1:$port/xiaozhi/ota/"

  url="$(config_value websocket)"
  host="$(printf '%s' "$url" | sed -n 's#^wss*://\([^:/]*\).*#\1#p')"
  ip="$(lan_ip)"
  local_name="$(scutil --get LocalHostName 2>/dev/null || true)"
  if [ -z "$url" ]; then
    bad "配置里没有 server.websocket 地址"
  elif [ "$host" = "$ip" ] || [ "$host" = "$local_name.local" ]; then
    ok "配置的 WebSocket 地址指向本机（${host}）"
  else
    bad "配置的 WebSocket 地址是 ${host}，本机当前局域网 IP 是 ${ip:-未知}，板子会连不上。请改 $CONFIG"
  fi

  webhook="$(config_value config_file)"
  if [ -z "$webhook" ]; then
    bad "配置里没有 grok_bot.config_file"
  elif [ ! -f "$webhook" ]; then
    bad "Webhook 配置文件不存在：$webhook"
  else
    mode="$(stat -f %Lp "$webhook")"
    [ "$mode" = 600 ] && ok "Webhook 配置存在，权限 600" || bad "Webhook 配置权限是 ${mode}，应为 600：chmod 600 \"$webhook\""
  fi

  if [ -s "$ERR_LOG" ] && grep -q 'Operation not permitted' "$ERR_LOG" 2>/dev/null; then
    note "${ERR_LOG} 里有 Operation not permitted：到 系统设置 → 隐私与安全性 → 文件与文件夹 → 宗主后端 打开对应文件夹，再运行 restart"
  fi
  return "$FAILED"
}

case "${1:-}" in
  enable) enable ;;
  disable) disable ;;
  restart) restart ;;
  status) status ;;
  *) echo "用法：bash $0 enable|disable|restart|status"; exit 2 ;;
esac
