# zongzhu-speaker：让小米音箱接入宗主

把小米智能音箱 Pro（OH2P）变成宗主的一块"没有屏幕的板子"：喊"宗主"（或 AI 的呼名），音箱回"在"，后面的话交给 Bot，回答从音箱里念出来；念的时候喊"宗主"能打断。小爱同学照常能用。

```
音箱（补丁固件 + Client）──WebSocket 4399──▶ 宗主后端（core/gateway/xiaoai/）
```

- **音箱上**：刷补丁固件（开 SSH、关小米自动升级、开机运行 `/data/init.sh`），再装 Client。Client 把麦克风和播放交给后端。
- **后端里**：唤醒词识别、对话都在宗主后端里，打开方法见 [GUIDE 的"接入小米智能音箱 Pro"](../docs/GUIDE.md#接入小米智能音箱-pro可选)。

本目录是音箱这一边需要的东西：补丁、Client 源码、做镜像、备份、刷机、编译、安装的脚本。只在 **OH2P、固件 1.62.2、Apple Silicon 的 Mac** 上完整做过一遍，别的版本和型号没试过。

## 目录

| 路径 | 内容 |
| --- | --- |
| `firmware/patches/` | 补丁固件用的 4 个补丁：开 SSH、设 root 密码并让串口进 shell、关自动升级、开机运行 `/data/init.sh` |
| `firmware/` | 下载官方包、做镜像、只读备份、刷机的脚本 |
| `client/client-rust/` | 音箱上跑的 Client 源码（Rust） |
| `client/` | 编译、安装 Client 的脚本，音箱的开机脚本 `init.sh` |

## 先看风险

- **刷机有变砖的可能。** 下面的做法只写音箱 A/B 两套系统中的一边，另一边的官方系统不动，出问题可以切回去（见"退路"）。但刷机工具、USB 线、断电都可能出意外，**风险自负**。
- **刷之前先备份**（第 4 步）。备份只读，不写音箱。
- 补丁固件**关掉了小米的自动升级**。以后想升级，要先切回官方那一边。
- 音箱的 root 密码由你在第 3 步设置，SSH 只在局域网里能连。Client 和后端之间用 token 认证。
- 改动系统可能影响保修。本项目与小米没有任何关系，详见 [DISCLAIMER.md](DISCLAIMER.md)。

## 需要准备

- 小米智能音箱 Pro（型号 OH2P，看底部标签），**能传数据的 Type-C 线**，直插电脑，不要经过扩展坞。
- Mac（Homebrew）：
  ```sh
  brew install squashfs libusb libusb-compat rustup zig
  python3 -m venv ~/.venvs/xiaoai && ~/.venvs/xiaoai/bin/pip install pyusb   # 刷机时用
  ```
- 晶晨（Amlogic）刷机工具 `update`（macOS 版），来自 [khadas/utils](https://github.com/khadas/utils) 的 `aml-flash-tool/tools/macos/update`。它是 Amlogic 的程序，本仓库不带。下载后放到 `firmware/tools/update` 并 `chmod +x`；我们用的那份 SHA-256 是 `19f37cc129d061512c24bffbbad3a51355d976c12d6091366fe7dfce3c949b30`（v1.7.5）。
- 已经能跑的宗主后端（见 [docs/GUIDE.md](../docs/GUIDE.md)）。

下面的命令都在本目录（`zongzhu-speaker/`）里运行。生成的文件放在 `work/`，不会进 git。

## 1. 确认版本

米家 App → 音箱 → 设置 → 检查更新，记下现在的版本（例如 1.62.2）。最好先在 App 里升到最新，这样下载的官方包和音箱上正在用的是同一个版本。

## 2. 下载官方固件包

```sh
python3 firmware/ota_query.py <SN> <当前版本>      # SN 在音箱底部标签上，例如 12345/A1B234567
```

不用登录。返回的 JSON 里，`data.currentInfo` 是当前版本，`data.upgradeInfo` 是能升级到的新版本。其中 `link` 是下载地址，`hash` 是 MD5，下载后用 `md5 <文件>` 核对。文件名形如 `mico_all_xxxxxxxxx_1.62.2.bin`，别改名，脚本要用文件名里的 MD5 片段做校验。

官方固件是小米的，本仓库不带，也不带打好补丁的镜像（里面是小米的系统和你的密码串）。

## 3. 做补丁镜像（只在电脑上）

```sh
bash firmware/build_image.sh <官方包.bin> work/build
```

会让你输入音箱的 root 密码（SSH 用，不回显）。脚本会：

1. 解开官方包，校验 CRC32 和 MD5；
2. 把 `firmware/patches/` 的 4 个补丁打到官方系统上；
3. 打包成 `work/build/root-patched.squashfs`，并复制一份官方内核 `boot.img.encrypt`；
4. 核对：和官方系统比，**只能有补丁改的 8 个文件不同**，条目数、权限、属主都不变，镜像里的密码串要能用你输的密码验证通过。任何一项不对就报错，这时不要刷。

## 4. 只读备份，判断现在用的是哪一边

```sh
UPDATE=firmware/tools/update PYTHON=~/.venvs/xiaoai/bin/python bash firmware/backup_readonly.sh work/backup
```

拔掉音箱电源 → 运行脚本 → 看到"等待设备"后插上电源。刷机模式的设备上电后只出现约 1 秒，脚本会自动抓住；没抓住就拔电再插，重新运行。读完拔电再插，音箱正常开机。

小米升级时写的是**没在用的那一边**，写完再切过去，所以两边可能是不同的版本。拿备份和官方包比一比，和现在版本相同的那边就是正在用的：

```sh
B=work/build K=work/backup
for s in 0 1; do
  head -c $(wc -c < $B/boot.img.encrypt) $K/boot$s.img | cmp -s - $B/boot.img.encrypt && echo "boot$s 是这个版本"
  head -c $(wc -c < $B/extracted/root.squashfs) $K/system$s.img | cmp -s - $B/extracted/root.squashfs && echo "system$s 是这个版本"
done
```

**刷另一边**（下面叫 SLOT）。比如 boot1 / system1 是现在的版本，SLOT 就是 0，官方系统留在 1 号，随时能切回去。两边都对得上时，选 0 号。

## 5. 刷机

```sh
SLOT=0 BOOTDELAY=15 UPDATE=firmware/tools/update PYTHON=~/.venvs/xiaoai/bin/python \
  bash firmware/flash_slot.sh work/build
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
$S 'dd if=/dev/mtd6 2>/dev/null' > work/backup/data-full.img
$S 'tar -c -C / data 2>/dev/null' > work/backup/data-files.tar
```

## 6. 编译 Client，生成 token

```sh
rustup default stable && rustup target add armv7-unknown-linux-gnueabihf && cargo install --locked cargo-zigbuild
bash client/build_client.sh            # 输出 work/client/client
python3 -c "import secrets; print(secrets.token_urlsafe(24))" > work/token.txt && chmod 600 work/token.txt
```

Client 源码在 `client/client-rust/`，来自 [coderzc/open-xiaoai](https://github.com/coderzc/open-xiaoai) 的 `14e1034`。它比原版多一处：连接时带 token。在 Mac 上编译出来的 SHA-256 是 `ec2a78a80d3ea71b8df584526a332b1872fc65aecd15f89aaee7b96ccb7101bd`，你编出来应该一样。

## 7. 在后端里打开音箱接入

下载唤醒词模型、在后端配置里打开 `gateway.xiaoai`（`token_file` 指向上一步的 `work/token.txt`，写完整路径），然后重启后端。步骤见 [GUIDE 的"接入小米智能音箱 Pro"](../docs/GUIDE.md#接入小米智能音箱-pro可选) 第 6、7 步。后端日志出现 `小米音箱接入：ws://0.0.0.0:4399` 就好了。

## 8. 把 Client 装到音箱上

```sh
bash client/install_client.sh <音箱 IP> ws://<运行后端的电脑的局域网 IP>:4399 work/token.txt
```

在终端里输一次 root 密码。第一次连时会自动记下音箱的主机密钥；以后重新刷了机，密钥会变，要先运行 `ssh-keygen -R <音箱 IP>`。脚本会：

1. 写入 `/data/open-xiaoai/`：Client、后端地址、token；
2. 写入开机脚本 `/data/init.sh`；
3. 核对校验和，然后启动。

约 20 秒后，后端日志里出现 `小米音箱已连接`，音箱"嘀"一声。以后音箱开机会自动连。

电脑的 IP 写进了音箱，所以要**在路由器里给电脑固定一个 IP**。不然电脑换了 IP，音箱就连不上了；真换了就重新运行这一步。

## 9. 试一下

- 喊"宗主"，音箱回"在"，再说"现在几点"，回答从音箱里出来。
- 打开网关页面 `http://<电脑>:8003/gateway`，能看到"小米音箱 Pro"。
- 喊"小爱同学"，小爱照常工作。

## 退路和撤销

- **只停掉宗主**：SSH 进音箱运行 `touch /data/open-xiaoai/disabled`，然后重启。删掉这个文件再重启就恢复。
- **撤销 Client**：删掉 `/data/init.sh` 和 `/data/open-xiaoai/`。
- **回到官方系统**：SSH 进音箱运行 `fw_env -s boot_part boot<另一边>`，然后重启。SSH 连不上时，进刷机模式运行 `firmware/tools/update bulkcmd "setenv boot_part boot<另一边>"`，再运行 `firmware/tools/update bulkcmd "saveenv"`。

## 已知问题

- 音箱没有屏幕，也没有宗主固件的 MCP 工具，网关页面上不能调它的音量和亮度。
- 刷机模式的设备只出现约 1 秒，`aml_wait.py` 偶尔抓不住，多试几次就行。抓住以后，音箱会一直停在刷机模式。

## 文件

| 文件 | 作用 |
| --- | --- |
| `firmware/patches/01-ssh.patch` … `04-start.patch` | 补丁：开 SSH；设 root 密码，串口进 shell；关自动升级；开机运行 `/data/init.sh` |
| `firmware/ota_query.py` | 查官方固件下载地址（不用登录） |
| `firmware/mico_extract.py` | 解开官方包，校验 CRC32 和 MD5 |
| `firmware/build_image.sh` | 打补丁、打包、核对 |
| `firmware/aml_wait.py` | 抓住刷机模式（只发只读的 identify） |
| `firmware/backup_readonly.sh` | 只读备份 |
| `firmware/flash_slot.sh` | 写一边 + 读回核对 + 切启动参数 |
| `firmware/tree_diff.py`、`sqfs_list_diff.py` | 比较两个系统的内容和权限 |
| `firmware/usb_watch.sh` | 诊断：记录 USB 设备的出现和消失 |
| `client/client-rust/` | Client 源码 |
| `client/build_client.sh` | 编译 Client |
| `client/install_client.sh` | 装 Client 和开机脚本 |
| `client/init.sh` | 音箱上的开机脚本：Client 退出 5 秒后重启，不联网下载任何东西 |
| `client/test_server.py` | 最小测试接收端：不开后端，只看音箱的 Client 能不能连上、token 对不对 |

## 来源和许可

- **补丁和 Client**：`firmware/patches/` 和 `client/client-rust/` 来自 [idootop/open-xiaoai](https://github.com/idootop/open-xiaoai)，Client 用的是 [coderzc/open-xiaoai](https://github.com/coderzc/open-xiaoai) 的 fork，提交 `14e1034`，内容没有改动。MIT 许可证，见 [LICENSE.open-xiaoai](LICENSE.open-xiaoai)。
- **借用的格式**：`mico_extract.py` 照 open-xiaoai 的 `client-patch/src/extract.py`（它又源自 csftech/Xiaomi-OpenWrt-firmware-toolkit）；`ota_query.py` 照 open-xiaoai 的 `client-patch/src/ota.ts`。
- **不在本仓库的**：小米官方固件和打好补丁的镜像（小米的系统，镜像里还有你的密码串）、刷机工具 `update`（Amlogic 的程序）。
