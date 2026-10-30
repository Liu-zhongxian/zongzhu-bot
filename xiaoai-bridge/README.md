# xiaoai-bridge：让小米音箱接入宗主

把小米智能音箱 Pro（OH2P）变成宗主的一块"没有屏幕的板子"：喊"你好宗主"，音箱回"在"，后面的话交给宗主后端，走的是同一个网关（点歌、Bot、呼名），回答从音箱里念出来。小爱同学照常能用。

```
音箱（补丁固件 + Client）──WebSocket 4399──▶ 电脑上的 xiaoai-bridge（本目录）──小智协议──▶ 宗主后端 8000 / 8003
```

- **音箱上**：刷补丁固件（开 SSH、关小米自动升级、开机运行 `/data/init.sh`），再装 Client。Client 把麦克风和播放交给电脑。
- **电脑上**：bridge 在本机识别唤醒词"你好宗主"、判断你说完没有，然后像一块小智板子一样连宗主后端。网关页面上它显示为"小米音箱 Pro"。

需要的东西都在本目录里：补丁、Client 源码、做镜像、备份、刷机、编译、安装、启动的脚本。只在 **OH2P、固件 1.62.2、Apple Silicon 的 Mac** 上完整做过一遍，别的版本和型号没试过。

## 目录

| 路径 | 内容 |
| --- | --- |
| `speaker/firmware/patches/` | 补丁固件用的 4 个补丁：开 SSH、设 root 密码并让串口进 shell、关自动升级、开机运行 `/data/init.sh` |
| `speaker/firmware/` | 下载官方包、做镜像、只读备份、刷机的脚本 |
| `speaker/client/client-rust/` | 音箱上跑的 Client 源码（Rust） |
| `speaker/client/` | 编译、安装 Client 的脚本，音箱的开机脚本 `init.sh` |
| `scripts/run-zongzhu.sh` | 接宗主后端时启动 bridge |
| `config.py` | bridge 的配置：宗主后端地址、唤醒词 |
| `core/`、`native/` | bridge 本体（Python + Rust 原生模块） |

## 和原项目相比改了什么

