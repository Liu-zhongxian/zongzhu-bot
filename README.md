中文 | [English](README.en.md)

# 宗主 Zongzhu Bot

![宗主：黑底圆屏上一对白色眼睛的桌面语音终端](docs/images/banner.jpg)

[![固件](https://img.shields.io/badge/固件-2.5.2.9-black)](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest)
[![板型](https://img.shields.io/badge/板型-Waveshare_ESP32--S3--Touch--AMOLED--1.75C-blue)](#使用前提)
[![许可](https://img.shields.io/badge/许可-MIT-green)](LICENSE)

让一块 466×466 圆屏 ESP32 开发板变成 Grok Bot 的语音终端：说「你好宗主」唤醒，直接说需求，Bot 的回答回到屏幕上显示并朗读。屏幕是一对会眨眼、会跟手、会被摇晕的黑底白眼睛。

> A voice terminal for Grok Bot on the Waveshare ESP32-S3-Touch-AMOLED-1.75C round display. Say the wake word, speak your request, and the Bot's reply is shown on screen and read aloud. Chinese-first; backend verified on Apple Silicon macOS.

## 使用前提

开始之前先确认这四条，任何一条不满足都跑不通：

- **板子**：Waveshare ESP32-S3-Touch-AMOLED-1.75C。固件只适配这一块。
- **电脑**：一台一直开着的电脑运行后端（已在 Apple Silicon macOS 上验证），和板子在同一个 2.4GHz 局域网。
- **Bot**：你的 Grok Bot 要提供 Webhook，并且**能往这台电脑写文件**。回复只留在云端或聊天窗口里的话，板子收不到。
- **不是 API 直连**：本项目调用的是 Bot 的 Webhook，不调用 xAI Chat Completions，只有 xAI API Key 是不够的。

## 功能

**语音 → Bot → 回传**

- 唤醒后说的话直接提交给 Bot，不用加"让机器人"之类的前缀。
- Bot 把回答写进本机回复文件，后端校验后把字幕和 EdgeTTS 语音发回板子。
- 等待时显示秒数，并暂停普通收音。默认最多等 300 秒，超时的任务会保留，不会自动重发。唤醒或按键可以追加内容。
- 长回复会自动滚动，朗读完后保留全文。连接断开期间没送出的回复，下次连上会补发。
- 对话中再说一次"你好宗主"（包括"你好中主""你好宗猪"这类误识别）只会回一句"我在"，不会当成任务提交；"你好宗主，帮我查天气"会去掉唤醒词，只提交"帮我查天气"。

**屏幕表情**

- 13 种实时绘制的眼睛表情，会跟着设备状态和服务端情绪自动切换。
- 眨眼快闭慢睁，偶尔连眨两下；待机、聆听、说话时会随机转一下眼神。
- 眼睛直接用实心形状绘制，每帧只重绘眼睛移动的区域，不用图片序列帧。

<details>
<summary>13 种表情</summary>

待机、聆听、思考、说话、开心（弯弧 ∩）、兴奋、好奇、困惑、生气、惊讶、难过、困倦（眯缝 ∪）、眩晕。

</details>

**字幕模式**：长按 BOOT 键循环切换，设置断电后也会保存。

| 模式 | 显示内容 |
| --- | --- |
| 完整 | 你说的话和 Bot 的全文，长文自动滚动；眼睛缩小 |
| 简洁 | 只显示 Bot 回复的第一句，最多两行；眼睛保持中等大小 |
| 关闭 | 不显示对话文字，眼睛最大 |

配网、激活、升级这类系统提示在任何模式下都会完整显示，等待秒数也照常显示。

**触摸、动作和按键**

<details>
<summary>展开操作表</summary>

| 操作 | 反应 |
| --- | --- |
| 单击 | 开心 |
| 双击 | 惊讶 |
| 长按 | 生气 |
| 按住后拖动 | 眼睛跟着手指 |
| 左右滑 | 切换表情 |
| 上滑 / 下滑 | 惊讶 / 困倦 |
| 倾斜板子 | 视线跟着倾斜方向 |
| 左右用力摇 4 下 | 眩晕，放稳后恢复 |
| BOOT 键短按 | 开始对话；播放中短按会停止播放 |
| BOOT 键长按 | 切换字幕模式 |

反应持续 2–3 秒，之后回到当前状态（聆听、思考、说话等）。碰一下屏幕也会唤醒省电变暗的屏幕。板子没有震动马达，所以没有震动反馈。

</details>

## 工作原理

![架构图：板子把语音发给电脑后端，后端识别后通过 Webhook 交给 Grok Bot，Bot 把回复写回电脑上的文件，后端合成字幕和语音发回板子](docs/images/architecture.zh-CN.svg)

## 快速开始

### 1. 下载固件

从 [Releases](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest) 下载 `zongzhu-1.75c-2.5.2.9.zip`，或者直接用仓库里的 `firmware/zongzhu-1.75c-2.5.2.9/`。

### 2. 后端

需要 Python 3.10、FFmpeg、Opus（`brew install python@3.10 ffmpeg opus`）。下面的命令都在仓库根目录执行：

```sh
python3.10 -m venv .venv
.venv/bin/python -m pip install -r requirements-macos.txt
mkdir -p logs private/bot-replies xiaozhi-esp32-server/main/xiaozhi-server/data
chmod 700 private private/bot-replies
cp examples/backend.config.yaml xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml
cp examples/grok-bot-webhook.example.json private/grok-bot-webhook.json
chmod 600 private/grok-bot-webhook.json xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml
```

然后改两个配置文件：

- `private/grok-bot-webhook.json`：填 Bot Webhook 的 `url` 和 `token`；`reply_dir` 改成 `仓库绝对路径/private/bot-replies`（可以用 `echo "$PWD/private/bot-replies"` 得到）。
- `xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml`：把 `192.168.1.100` 全部换成电脑的局域网 IP（macOS 上用 `ipconfig getifaddr en0` 查）。保持 `LLM: BotOnly`、`Intent: nointent`，不需要模型 API Key。

下载语音识别模型并启动：

```sh
.venv/bin/python - <<'PY'
from modelscope import snapshot_download
snapshot_download('iic/SenseVoiceSmall', local_dir='xiaozhi-esp32-server/main/xiaozhi-server/models/SenseVoiceSmall')
PY
./start.sh
```

`start.sh` 在前台运行，关掉终端服务就停了，不要同时开多个。后端占用 8000（WebSocket）和 8003（HTTP/OTA）两个端口。

### 3. 刷固件

用 USB-C 连上板子，先找串口并备份整片 Flash（出问题可以原样刷回）：

```sh
ls /dev/cu.usbmodem*
esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX read-flash 0 ALL zongzhu-backup.bin
```

然后校验并写入：

```sh
cd firmware/zongzhu-1.75c-2.5.2.9
shasum -a 256 -c SHA256SUMS
esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX --baud 921600 write-flash @flash_args
```

完整分段包不写 NVS（Wi-Fi 等设置会保留），但会把 OTA 启动选择重置到分区 0。找不到串口或连接失败时，按住 BOOT 键再插 USB，进入下载模式后重试。

### 4. 配网

板子开机后连它的热点，选一个和电脑互通的 2.4GHz Wi-Fi。OTA 地址填 `http://电脑局域网IP:8003/xiaozhi/ota/`。

### 5. 试一下

说"你好宗主"，等它回应后说"请回复三句话，介绍宗主现在的等待和朗读功能"。屏幕先显示等待秒数，Bot 写回文件后开始朗读，就说明整条链路通了。

## 常见问题

| 现象 | 先查这里 |
| --- | --- |
| 板子一直连不上服务 | 电脑和板子是否在同一网段；`.config.yaml` 和板子 OTA 地址里的 IP 是否是电脑当前的 IP；macOS 防火墙是否放行了 Python 的 8000/8003 端口 |
| 电脑 IP 变了 | 要改两处：`.config.yaml` 里的 WebSocket 地址，以及板子配网页里的 OTA 地址 |
| 屏幕说"任务已提交"，但一直没有回复 | Bot 没把文件写到这台电脑。确认 Bot 有本机文件写入权限，写到的是 `reply_dir` 下的路径，内容里的 `request_id` 和请求里的一致 |
| 屏幕说"Bot 服务拒绝了请求" | Webhook 返回了 4xx，检查 `url` 和 `token` |
| 屏幕说"Bot 回传目录不可用" | `reply_dir` 不是存在且可写的绝对路径 |
| 唤醒词总是误触发或叫不醒 | 阈值在板级 `config.json` 的 `CONFIG_CUSTOM_WAKE_WORD_THRESHOLD`（当前 20，调低更灵敏、误触发也更多），改完重新构建 |
| 倾斜方向和视线方向反了 | 在 `config.h` 里调整 `QMI8658_SCREEN_X/Y` 后重新构建 |

## Bot 接口要求

后端会向 Webhook 发一个 HTTPS POST，带 `Authorization: Bearer <token>`，请求体大致如下：

```json
{
  "command": "以下是用户对宗主板子说的对话……（含回传路径和格式要求）",
  "user_text": "帮我查一下明天的天气",
  "request_id": "ESP32-3f2a…",
  "device": "板子的设备 ID",
  "source": "zongzhu-voice"
}
```

`command` 里已经写好了给 Bot 的完整指令，包括回复文件的绝对路径。Bot 需要做到：

1. 接受任务后立即返回 `{"success": true, "runUuid": "..."}`。
2. 处理完后，把回答以 UTF-8 JSON 写到指定路径，**先写同目录的临时文件再重命名**：

   ```json
   {"request_id": "ESP32-3f2a…", "text": "实际回答，中文纯文本，最多 2000 字"}
   ```

后端看到文件后才会推送字幕和语音。`.sent.json` 只表示已经交给播放队列，不代表板子确实播放了。

## 从源码构建

加载 ESP-IDF 6.0.1 或更高版本的环境（本版用 6.0.1 实测）。源码路径不能有中文。

```sh
cd xiaozhi-esp32
python scripts/build.py waveshare/esp32-s3-touch-amoled-1.75 --name esp32-s3-touch-amoled-1.75c
```

## 仓库结构

| 路径 | 内容 |
| --- | --- |
| `xiaozhi-esp32/` | 完整固件源码；本项目的改动集中在 `main/boards/waveshare/esp32-s3-touch-amoled-1.75/` |
| `xiaozhi-esp32-server/main/xiaozhi-server/` | 实际运行的 Python 后端，Bot 桥接在 `core/handle/grokBotHandle.py` |
| `firmware/zongzhu-1.75c-2.5.2.9/` | 编译好的分段固件、校验值、构建记录 |
| `examples/` | 不含真实凭证的配置模板 |
| `docs/TASK-RECORD.md` | 脱敏后的实施过程和每次验收记录 |
| `docs/VALIDATION.md` | 当前版本的测试范围和限制 |
| `verify_*.py` | 连真实 Bot 的端到端验证脚本 |

<details>
<summary>板级关键文件</summary>

| 文件 | 作用 |
| --- | --- |
| `eye_model.h` | 13 种表情的形状和动态（纯数学，不依赖 LVGL） |
| `eye_display.h` | 圆屏布局、眼睛绘制、眨眼和眼神、触摸手势、字幕模式 |
| `qmi8658_motion.h` | QMI8658 驱动，倾斜跟随和摇晃检测 |
| `config.h` | 引脚和 IMU 轴向映射 |
| `config.json` | 构建选项：唤醒词、1ms 系统时钟（`CONFIG_FREERTOS_HZ=1000`） |

</details>

## 测试

```sh
cd xiaozhi-esp32-server/main/xiaozhi-server
../../../.venv/bin/python -m unittest tests.test_grok_bot tests.test_grok_bot_reply -v
```

`verify_bot_bridge.py`、`verify_bot_reply.py`、`verify_bot_speech.py` 会真的调用你配置的 Bot，只在你有权限的测试环境里用，运行前先启动后端。`verify_bot_wait_display.py` 用的是本机测试文件，正常情况下不会调用 Webhook。每个版本的实测结果见 [docs/VALIDATION.md](docs/VALIDATION.md)。

## 已知限制

- 说话时眼睛的起伏是按状态播放的动画，不跟音量同步。
- 动画逻辑实测约 35–42 帧/秒。显示任务优先级低于语音处理，以保证声音不卡，所以说话时偶尔会有 100ms 左右的停顿。
- 手势阈值是按测试板调的，换一种握持方式可能需要微调。
- 只能在局域网内用，电脑必须开着。
- MQTT 路径参与了编译，但没有单独做实机网络验收。

## 来源与许可

- 固件基于 [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)，后端基于 [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)，都是 MIT 许可证。
- 源码快照不含上游的 Git 历史。上游基线提交记录在 `UPSTREAM.json`。

真实密钥、Wi-Fi 配置、Flash 备份、模型权重、运行日志和对话内容都只留在本机，不在这个仓库里。
