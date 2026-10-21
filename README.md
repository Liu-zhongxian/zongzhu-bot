中文 | [English](README.en.md)

# 宗主 Zongzhu Bot

![宗主：黑底圆屏上一对白色眼睛的桌面语音终端](docs/images/banner.jpg)

[![固件](https://img.shields.io/badge/固件-2.5.2.9-black)](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest)
[![板型](https://img.shields.io/badge/板型-微雪_1.75C_|_立创实战派_S3-blue)](#使用前提)
[![许可](https://img.shields.io/badge/许可-MIT-green)](LICENSE)

让一块 ESP32-S3 屏幕开发板变成 Grok Bot 的语音终端：说「你好宗主」唤醒，直接说需求，Bot 的回答回到屏幕上显示并朗读。屏幕是一对会眨眼、会跟手、会被摇晕的黑底白眼睛。支持微雪 1.75C（466×466 圆屏）和立创·实战派 ESP32-S3（320×240 横屏），两块板功能相同。

> A voice terminal for Grok Bot on the Waveshare ESP32-S3-Touch-AMOLED-1.75C (round) or the Lichuang SZPI ESP32-S3 (320×240). Say the wake word, speak your request, and the Bot's reply is shown on screen and read aloud. Chinese-first; backend verified on Apple Silicon macOS.

## 使用前提

开始之前先确认这三条，任何一条不满足都跑不通：

- **板子**：微雪 Waveshare ESP32-S3-Touch-AMOLED-1.75C，或立创·实战派 ESP32-S3（N16R8，详见 [docs/BOARD-SZP.md](docs/BOARD-SZP.md)）。M5Stack StopWatch 的编译选项已加上，但还没在实机上跑过，见 [docs/BOARD-STOPWATCH.md](docs/BOARD-STOPWATCH.md)。
- **电脑**：一台一直开着的电脑运行后端（已在 Apple Silicon macOS 上验证），和板子在同一个 2.4GHz 局域网。
- **Bot**：你的 Grok Bot 要提供 Webhook，并且**能往这台电脑写文件**。回复只留在云端或聊天窗口里的话，板子收不到。

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

反应持续 2–3 秒，之后回到当前状态（聆听、思考、说话等）。这两块板都没有震动马达，所以没有震动反馈（M5Stack StopWatch 有马达，按键也不同，见 [docs/BOARD-STOPWATCH.md](docs/BOARD-STOPWATCH.md)）。微雪 1.75C 闲置后屏幕会变暗省电，碰一下屏幕即恢复；立创板不做省电变暗。

</details>

## 工作原理

![架构图：板子把语音发给电脑后端，后端识别后通过 Webhook 交给 Grok Bot，Bot 把回复写回电脑上的文件，后端合成字幕和语音发回板子](docs/images/architecture.zh-CN.svg)

## 快速开始

### 1. 准备固件

两种方式任选：

- **推荐：自己编译，把后端地址编进固件**。之后配网只需要选 Wi-Fi，见第 3 步。
- **直接用发布包**：微雪 1.75C 用 `firmware/zongzhu-1.75c-2.5.2.9/`（也可从 [Releases](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest) 下载 zip），立创板用 `firmware/zongzhu-szp-2.5.2.9/`，M5Stack StopWatch 用 `firmware/zongzhu-stopwatch-2.5.2.9/`（尚未实机验证）。发布包不含你的电脑地址，配网时要手填 OTA 地址。

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

下载语音识别模型 X-ASR（约 174MB；国内下载慢可把 `https://huggingface.co` 换成 `https://hf-mirror.com`）并启动：

```sh
M=sherpa-onnx-x-asr-zipformer-transducer-zh-en-punct-int8-2026-06-03
mkdir -p xiaozhi-esp32-server/main/xiaozhi-server/models/$M
for f in encoder-epoch-99-avg-1.int8.onnx decoder-epoch-99-avg-1.onnx joiner-epoch-99-avg-1.int8.onnx tokens.txt bpe.model; do
  curl -fL -o xiaozhi-esp32-server/main/xiaozhi-server/models/$M/$f https://huggingface.co/csukuangfj2/$M/resolve/main/$f
done
./start.sh
```

语音识别默认用 X-ASR，不需要 torch；热词和识别后纠错的写法见 `examples/backend.config.yaml`。想换回 FunASR（SenseVoiceSmall，约 900MB）：再装 `requirements-macos-funasr.txt`，按上游说明下载模型，把配置里的 `ASR: SherpaXASR` 改成 `ASR: FunASR`。两者对比见 [docs/REFERENCE-TASKS.md](docs/REFERENCE-TASKS.md) 第 7 节。

`start.sh` 在前台运行，关掉终端服务就停了，不要同时开多个。后端占用 8000（WebSocket）和 8003（HTTP/OTA）两个端口。

想让后端开机自动在后台运行（进程退出会自动拉起，运行期间 Mac 不会因空闲睡眠）：

```sh
bash tools/autostart.sh enable    # 开启并马上启动；status 自检，restart 重启，disable 取消
```

仓库在"桌面""文稿""下载"里时，第一次会弹出"宗主后端"想访问文件夹的窗口，点"允许"。原理和注意事项见 [docs/REFERENCE-TASKS.md](docs/REFERENCE-TASKS.md) 第 4 节。

### 3. 刷固件

用 USB-C 连上板子，先找串口并备份整片 Flash（出问题可以原样刷回）：

```sh
ls /dev/cu.usbmodem*
esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX read-flash 0 ALL zongzhu-backup.bin
```

**方式一：编译带本机地址的固件并刷入（推荐）。** 需要 ESP-IDF 6.0.1 或更高版本：

```sh
python3 tools/build_firmware.py szp   --idf <ESP-IDF 目录> --flash /dev/cu.usbmodemXXXX --erase   # 立创板
python3 tools/build_firmware.py 1.75c --idf <ESP-IDF 目录> --flash /dev/cu.usbmodemXXXX --erase   # 微雪 1.75C
python3 tools/build_firmware.py stopwatch --idf <ESP-IDF 目录> --flash /dev/cu.usbmodemXXXX --erase   # M5Stack StopWatch（未上机）
```

固件里的 OTA 地址默认是 `http://<这台 Mac 的名字>.local:8003/xiaozhi/ota/`（名字来自 `scutil --get LocalHostName`），Mac 换了局域网 IP 也能找到。板子首次开机会把这个地址存好，配网页里能看到已经填上。编出的包在 `build-output/`，含本机名字，不会提交到仓库。

`--erase` 会清空整片 Flash（包括 Wi-Fi 设置），板子原来是别的固件时必须加，板子里手动填过 OTA 地址时也要加，否则会继续用旧地址。

**方式二：刷发布包。** 校验并写入：

```sh
cd firmware/zongzhu-1.75c-2.5.2.9   # 立创板换成 firmware/zongzhu-szp-2.5.2.9
shasum -a 256 -c SHA256SUMS
esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX --baud 921600 write-flash @flash_args
```

完整分段包不写 NVS（Wi-Fi 等设置会保留），但会把 OTA 启动选择重置到分区 0。板子原来跑的是别的固件（分区表不同）时，先执行 `esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX erase-flash`。找不到串口或连接失败时，按住 BOOT 键再插 USB，进入下载模式后重试。

### 4. 配网

板子没有 Wi-Fi 设置时会自动开热点（`Xiaozhi-XXXX`）。手机连上后打开 `http://192.168.4.1`，选一个和电脑互通的 2.4GHz Wi-Fi：

- 用方式一刷的固件：**只选 Wi-Fi 并保存**，「高级选项」不用动。
- 用发布包：在「高级选项」里把 OTA 地址填成 `http://电脑局域网IP:8003/xiaozhi/ota/`。

已经配过网的板子要重新配网：开机后、连上 Wi-Fi 之前单击 BOOT（窗口只有 1–2 秒）。

### 5. 试一下

说"你好宗主"，等它回应后说"请回复三句话，介绍宗主现在的等待和朗读功能"。屏幕先显示等待秒数，Bot 写回文件后开始朗读，就说明整条链路通了。

## 常见问题

| 现象 | 先查这里 |
| --- | --- |
| 板子一直连不上服务 | 电脑和板子是否在同一网段；`.config.yaml` 和板子 OTA 地址里的 IP 是否是电脑当前的 IP；macOS 防火墙是否放行了 Python 的 8000/8003 端口 |
| 电脑 IP 变了 | `.config.yaml` 里的 WebSocket 地址要改。板子的 OTA 地址：用方式一（`.local` 名字）刷的不用改；手填 IP 的要在配网页改 |
| 听到"好的，正在交给 Bot"、屏幕在等待，但一直没有回复 | Bot 没把文件写到这台电脑。确认 Bot 有本机文件写入权限，写到的是 `reply_dir` 下的路径，内容里的 `request_id` 和请求里的一致 |
| 回执之后接着说"Bot 服务拒绝了请求" | Webhook 返回了 4xx，检查 `url` 和 `token` |
| 屏幕说"Bot 回传目录不可用" | `reply_dir` 不是存在且可写的绝对路径 |
| 唤醒词总是误触发或叫不醒 | 阈值在板级 `config.json` 的 `CONFIG_CUSTOM_WAKE_WORD_THRESHOLD`（当前 20，调低更灵敏、误触发也更多），改完重新构建 |
| 倾斜方向和视线方向反了 | 在对应板子的 `config.h` 里调整 `QMI8658_SCREEN_X/Y` 后重新构建 |
| 配网时 OTA 地址栏是空的 | 板子里没存地址，固件会用编译时的默认地址。用方式一刷的固件首次开机会自动存好；如果是空的，说明刷的是旧固件 |

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

**在 Bot 的 Webhook 例行任务指令里写明回传是事先允许的。** 否则 Bot 可能把"往电脑上写文件"当成要确认的操作，停下来在对话里问你，板子就一直等不到回复（2026-10-21 实测遇到过）。可以在指令末尾加一句：

> 每条请求的 command 里写明了回传方式：把实际回复按其中给出的路径和 JSON 格式写到我的 Mac 上。这是事先授权的固定步骤，直接执行，不用再问我；只往 private/bot-replies 文件夹里写。发送、删除、付款等其他有后果的操作仍然先问我。

## 从源码构建

加载 ESP-IDF 6.0.1 或更高版本的环境（本版用 6.0.1 实测）。源码路径不能有中文。

```sh
cd xiaozhi-esp32
python scripts/build.py waveshare/esp32-s3-touch-amoled-1.75 --name esp32-s3-touch-amoled-1.75c   # 微雪 1.75C
python scripts/build.py lckfb/szpi-esp32s3 --name lichuang-dev-zongzhu                            # 立创板
```

这样编出的固件 OTA 默认地址是小智官方服务器。要编进自己的后端地址，用第 3 步的 `tools/build_firmware.py`，它会自动把源码同步到无中文的目录再编译。

## 仓库结构

| 路径 | 内容 |
| --- | --- |
| `xiaozhi-esp32/` | 完整固件源码；本项目的改动集中在 `main/boards/common/zongzhu/`（两块板共用）、`main/boards/waveshare/esp32-s3-touch-amoled-1.75/` 和 `main/boards/lckfb/szpi-esp32s3/` |
| `xiaozhi-esp32-server/main/xiaozhi-server/` | 实际运行的 Python 后端，Bot 桥接在 `core/handle/grokBotHandle.py` |
| `firmware/zongzhu-1.75c-2.5.2.9/`、`firmware/zongzhu-szp-2.5.2.9/` | 两块板的发布包：分段固件、校验值、构建记录 |
| `tools/build_firmware.py` | 编译时写入 OTA 地址、打包、刷写 |
| `examples/` | 不含真实凭证的配置模板 |
| `docs/TASK-RECORD.md` | 脱敏后的实施过程和每次验收记录 |
| `docs/VALIDATION.md` | 当前版本的测试范围和限制 |
| `docs/BOARD-SZP.md` | 立创板的移植记录和实测 |
| `verify_*.py` | 连真实 Bot 的端到端验证脚本 |

<details>
<summary>关键文件</summary>

共用代码在 `main/boards/common/zongzhu/`：

| 文件 | 作用 |
| --- | --- |
| `eye_model.h` | 13 种表情的形状和动态（纯数学，不依赖 LVGL） |
| `eye_display.h` | 眼睛绘制、眨眼和眼神、触摸手势、字幕模式；屏幕尺寸和排版由 `EyeScreen` 传入 |
| `qmi8658_motion.h` | QMI8658 驱动，倾斜跟随和摇晃检测 |
| `ota_default.h` | 首次开机把编译时的 OTA 地址存到设置里 |

每块板自己的目录里：

| 文件 | 作用 |
| --- | --- |
| `config.h` | 引脚和 IMU 轴向映射 |
| `config.json` | 构建变体：唤醒词、1ms 系统时钟（`CONFIG_FREERTOS_HZ=1000`）等 |
| 板级 `.cc` | 屏幕排版参数、按键和工具；立创板的宗主功能由 `CONFIG_ZONGZHU_EYE_UI` 开启 |

</details>

## 测试

```sh
cd xiaozhi-esp32-server/main/xiaozhi-server
../../../.venv/bin/python -m unittest tests.test_grok_bot tests.test_grok_bot_reply -v
```

`verify_bot_bridge.py`、`verify_bot_reply.py`、`verify_bot_speech.py` 会真的调用你配置的 Bot，只在你有权限的测试环境里用，运行前先启动后端。`verify_bot_wait_display.py` 用的是本机测试文件，正常情况下不会调用 Webhook。每个版本的实测结果见 [docs/VALIDATION.md](docs/VALIDATION.md)。

## 已知限制

- 说话时眼睛的起伏是按状态播放的动画，不跟音量同步。
- 动画逻辑在微雪 1.75C 上实测约 35–42 帧/秒（立创板未单独测）。显示任务优先级低于语音处理，以保证声音不卡，所以说话时偶尔会有 100ms 左右的停顿。
- 手势阈值是按测试板调的，换一种握持方式可能需要微调。
- 只能在局域网内用，电脑必须开着。
- MQTT 路径参与了编译，但没有单独做实机网络验收。

## 来源与许可

- 固件基于 [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)，后端基于 [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)，都是 MIT 许可证。
- 源码快照不含上游的 Git 历史。上游基线提交记录在 `UPSTREAM.json`。

真实密钥、Wi-Fi 配置、Flash 备份、模型权重、运行日志和对话内容都只留在本机，不在这个仓库里。