本目录基于 [coderzc/open-xiaoai-bridge](https://github.com/coderzc/open-xiaoai-bridge)。为了接宗主后端，改了这些：

- **连接 token**：连后端前先向 OTA 要 token（后端开了认证时必须带）。
- **断开后重连**：后端会断开空闲的连接；bridge 能发现，下次唤醒时自动重连。
- **重复唤醒**：同一句"你好宗主"会被本地唤醒词和小爱自己的识别各触发一次，第二次忽略，不再把正在念的回答截断。
- **小爱放歌**：小爱自己的对话（比如"播放音乐"）不会被 bridge 暂停。
- **唤醒词**："你好宗主""宗主你好"，回一声"在"后交给宗主；回答完直接待机，不说结束语。
- **固定 Client 版本**：原生模块依赖的 open-xiaoai 固定在 `14e1034`，和音箱上的 Client 同一个版本。
- 新增 `speaker/`（刷机、Client）和 `scripts/run-zongzhu.sh`，测试在 `tests/test_zongzhu.py`。

## 先看风险

- **刷机有变砖的可能。** 下面的做法只写音箱 A/B 两套系统中的一边，另一边的官方系统不动，出问题可以切回去（见"退路"）。但刷机工具、USB 线、断电都可能出意外，**风险自负**。
- **刷之前先备份**（第 4 步）。备份只读，不写音箱。
- 补丁固件**关掉了小米的自动升级**。以后想升级，要先切回官方那一边。
- 音箱的 root 密码由你在第 3 步设置，SSH 只在局域网里能连。Client 和 bridge 之间用 token 认证。
- 改动系统可能影响保修。本项目与小米没有任何关系，详见 [DISCLAIMER.md](DISCLAIMER.md)。

## 需要准备

- 小米智能音箱 Pro（型号 OH2P，看底部标签），**能传数据的 Type-C 线**，直插电脑，不要经过扩展坞。
- Mac（Homebrew）：
  ```sh
  brew install squashfs libusb libusb-compat portaudio rustup zig
  python3 -m venv ~/.venvs/xiaoai && ~/.venvs/xiaoai/bin/pip install pyusb   # 刷机时用
  ```
- 晶晨（Amlogic）刷机工具 `update`（macOS 版），来自 [khadas/utils](https://github.com/khadas/utils) 的 `aml-flash-tool/tools/macos/update`。它是 Amlogic 的程序，本仓库不带。下载后放到 `speaker/firmware/tools/update` 并 `chmod +x`；我们用的那份 SHA-256 是 `19f37cc129d061512c24bffbbad3a51355d976c12d6091366fe7dfce3c949b30`（v1.7.5）。
- 已经能跑的宗主后端（见 [docs/GUIDE.md](../docs/GUIDE.md)）。bridge 默认连同一台电脑上的后端。

下面的命令都在本目录（`xiaoai-bridge/`）里运行。生成的文件放在 `speaker/work/`，不会进 git。

## 1. 确认版本

米家 App → 音箱 → 设置 → 检查更新，记下现在的版本（例如 1.62.2）。最好先在 App 里升到最新，这样下载的官方包和音箱上正在用的是同一个版本。

## 2. 下载官方固件包

```sh
python3 speaker/firmware/ota_query.py <SN> <当前版本>      # SN 在音箱底部标签上，例如 12345/A1B234567
```

不用登录。返回的 JSON 里，`data.currentInfo` 是当前版本，`data.upgradeInfo` 是能升级到的新版本。其中 `link` 是下载地址，`hash` 是 MD5，下载后用 `md5 <文件>` 核对。文件名形如 `mico_all_xxxxxxxxx_1.62.2.bin`，别改名，脚本要用文件名里的 MD5 片段做校验。

官方固件是小米的，本仓库不带，也不带打好补丁的镜像（里面是小米的系统和你的密码串）。

## 3. 做补丁镜像（只在电脑上）

```sh
bash speaker/firmware/build_image.sh <官方包.bin> speaker/work/build
```

会让你输入音箱的 root 密码（SSH 用，不回显）。脚本会：

1. 解开官方包，校验 CRC32 和 MD5；
2. 把 `speaker/firmware/patches/` 的 4 个补丁打到官方系统上；
3. 打包成 `speaker/work/build/root-patched.squashfs`，并复制一份官方内核 `boot.img.encrypt`；
4. 核对：和官方系统比，**只能有补丁改的 8 个文件不同**，条目数、权限、属主都不变，镜像里的密码串要能用你输的密码验证通过。任何一项不对就报错，这时不要刷。

## 4. 只读备份，判断现在用的是哪一边

```sh
UPDATE=speaker/firmware/tools/update PYTHON=~/.venvs/xiaoai/bin/python bash speaker/firmware/backup_readonly.sh speaker/work/backup
```

拔掉音箱电源 → 运行脚本 → 看到"等待设备"后插上电源。刷机模式的设备上电后只出现约 1 秒，脚本会自动抓住；没抓住就拔电再插，重新运行。读完拔电再插，音箱正常开机。

小米升级时写的是**没在用的那一边**，写完再切过去，所以两边可能是不同的版本。拿备份和官方包比一比，和现在版本相同的那边就是正在用的：

```sh
B=speaker/work/build K=speaker/work/backup
for s in 0 1; do
  head -c $(wc -c < $B/boot.img.encrypt) $K/boot$s.img | cmp -s - $B/boot.img.encrypt && echo "boot$s 是这个版本"
  head -c $(wc -c < $B/extracted/root.squashfs) $K/system$s.img | cmp -s - $B/extracted/root.squashfs && echo "system$s 是这个版本"
done
```

**刷另一边**（下面叫 SLOT）。比如 boot1 / system1 是现在的版本，SLOT 就是 0，官方系统留在 1 号，随时能切回去。两边都对得上时，选 0 号。

## 5. 刷机

```sh
SLOT=0 BOOTDELAY=15 UPDATE=speaker/firmware/tools/update PYTHON=~/.venvs/xiaoai/bin/python \
  bash speaker/firmware/flash_slot.sh speaker/work/build
```

同样是拔电 → 运行 → 插电。脚本依次把官方内核写进 `boot<SLOT>`、补丁系统写进 `system<SLOT>`，**每一步都读回来逐字节核对**，全部通过才把启动参数切到 `boot<SLOT>`。任何一步失败就停下，不改启动参数，音箱照旧从原来那边启动。`BOOTDELAY=15` 让以后更容易进刷机模式，可以不加。

刷完拔电再插。小爱能正常应答后，用 SSH 检查：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa root@<音箱 IP>
fw_env -g boot_part                      # 应为 boot<SLOT>
grep ROM /usr/share/mico/version         # 应为刷进去的版本
grep -c "no upgrade" /bin/ota            # 1 表示自动升级已关
```

音箱 IP 在路由器管理页面或米家 App 的设备信息里。

刷完以后再备份一次 data 分区。这个分区存设置和登录信息，刷机不写它，第 4 步也没读它。在电脑上运行：

```sh
S="ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa root@<音箱 IP>"
$S 'cat /proc/mtd'                                                      # 确认 data 是 mtd6
$S 'dd if=/dev/mtd6 2>/dev/null' > speaker/work/backup/data-full.img
$S 'tar -c -C / data 2>/dev/null' > speaker/work/backup/data-files.tar
```

## 6. 编译 Client，生成 token

```sh
rustup default stable && rustup target add armv7-unknown-linux-gnueabihf && cargo install --locked cargo-zigbuild
bash speaker/client/build_client.sh            # 输出 speaker/work/client/client
python3 -c "import secrets; print(secrets.token_urlsafe(24))" > speaker/work/token.txt && chmod 600 speaker/work/token.txt
```

Client 源码在 `speaker/client/client-rust/`，来自 [coderzc/open-xiaoai](https://github.com/coderzc/open-xiaoai) 的 `14e1034`。它比原版多一处：连接时带 token。在 Mac 上编译出来的 SHA-256 是 `ec2a78a80d3ea71b8df584526a332b1872fc65aecd15f89aaee7b96ccb7101bd`，你编出来应该一样。

## 7. 在电脑上启动 bridge

bridge 默认连本机的宗主后端，地址是 `config.py` 里的 `OTA_URL` 和 `WEBSOCKET_URL`，后端在别的电脑上时改这两项。唤醒词在同一个文件的 `wakeup.keywords`，默认"你好宗主""宗主你好"。

```sh
OPEN_XIAOAI_TOKEN_FILE=speaker/work/token.txt ./scripts/run-zongzhu.sh
```

第一次运行会装依赖、编译原生模块（几分钟），并下载唤醒词和语音识别模型（约 500 MB）。看到 `已启动: "0.0.0.0:4399"` 和 `连接 ws://…/xiaozhi/v1/ 成功` 就好了。它在前台运行，关掉终端就停了。

## 8. 把 Client 装到音箱上

另开一个终端，也在本目录里：

```sh
bash speaker/client/install_client.sh <音箱 IP> ws://<电脑的局域网 IP>:4399 speaker/work/token.txt
```

在终端里输一次 root 密码。第一次连时会自动记下音箱的主机密钥；以后重新刷了机，密钥会变，要先运行 `ssh-keygen -R <音箱 IP>`。脚本会：

1. 写入 `/data/open-xiaoai/`：Client、bridge 地址、token；
2. 写入开机脚本 `/data/init.sh`；
3. 核对校验和，然后启动。

约 20 秒后，bridge 的日志里出现 `已连接: <音箱 IP>`。以后音箱开机会自动连。

电脑的 IP 写进了音箱，所以要**在路由器里给电脑固定一个 IP**。不然电脑换了 IP，音箱就连不上了；真换了就重新运行这一步。

## 9. 试一下

- 喊"你好宗主"，音箱回"在"，再说"现在几点"，回答从音箱里出来。
- 打开网关页面 `http://<电脑>:8003/gateway`，能看到"小米音箱 Pro"。
- 喊"小爱同学"，小爱照常工作。

后端会断开空闲的连接，这时网关页面上音箱显示"待机"，是正常的。下次喊"你好宗主"会自动重连。

## 退路和撤销

- **只停掉宗主**：SSH 进音箱运行 `touch /data/open-xiaoai/disabled`，然后重启。删掉这个文件再重启就恢复。
- **撤销 Client**：删掉 `/data/init.sh` 和 `/data/open-xiaoai/`。
- **回到官方系统**：SSH 进音箱运行 `fw_env -s boot_part boot<另一边>`，然后重启。SSH 连不上时，进刷机模式运行 `speaker/firmware/tools/update bulkcmd "setenv boot_part boot<另一边>"`，再运行 `speaker/firmware/tools/update bulkcmd "saveenv"`。

## 已知问题

- 喊"你好宗主"有时会听到两声"在"：bridge 的唤醒词识别和小爱自己的识别各触发了一次。
- 音箱没有屏幕，也没有宗主固件的 MCP 工具，网关页面上不能调它的音量和亮度。
- 刷机模式的设备只出现约 1 秒，`aml_wait.py` 偶尔抓不住，多试几次就行。抓住以后，音箱会一直停在刷机模式。

## 环境变量

`scripts/run-zongzhu.sh` 会打开 `XIAOZHI_ENABLE` 和 `API_SERVER_ENABLE`。

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `OPEN_XIAOAI_TOKEN` / `OPEN_XIAOAI_TOKEN_FILE` | Client 的连接 token（或存 token 的文件），和音箱上 `/data/open-xiaoai/token.txt` 一样 | 必填 |
| `XIAOZHI_ENABLE` | 用小智协议连宗主后端 | 关 |
| `API_SERVER_ENABLE` | 本机 HTTP 接口 | 关 |
| `API_SERVER_HOST` / `API_SERVER_PORT` | HTTP 接口地址 | `127.0.0.1` / `9092` |
| `AUDIO_INPUT_ENABLE` | 接收音箱麦克风（关掉后唤醒词和小智都不能用） | 开 |
| `CONFIG_PATH` | 配置文件路径 | `./config.py` |
| `LOGLEVEL` | 日志级别 | `INFO` |

## HTTP 接口

只听本机（`127.0.0.1:9092`），可以让音箱说话、放音频：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/play/text` | 念一段文字：`{"text": "你好"}` |
| `POST` | `/api/play/url` | 放一个音频链接：`{"url": "http://…/a.mp3"}` |
| `POST` | `/api/play/file` | 上传并播放音频文件 |
| `POST` | `/api/wakeup` | 唤醒小爱 |
| `POST` | `/api/interrupt` | 打断当前播放 |
| `GET` | `/api/status` | 播放状态 |
| `GET` | `/api/health` | 健康检查 |

```sh
curl -X POST http://127.0.0.1:9092/api/play/text -H 'Content-Type: application/json' -d '{"text": "宗主已就绪"}'
```

原项目还支持 OpenClaw、OpenAI 兼容服务、QwenPaw、豆包 TTS 等，代码都还在（`core/`、`config.py`），宗主没有用到。用法见 [原项目说明](https://github.com/coderzc/open-xiaoai-bridge#readme)。

## 测试

```sh
uv run python -m unittest tests.test_zongzhu tests.test_openclaw_protocol tests.test_openclaw_response_events \
  tests.test_audio_stream tests.test_qwenpaw tests.test_tts_router
```

用 `scripts/start.sh` 装好依赖以后再跑。`tests/test_zongzhu.py` 覆盖上面"改了什么"里的几处。

## 文件

| 文件 | 作用 |
| --- | --- |
| `speaker/firmware/patches/01-ssh.patch` … `04-start.patch` | 补丁：开 SSH；设 root 密码，串口进 shell；关自动升级；开机运行 `/data/init.sh` |
| `speaker/firmware/ota_query.py` | 查官方固件下载地址（不用登录） |
| `speaker/firmware/mico_extract.py` | 解开官方包，校验 CRC32 和 MD5 |
| `speaker/firmware/build_image.sh` | 打补丁、打包、核对 |
| `speaker/firmware/aml_wait.py` | 抓住刷机模式（只发只读的 identify） |
| `speaker/firmware/backup_readonly.sh` | 只读备份 |
| `speaker/firmware/flash_slot.sh` | 写一边 + 读回核对 + 切启动参数 |
| `speaker/firmware/tree_diff.py`、`sqfs_list_diff.py` | 比较两个系统的内容和权限 |
| `speaker/firmware/usb_watch.sh` | 诊断：记录 USB 设备的出现和消失 |
| `speaker/client/client-rust/` | Client 源码 |
| `speaker/client/build_client.sh` | 编译 Client |
| `speaker/client/install_client.sh` | 装 Client 和开机脚本 |
| `speaker/client/init.sh` | 音箱上的开机脚本：Client 退出 5 秒后重启，不联网下载任何东西 |
| `speaker/client/test_server.py` | 最小测试接收端：不开 bridge，只看音箱的 Client 能不能连上、token 对不对 |
| `scripts/run-zongzhu.sh` | 接宗主后端时启动 bridge |

## 来源和许可

- **bridge**：基于 [coderzc/open-xiaoai-bridge](https://github.com/coderzc/open-xiaoai-bridge)，MIT 许可证，版权声明见 [LICENSE](LICENSE)。
- **补丁和 Client**：`speaker/firmware/patches/` 和 `speaker/client/client-rust/` 来自 [idootop/open-xiaoai](https://github.com/idootop/open-xiaoai)，Client 用的是 [coderzc/open-xiaoai](https://github.com/coderzc/open-xiaoai) 的 fork，提交 `14e1034`，内容没有改动。MIT 许可证，见 [speaker/LICENSE.open-xiaoai](speaker/LICENSE.open-xiaoai)。
- **借用的格式**：`mico_extract.py` 照 open-xiaoai 的 `client-patch/src/extract.py`（它又源自 csftech/Xiaomi-OpenWrt-firmware-toolkit）；`ota_query.py` 照 open-xiaoai 的 `client-patch/src/ota.ts`。
- **不在本仓库的**：小米官方固件和打好补丁的镜像（小米的系统，镜像里还有你的密码串）、刷机工具 `update`（Amlogic 的程序）。
