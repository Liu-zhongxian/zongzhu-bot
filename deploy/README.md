# 服务器部署

把后端部署到一台有公网 IP 的 Linux 服务器上，板子在任何网络都能用，电脑可以关机。已在 Ubuntu 22.04（4 核 6GB）上验证。

前提：一个解析到服务器的子域名（Cloudflare 用户要关掉代理，用灰色云朵）；服务器放行 80、443。

| 文件 | 放到哪里 | 作用 |
| --- | --- | --- |
| `Caddyfile` | `/etc/caddy/Caddyfile` | 自动申请 HTTPS 证书；只放行板子的 WebSocket、OTA 和 Bot 回传三个路径，其余 404 |
| `zongzhu.service` | `/etc/systemd/system/` | 用独立的 `zongzhu` 用户运行后端，开机自启，崩溃自动重启 |
| `server.config.yaml` | `/opt/zongzhu/app/data/.config.yaml` | 后端只监听 127.0.0.1；开启设备白名单 |

## 步骤（以 root 执行）

```sh
apt-get install -y ffmpeg libopus0 python3.10-venv caddy   # Caddy 需先按官网加软件源
useradd --system --home /opt/zongzhu --shell /usr/sbin/nologin zongzhu
mkdir -p /opt/zongzhu/app /opt/zongzhu/private/bot-replies
# 把仓库里的 xiaozhi-esp32-server/main/xiaozhi-server/ 复制到 /opt/zongzhu/app/
cd /opt/zongzhu && python3.10 -m venv venv
venv/bin/pip install torch==2.2.2 torchaudio==2.2.2 --index-url https://download.pytorch.org/whl/cpu
venv/bin/pip install -r /path/to/requirements-macos.txt
grep -vE "^(torch|torchaudio)==" /path/to/requirements-macos-funasr.txt > /tmp/req.txt && venv/bin/pip install -r /tmp/req.txt
cd app && ../venv/bin/python -c "from modelscope import snapshot_download; snapshot_download('iic/SenseVoiceSmall', local_dir='models/SenseVoiceSmall')"
chown -R zongzhu:zongzhu /opt/zongzhu && chmod 700 /opt/zongzhu/private
systemctl enable --now zongzhu && systemctl reload caddy
ufw allow 80/tcp && ufw allow 443/tcp
```

PyTorch 用 CPU 版，避免下载约 2GB 的 CUDA 依赖。服务器上用的是 FunASR（`server.config.yaml` 里 `ASR: FunASR`），所以要另装 `requirements-macos-funasr.txt`；本机默认的 X-ASR 还没在服务器上验证过。

`/opt/zongzhu/private/grok-bot-webhook.json` 按 `examples/grok-bot-webhook.example.json` 填写，其中：

- `reply_dir`：`/opt/zongzhu/private/bot-replies`
- `reply_url`：`https://你的子域名/bot/reply`。填了它，Bot 就用 HTTPS 把回复 POST 回来，不再需要写本机文件

## 切换板子

板子配网页的 OTA 地址改成 `https://你的子域名/xiaozhi/ota/`。要切回本机后端，把 OTA 地址改回电脑的局域网地址即可。

## 检查

```sh
systemctl status zongzhu
journalctl -u zongzhu -f
curl -s -o /dev/null -w "%{http_code}\n" https://你的子域名/mcp/vision/explain   # 应为 404
```
