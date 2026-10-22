中文 | [English](README.en.md)

# 宗主 Zongzhu Bot

![宗主：黑底圆屏上一对白色眼睛的桌面语音终端](docs/images/banner.jpg)

[![固件](https://img.shields.io/badge/固件-2.5.2.9-black)](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest)
[![板型](https://img.shields.io/badge/板型-微雪_1.75C_|_立创实战派_S3-blue)](#需要准备)
[![许可](https://img.shields.io/badge/许可-MIT-green)](LICENSE)

**对板子说一句话：要查、要做的交给 Grok Bot，放歌、暂停、调音量在电脑上马上执行。**

[使用说明](docs/GUIDE.md) · [文档目录](docs/README.md) · [网页刷机](https://liu-zhongxian.github.io/zongzhu-bot/)

---

一块 ESP32-S3 屏幕开发板，加上跑在你电脑上的后端。板子负责听和说，屏幕是一对会眨眼、会跟手、会被摇晕的眼睛。后端负责识别语音，再决定这句话交给谁：

```
宗主板子        ⇄   电脑上的后端                    ⇄   Grok Bot
听和说、眼睛         识别语音
                    ├ 放歌、暂停、音量 → 这台电脑直接执行
                    └ 其他的话 → 交给 Bot，回复朗读       干活、回复
```

> 基于小智开源固件和后端的社区项目，不是小智、Grok 或 xAI 的官方项目。

## 功能

**给 Grok Bot 派活**

- **直接说需求**：唤醒后说"帮我把这周的 X 热点整理一下"，不用加"让机器人"之类的前缀。
- **陪着等**：等待时屏幕显示秒数，回复到了就朗读，读完保留全文，长回复自动滚动。
- **不会漏**：连接断开期间到的回复，下次连上补发；对话中再说一次"你好宗主"只回一声"我在"，不会当成新任务。

**本机点歌（可选，默认关闭）**

- **一句话点歌**：说"放周杰伦的晴天""来一首孤勇者""我想听陈奕迅的歌"，约 1.5 秒后歌在电脑上放起来，屏幕显示歌名。
- **随口控制**："先给我暂停""下一首""快进五秒""从头播放""单曲循环""音量调到三十""这首歌是谁唱的"。
- **找原唱**：先搜网易云，没有原唱再同时搜 QQ、酷狗、酷我、咪咕，跳过翻唱、Live、remix 和冒名上传，同样的版本里挑码率最高的。
- **听错了也能放**："晴天"被识别成"请帖"，会按读音找到《晴天》。
- **不抢 Bot 的活**："暂停那个下载任务""继续写昨天那份报告"照旧交给 Bot。

**听得准**

- 本地离线识别（X-ASR），中英混说也能认，"帮我看一下 GitHub 上的 issue"能认对。
- 热词和识别后纠错："你好中主""你好宗猪"会改成"你好宗主"；打开点歌后，再加上常见歌手和歌名的热词。

**屏幕会动**

- 13 种实时绘制的眼睛表情，跟着状态切换；触摸、倾斜、摇晃都有反应。
- 字幕三种模式（完整 / 简洁 / 关闭），长按 BOOT 键切换。

操作表、表情列表、点歌能说的话见[使用说明](docs/GUIDE.md)。

## 需要准备

- **板子**：微雪 ESP32-S3-Touch-AMOLED-1.75C，或立创·实战派 ESP32-S3（[说明](docs/BOARD-SZP.md)）。M5Stack StopWatch 能编译，还没上过实机（[说明](docs/BOARD-STOPWATCH.md)）。
- **电脑**：一台常开的 Mac（Apple 芯片上验证过）运行后端，和板子在同一个 2.4GHz 局域网。有公网服务器也可以[部署到服务器](deploy/README.md)。
- **Bot**：你的 Grok Bot 要提供 Webhook，并且**能往这台电脑写文件**，回复才能回到板子上（[接口要求](docs/GUIDE.md#bot-接口要求)）。

## 快速开始

1. 用电脑上的 Chrome 或 Edge 打开 **[网页刷机](https://liu-zhongxian.github.io/zongzhu-bot/)**，USB 接上板子。
2. 第一次用先装后端：网页上给出一行命令，粘贴到"终端"运行。它会安装依赖、下载语音模型（约 200MB），问你的 Bot Webhook 地址，最后显示要填回网页的电脑地址。
3. 回到网页，按 6 步走完：识别板子、选唤醒词、选样式、填后端地址、填 Wi-Fi、刷入并检查连接。
4. 说"你好宗主"，再说一句需求。屏幕显示等待秒数，Bot 回复后开始朗读，就通了。

想用本机点歌：

```sh
bash tools/local_music_setup.sh    # 下载 go-music-dl 和 mpv 到 local-music/，核对校验值
```

按脚本最后的提示，在后端配置里打开 `local_music`，再重启后端。需要网易云会员歌曲的话，在 go-music-dl 的网页里扫码登录。步骤见[使用说明 · 本机点歌](docs/GUIDE.md#本机点歌可选)。

不想用网页、要自己编译固件，或者网页用不了：看[手动安装](docs/GUIDE.md#手动安装不用网页)。

## 安全

- **只在局域网里用**。不要把后端的 8000、8003 端口暴露到公网；要放到服务器上，按[部署说明](deploy/README.md)让后端只监听本机，并开启设备白名单。
- **Bot 能做的事，语音也能让它做**。板子听到的话会原样交给你的 Bot，它有什么权限（发消息、改文件、花钱），语音就能触发什么。Webhook 地址和令牌放在 `private/`（权限 600），不要提交。
- **本机点歌**：
  - go-music-dl 会监听所有网卡的 18080 端口，后端运行期间，同一局域网的设备都能用它搜歌、下歌。
  - 扫码登录的 Cookie 存在 `local-music/go-music-dl/data/`，这个目录不进 Git。
  - 这些音乐来自各平台的非官方接口，只限个人自用。

## 文档

| | |
| --- | --- |
| [docs/GUIDE.md](docs/GUIDE.md) | 使用说明：功能、本机点歌、手动安装、刷机、常见问题、Bot 接口、构建、测试、已知限制 |
| [docs/README.md](docs/README.md) | 全部文档目录，包括各板说明和开发记录 |
| [docs/records/REFERENCE-TASKS.md](docs/records/REFERENCE-TASKS.md) | 任务说明书：做过什么、为什么这样做、还有哪些待办 |
| [deploy/README.md](deploy/README.md) | 部署到公网服务器 |

## 关于这个仓库

本项目自己的改动集中在这几处：
- **固件**：`xiaozhi-esp32/main/boards/common/zongzhu/`，以及各板目录。
- **后端**：`xiaozhi-esp32-server/main/xiaozhi-server/core/` 下的 `handle/grokBot*.py`、`handle/localCommandHandle.py`、`music/`、`utils/asr_text.py`。
- **其他**：`web/`、`tools/`、`deploy/`、`examples/`、`docs/`。

两个上游目录里其余的代码基本保持原样，方便以后合并上游、跟上小智固件的更新。上游基线提交记录在 `UPSTREAM.json`。

## 来源与许可

- 本项目代码：[MIT 许可证](LICENSE)。
- 固件基于 [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)，后端基于 [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)，两者都是 MIT 许可证。
- 本机点歌用到 [go-music-dl](https://github.com/guohuiyuan/go-music-dl)（AGPL-3.0）和 [mpv](https://github.com/mpv-player/mpv)，两者都不在这个仓库里：由 `tools/local_music_setup.sh` 从各自的发布页下载，作为独立程序运行，遵循各自的许可证。
