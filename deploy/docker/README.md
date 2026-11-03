# 用 Docker 运行后端

宗主后端可以放进容器里运行，Windows、Linux、Mac 都能用，不用在电脑上装 Python 环境。板子、小米音箱、网关页面、Bot 回复都和直接在 Mac 上运行一样。

**实测情况**：
- 2026-11-04 在 Mac 上实测（Docker Desktop 29.9，Apple 芯片）。从一个空文件夹开始设置，音箱唤醒、交给 Bot、Bot 回复都正常。
- 镜像也按 x86（amd64）编译过，测试全部通过。
- Windows、Linux 实机还没试过。

## 需要准备

- **Docker**：Windows 和 Mac 装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)；Linux 装 Docker Engine 和 compose 插件。
- **这个仓库**：`git clone` 下来，或者下载 zip 解压。
- **一个放宗主文件的文件夹**，比如 `C:\Users\你\zongzhu`、`/home/你/zongzhu`。配置、模型、Bot 的回复都放在这里，删掉容器、重新编译镜像都不会丢。
- **板子**：先用[网页刷机](https://liu-zhongxian.github.io/zongzhu-bot/)刷好。网页第 2 步的安装命令只适用于 Mac，用 Docker 时跳过这一步，后端由下面的 `setup` 来装。
- **Bot**：和 Mac 上的要求一样，Bot 要能往**这台电脑**写文件（[接口要求](../../docs/GUIDE.md#bot-接口要求)）。

## 第一次运行

以下命令都在仓库根目录运行（Windows 用 PowerShell，命令一样）。

1. 写下文件夹的位置：把 `deploy/docker/env.example` 复制成 `deploy/docker/.env`，然后把 `ZONGZHU_HOME` 改成你的文件夹。`.env` 不会进 Git。
2. 编译镜像。第一次要下载依赖，需要几分钟，镜像约 2 GB：

   ```sh
   docker compose -f deploy/docker/compose.yaml build
   ```

3. 设置：

   ```sh
   docker compose -f deploy/docker/compose.yaml run --rm zongzhu setup
   ```

   它会依次问你三件事：
   - 这台电脑的局域网 IP。查法：Windows 运行 `ipconfig`，Linux 运行 `hostname -I`。
   - Bot 的 Webhook 地址和 token。
   - 要不要接小米音箱。

   然后它会：
   - 生成后端配置。连接用的密钥每台电脑随机生成。
   - 下载语音识别模型（约 174 MB）；接音箱的话，再下载唤醒词模型（压缩包约 490 MB）。
   - 最后告诉你网页刷机要填的地址。

   重新运行 `setup` 不会覆盖已有的配置，下过的模型也会跳过。
4. 启动：

   ```sh
   docker compose -f deploy/docker/compose.yaml up -d
   ```

   浏览器打开 `http://<电脑 IP>:8003/gateway`。在网页刷机第 4 步的「电脑的地址」里填这台电脑的 IP。

如果电脑上已经直接运行着宗主后端，先把它停掉。8000、8003、4399 端口同时只能有一个程序用。

## 文件夹里有什么

| 目录 | 内容 |
| --- | --- |
| `data/` | 后端配置 `.config.yaml`，以及网关页面的设置、上传的固件、唤醒词资源包 |
| `models/` | X-ASR 语音识别模型；接音箱时还有 `sherpa-onnx-kws-open-xiaoai` |
| `private/` | `grok-bot-webhook.json`（Bot 地址和 token）、`bot-replies/`（Bot 写回复的地方）、`open-xiaoai-token.txt`（音箱 token） |

Bot 是在电脑上写回复文件的，所以后端交给 Bot 的是这个文件夹**在电脑上的路径**，后端自己在容器里读。这两个路径写在 `grok-bot-webhook.json` 里：`reply_dir` 是容器里的路径，`bot_reply_dir` 是电脑上的路径，`setup` 会自动填好。如果你挪了文件夹，要改 `bot_reply_dir` 和 `.env`。

接小米音箱时，装 Client 用 `private/open-xiaoai-token.txt` 这个 token 文件，地址填 `ws://<电脑 IP>:4399`。刷机和装 Client 的步骤见 [GUIDE](../../docs/GUIDE.md#接入小米智能音箱-pro可选)。刷机脚本要在 Mac 或 Linux 上运行。

## 日常用

| 要做什么 | 命令 |
| --- | --- |
| 看日志 | `docker logs -f zongzhu-backend` |
| 停 | `docker compose -f deploy/docker/compose.yaml down` |
| 改了 `data/.config.yaml` | `docker restart zongzhu-backend` |
| 更新代码 | `git pull`，再 `docker compose -f deploy/docker/compose.yaml up -d --build` |

开机自启：compose 里写了 `restart: unless-stopped`，只要 Docker 起来，容器就会起来。Docker Desktop 要在设置里勾上"登录时启动"。

日志开头会打印 `172.x.x.x` 的地址，那是容器内部的地址，可以不用管。板子实际用的是配置里写的电脑 IP。

## 容器里用不了的

| 功能 | 原因 |
| --- | --- |
| 本机点歌 | 歌是在电脑上用 mpv 放出声音，容器里没有声卡。要点歌，就直接在 Mac 上运行后端 |
| `tools/autostart.sh` | 它用的是 macOS 的 launchd，Docker 用上面说的 `restart` 代替 |
| 日志里设备的真实 IP（Windows、Mac） | Docker Desktop 转发端口，所有连接看起来都来自 `192.168.65.1`，不影响使用。Linux 上可以在 `compose.yaml` 里把 `ports` 换成 `network_mode: host` |

## 跑测试

```sh
docker compose -f deploy/docker/compose.yaml run --rm -v "$PWD/requirements-macos-test.txt:/tmp/rt.txt:ro" zongzhu \
  sh -c 'pip install -q -r /tmp/rt.txt && python -m pytest -q'
```

## 放到公网服务器

可以用同一份 compose，但还要按[部署说明](../README.md)做三件事：加 HTTPS 反向代理、只放行板子用到的路径、开设备白名单。

如果 Bot 没法往服务器写文件，就在 `grok-bot-webhook.json` 里写 `reply_url`，让 Bot 用 HTTPS 把回复发回来。
