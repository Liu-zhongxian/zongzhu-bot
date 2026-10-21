中文 | [English](README.en.md)

# 宗主 Zongzhu Bot

![宗主：黑底圆屏上一对白色眼睛的桌面语音终端](docs/images/banner.jpg)

[![固件](https://img.shields.io/badge/固件-2.5.2.9-black)](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest)
[![板型](https://img.shields.io/badge/板型-微雪_1.75C_|_立创实战派_S3-blue)](#需要准备)
[![许可](https://img.shields.io/badge/许可-MIT-green)](LICENSE)

让一块 ESP32-S3 屏幕开发板变成 Grok Bot 的语音终端：说「你好宗主」唤醒，直接说需求，Bot 的回答回到屏幕上显示并朗读。屏幕是一对会眨眼、会跟手、会被摇晕的黑底白眼睛。

## 需要准备

- **板子**：微雪 ESP32-S3-Touch-AMOLED-1.75C，或立创·实战派 ESP32-S3（[说明](docs/BOARD-SZP.md)）。M5Stack StopWatch 能编译，还没上过实机（[说明](docs/BOARD-STOPWATCH.md)）。
- **电脑**：一台常开的 Mac（Apple 芯片上验证过）运行后端，和板子在同一个 2.4GHz 局域网。有公网服务器也可以[部署到服务器](deploy/README.md)。
- **Bot**：你的 Grok Bot 要提供 Webhook，并且**能往这台电脑写文件**，回复才能回到板子上（[接口要求](docs/GUIDE.md#bot-接口要求)）。

## 开始使用

1. 用电脑上的 Chrome 或 Edge 打开 **[网页刷机](https://liu-zhongxian.github.io/zongzhu-bot/)**，USB 接上板子。
2. 第一次用先装后端：网页上给出一行命令，粘贴到"终端"运行。它会安装依赖、下载语音模型（约 200MB），问你的 Bot Webhook 地址，最后显示要填回网页的电脑地址。
3. 回到网页，按 6 步走完：识别板子、选唤醒词、选样式、填后端地址、填 Wi-Fi、刷入并检查连接。
4. 说"你好宗主"，再说一句需求。屏幕显示等待秒数，Bot 回复后开始朗读，就通了。

不想用网页、要自己编译固件，或者网页用不了：看[手动安装](docs/GUIDE.md#手动安装不用网页)。

## 能做什么

- 唤醒后说的话直接交给 Bot，等待时显示秒数；回复显示在屏幕上并朗读，断线期间的回复下次连上补发。
- 本地离线语音识别（X-ASR），中英混说也能认，常见误识别自动纠正。
- 13 种实时绘制的眼睛表情，跟着状态切换；触摸、倾斜、摇晃都有反应。
- 字幕三种模式（完整 / 简洁 / 关闭），长按 BOOT 键切换。

操作表、表情列表和常见问题见[完整说明](docs/GUIDE.md)。

## 文档

| | |
| --- | --- |
| [docs/GUIDE.md](docs/GUIDE.md) | 完整说明：功能、手动安装、刷机、常见问题、Bot 接口、构建、测试、已知限制 |
| [docs/README.md](docs/README.md) | 全部文档目录，包括各板说明和开发记录 |
| [deploy/README.md](deploy/README.md) | 部署到公网服务器 |

## 来源与许可

固件基于 [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)，后端基于 [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)，都是 MIT 许可证；上游基线提交记录在 `UPSTREAM.json`。真实密钥、Wi-Fi 配置、Flash 备份、模型权重、运行日志和对话内容都只留在本机，不在这个仓库里。
