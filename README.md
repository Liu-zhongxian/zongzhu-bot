中文 | [English](README.en.md)

# 宗主 Zongzhu Bot

![宗主：黑底圆屏上一对白色眼睛的桌面语音终端](docs/images/banner.jpg)

[![固件](https://img.shields.io/badge/固件-2.5.2.9-black)](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest)
[![板型](https://img.shields.io/badge/板型-微雪_1.75C_|_立创实战派_S3-blue)](#需要准备)
[![音箱](https://img.shields.io/badge/可选-小米智能音箱_Pro-orange)](#小米智能音箱-pro可选实验)
[![许可](https://img.shields.io/badge/许可-MIT-green)](LICENSE)

**对板子说一句话：要查、要做的交给 Grok Bot；放歌、暂停、调音量，电脑上马上执行。**

[使用说明](docs/GUIDE.md) · [文档目录](docs/README.md) · [网页刷机](https://liu-zhongxian.github.io/zongzhu-bot/)

---

宗主由两部分组成：一块 ESP32-S3 屏幕开发板，和一个跑在你电脑上的后端。

- **板子**负责听和说。屏幕是一对会眨眼、会跟手、摇晃会晕的眼睛。
- **后端**负责识别语音，再由里面的网关决定这句话交给谁。
- 刷过补丁固件的**小米智能音箱 Pro** 也能接进来，用起来就像一块没有屏幕的宗主。

```
宗主板子 ─┐                    电脑上的后端
          ├─ 语音 ─▶  识别 → 网关 ┬ 放歌、暂停、音量 → 这台电脑直接执行
小米音箱 ─┘                       └ 其他的话 → Grok Bot ─▶ 干活、回复 ─▶ 朗读
                      网关页面：看状态、管设备、更新固件（浏览器打开）
```

> 这是基于小智开源固件和后端的社区项目，不是小智、Grok 或 xAI 的官方项目。

## 功能

### 给 Grok Bot 派活

- **直接说需求**：唤醒后直接说"帮我把这周的 X 热点整理一下"，不用加"让机器人"之类的前缀。
- **陪着等**：等回复时屏幕显示已等的秒数。回复到了就朗读，读完保留全文，太长会自动滚动。
- **不会漏**：连接断开期间到的回复，下次连上补发。对话中再说一次唤醒词，它只回一声"我在"，不会当成新任务。
- **指名交给谁**：说"嗨 + Bot 的名字"，后面的话直接交给这个 Bot。称呼在网关页面上改，也可以加上它常听错的写法。

### 网关页面

浏览器打开 `http://<电脑地址>:8003/gateway`，局域网里的手机、电脑都能看。页面上不显示任何密钥。

- **总览**：哪些板子在线、在做什么（在听、在说、等了 Bot 几秒），各模块是否正常。
- **最近的话**：每句话交给了谁、多久出声，以及 AI 回了什么。
- **设备**：
  - 读板子的 WiFi 信号、IP、版本、内存。
  - 调音量和亮度、重启板子。
  - 改唤醒词，不用重刷固件。
  - 控制小米音箱：调音量、播放 / 暂停、让它说一句话、打断小爱。
- **转交任务**：交给 Bot 的每件事，在等、已回复、已念完、超时，分开列出。
- **工作原理**：按你现在的配置，画出一句话从收音到朗读要经过哪几步。
- **更新固件**：可以在页面上传固件给自己的板子，选"立即更新"或"下次开机更新"。上传前会核对型号、芯片和版本，刷错型号的固件会被拒绝。

### 固件自动更新

项目发布新固件后，你的后端会自动拿到，你的板子在下次开机时更新。

- 发布的固件带项目主人的签名，后端用写在代码里的公钥核对。签名不对、文件被改过，都不收。
- 只下载你自己板子用得上的型号，下载后还要核对大小、SHA-256 和固件内容。
- 发布的固件里不带任何人的后端地址，更新后板子照旧连你自己的后端。
- 默认打开。可以在页面上关掉，或在配置里写 `gateway.firmware_releases: false`。

### 本机点歌（可选，默认关闭）

- **一句话点歌**：说"放周杰伦的晴天""来一首孤勇者""我想听陈奕迅的歌"，约 1.5 秒后歌在电脑上响起，屏幕显示歌名。
- **随口控制**：比如"先给我暂停""下一首""快进五秒""从头播放""单曲循环""音量调到三十""这首歌是谁唱的"。
- **找原唱**：先搜网易云，没有原唱再同时搜 QQ、酷狗、酷我、咪咕。翻唱、Live、remix 和冒名上传都会跳过，同一版本里挑码率最高的。
- **听错了也能放**："晴天"被识别成"请帖"，会按读音找到《晴天》。
- **不抢 Bot 的活**："暂停那个下载任务""继续写昨天那份报告"这类话照旧交给 Bot。

### 小米智能音箱 Pro（可选，实验）

给音箱刷 open-xiaoai 的补丁固件后，它直接连宗主后端，小爱同学照常能用。

- 喊"宗主"，或者直接喊 Bot 的名字，后面的话交给 Bot，回答从音箱里念出来。
- 音箱在念的时候也能打断：喊一声，问新问题。新问题答完后，它会把刚才没念完的接着念完。
- 目前只在 OH2P、固件 1.62.2 上完整做过。刷机有变砖风险，步骤见 [GUIDE](docs/GUIDE.md#接入小米智能音箱-pro可选)，刷机细节和退路见 [zongzhu-speaker](zongzhu-speaker/README.md)。

### 听得准，屏幕会动

- **识别**：本地离线识别（X-ASR），中英混说也能认，比如"帮我看一下 GitHub 上的 issue"。
- **纠错**：有热词和识别后纠错，"你好中主""你好宗猪"会改回"你好宗主"。打开点歌后，再加上常见歌手和歌名的热词。
- **表情**：13 种实时绘制的眼睛表情，跟着状态切换，触摸、倾斜、摇晃都有反应。
- **字幕**：三种模式（完整 / 简洁 / 关闭），长按 BOOT 键切换。

操作表、表情列表、点歌能说的话，见[使用说明](docs/GUIDE.md)。

## 需要准备

- **板子**（任选一块）：
  - 微雪 ESP32-S3-Touch-AMOLED-1.75C；
  - 立创·实战派 ESP32-S3（[说明](docs/BOARD-SZP.md)）。
  - M5Stack StopWatch 也能编译，但还没上过实机（[说明](docs/BOARD-STOPWATCH.md)）。
- **电脑**：一台常开的 Mac（在 Apple 芯片上验证过）运行后端，要和板子在同一个 2.4GHz 局域网。Windows、Linux 可以[用 Docker 运行](deploy/docker/README.md)（点歌除外），或[部署到公网服务器](deploy/README.md)。
- **Bot**：你的 Grok Bot 要提供 Webhook，并且**能往这台电脑写文件**，回复才能回到板子上（[接口要求](docs/GUIDE.md#bot-接口要求)）。

## 快速开始

1. 在电脑上用 Chrome 或 Edge 打开 **[网页刷机](https://liu-zhongxian.github.io/zongzhu-bot/)**，用 USB 接上板子。
2. 第一次用要先装后端：网页上给出一行命令，粘贴到"终端"里运行。它会：
   - 安装依赖；
   - 下载语音模型（约 200MB）；
   - 问你的 Bot Webhook 地址；
   - 最后显示要填回网页的电脑地址。
3. 回到网页，按 6 步走完：识别板子、选唤醒词、选样式、填后端地址、填 Wi-Fi、刷入并检查连接。
4. 说"你好宗主"，再说一句需求。屏幕开始显示等待秒数，Bot 回复后开始朗读，就说明通了。
5. 打开网关页面 `http://<电脑地址>:8003/gateway`，看看板子是不是显示在线。

想用本机点歌：

```sh
bash tools/local_music_setup.sh    # 下载 go-music-dl 和 mpv 到 local-music/，核对校验值
```

按脚本最后的提示，在后端配置里打开 `local_music`，再重启后端。需要网易云会员歌曲的话，在 go-music-dl 的网页里扫码登录。详细步骤见[使用说明 · 本机点歌](docs/GUIDE.md#本机点歌可选)。

如果不想用网页、要自己编译固件，或者网页用不了，看[手动安装](docs/GUIDE.md#手动安装不用网页)。

## 安全

- **只在局域网里用**：
  - 不要把后端的 8000、8003 端口暴露到公网。
  - 要放到服务器上，就按[部署说明](deploy/README.md)让后端只监听本机，并开启设备白名单。
  - 不想让局域网里的人随便改设置，就在配置里写 `gateway.password`，网关页面会先要口令。
- **Bot 能做的事，语音也能让它做**：
  - 板子听到的话会原样交给你的 Bot。Bot 有什么权限（发消息、改文件、花钱），语音就能触发什么。
  - Webhook 地址和令牌放在 `private/`（权限 600），不要提交。
- **固件更新**：
  - 自动更新只收项目主人签名的发布。签名私钥不在仓库里，别人没法冒充发布。
  - 其他人只能在自己的网关页面上，给自己的板子更新。
- **本机点歌**：
  - go-music-dl 会监听所有网卡的 18080 端口。后端运行期间，同一局域网的设备都能用它搜歌、下歌。
  - 扫码登录的 Cookie 存在 `local-music/go-music-dl/data/`，这个目录不进 Git。
  - 这些音乐来自各平台的非官方接口，只限个人自用。
- **小米音箱**：
  - 刷机可能变砖。先按说明只读备份，并且只写 A/B 两套系统中的一边。
  - 补丁固件会开启 root SSH（密码自己设），并关掉小米自动升级。
  - 音箱和后端之间用 token 认证。后端的 4399 端口只给局域网用。

## 文档

| | |
| --- | --- |
| [docs/GUIDE.md](docs/GUIDE.md) | 使用说明：功能、网关页面、本机点歌、小米音箱、手动安装、刷机、常见问题、Bot 接口、构建、测试、已知限制 |
| [docs/README.md](docs/README.md) | 全部文档目录，包括各板说明 |
| [deploy/docker/README.md](deploy/docker/README.md) | 用 Docker 运行后端 |
| [deploy/README.md](deploy/README.md) | 部署到公网服务器 |
| [zongzhu-speaker/README.md](zongzhu-speaker/README.md) | 小米智能音箱 Pro 的刷机和 Client |

## 关于这个仓库

本项目自己的改动集中在这几处：

| 部分 | 位置 |
| --- | --- |
| 固件 | `xiaozhi-esp32/main/boards/common/zongzhu/` 和各板目录 |
| 后端 | `xiaozhi-esp32-server/main/xiaozhi-server/core/` 下的这几处：<br>`gateway/`：网关和网关页面；点歌在 `gateway/skills/music/`，小米音箱在 `gateway/xiaoai/`，固件发布在 `gateway/releases.py`<br>`handle/grokBot*.py`：Bot 的提交和回复<br>`utils/asr_text.py`：热词和纠错 |
| 小米音箱这一边 | `zongzhu-speaker/`：补丁、Client 源码和刷机、安装脚本 |
| 其他 | `web/`（网页刷机）、`tools/`（编译、发布固件、改唤醒词）、`deploy/`（服务器、Docker）、`examples/`、`docs/` |

两个上游目录里其余的代码基本保持原样，方便以后合并上游、跟上小智固件的更新。上游基线的提交记录在 `UPSTREAM.json`。

## 来源与许可

- 本项目代码使用 [MIT 许可证](LICENSE)。
- 固件基于 [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)，后端基于 [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)，两者都是 MIT 许可证。
- 本机点歌用到 [go-music-dl](https://github.com/guohuiyuan/go-music-dl)（AGPL-3.0）和 [mpv](https://github.com/mpv-player/mpv)。两者都不在这个仓库里：由 `tools/local_music_setup.sh` 从各自的发布页下载，作为独立程序运行，各自遵循自己的许可证。
- 小米音箱：
  - 补丁和 Client 源码（`zongzhu-speaker/`）来自 [open-xiaoai](https://github.com/idootop/open-xiaoai)（MIT，见 [zongzhu-speaker/LICENSE.open-xiaoai](zongzhu-speaker/LICENSE.open-xiaoai)）。
  - 后端接音箱的做法（`core/gateway/xiaoai/`）参考了 [coderzc/open-xiaoai-bridge](https://github.com/coderzc/open-xiaoai-bridge)（MIT），唤醒词模型也用它发布的那一套。
  - 小米官方固件和刷机工具不在这个仓库里。
- 呼名的匹配规则参考了 [justhalfbit/xiaozhi-hub-server](https://github.com/justhalfbit/xiaozhi-hub-server)（MIT）。
- 真实密钥、Wi-Fi 设置、Flash 备份、模型权重、登录 Cookie、日志和对话都只留在本机，不在这个仓库里。
