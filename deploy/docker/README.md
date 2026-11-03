# 用 Docker 运行后端

把宗主后端放进容器里运行，不用在电脑上装 Python 环境。板子、小米音箱、网关页面、Bot 回复都和直接在 Mac 上运行一样。2026-11-03 在 Mac（Docker Desktop 29.9，Apple 芯片）上实测：音箱唤醒、对话、等 Bot 回复、打断后接着说都正常。

## 容器里用不了的

| 功能 | 原因 | 怎么办 |
| --- | --- | --- |
| 本机点歌 | 歌是在电脑上用 mpv 放出声音，容器里没有声卡 | 配置里 `local_music.enabled: false`；要点歌就直接在 Mac 上运行后端 |
| 开机自启（`tools/autostart.sh`） | 它用的是 macOS 的 launchd | compose 里已写 `restart: unless-stopped`：Docker 起来容器就起来；Docker Desktop 要在设置里勾"登录时启动" |
| 日志里设备的真实 IP（Mac 上） | Docker Desktop 转发端口，所有连接看起来都来自 `192.168.65.1` | 不影响使用；Linux 上可以改用 host 网络（见下） |

## 准备

先按[使用说明](../../docs/GUIDE.md)在 Mac 上装好一次后端（网页刷机给的安装命令，或手动安装）。Docker 直接用装好的这几样：

| 目录 | 里面有什么 | 容器里 |
| --- | --- | --- |
| 后端的 `data/` | `.config.yaml`，网关页面的设置、固件、唤醒词资源包 | 挂到 `/opt/zongzhu/server/data` |
| 后端的 `models/` | `snakers4_silero-vad`、X-ASR 模型，接音箱时还有 `sherpa-onnx-kws-open-xiaoai` | 只读挂到 `/opt/zongzhu/server/models` |
| `private/` | Bot Webhook 配置、Bot 写回复的目录、音箱 token | **挂在和电脑上一样的路径** |
| 这个仓库 | `firmware/`、`web/boards.json` | 只读，挂在一样的路径 |

私人目录必须挂在一样的路径：后端会把回复文件的**完整路径**交给 Bot，Bot 在电脑上写这个文件，后端在容器里读它，两边路径不一样就收不到回复。这样挂，配置里 Webhook、音箱 token、`gateway.firmware_root` 的路径也都不用改。

配置（`data/.config.yaml`）里要确认：

```yaml
local_music:
  enabled: false        # 容器里放不出声音
server:
  websocket: ws://<电脑的局域网 IP>:8000/xiaozhi/v1/            # 写电脑的地址，不能让后端自己猜（容器里猜出来的是容器的地址）
  vision_explain: http://<电脑的局域网 IP>:8003/mcp/vision/explain
```

## 运行

在仓库根目录：

```sh
cp deploy/docker/env.example deploy/docker/.env    # 改成你自己的 4 个目录（绝对路径）
docker compose -f deploy/docker/compose.yaml up -d --build
docker logs -f zongzhu-backend                    # 看日志
```

先停掉直接在 Mac 上运行的后端（`start.sh` 或 `tools/autostart.sh disable`）：8000、8003、4399 端口同时只能有一个程序用。

- 停：`docker compose -f deploy/docker/compose.yaml down`
- 更新代码后：`git pull`，再 `up -d --build`
- 改了 `.config.yaml`：`docker restart zongzhu-backend`

镜像里只有后端代码和依赖（约 2 GB），配置、密钥、模型都不在镜像里，换一台电脑要连同这几个目录一起准备好。

## 跑测试

```sh
docker run --rm -v "$PWD/requirements-macos-test.txt:/tmp/rt.txt:ro" zongzhu-backend \
  sh -c 'pip install -q -r /tmp/rt.txt && python -m pytest -q'
```

没挂模型目录时，音箱唤醒词那一项会跳过。

## Linux 服务器

同一份 compose 也能用。要看到设备的真实 IP，可以在 `compose.yaml` 里把 `ports` 换成 `network_mode: host`。放到公网上时，还要按 [部署说明](../README.md) 加 HTTPS 反向代理、只放行板子用到的路径、开设备白名单；Bot 不能往服务器写文件时，在 Webhook 配置里写 `reply_url`，让 Bot 用 HTTPS 把回复发回来。
