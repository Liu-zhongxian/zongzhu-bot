# 宗主 ESP32 × Grok Bot

用 Waveshare ESP32-S3-Touch-AMOLED-1.75C 向已有 Grok Bot 下达语音指令，再把 Bot 的回复送回圆屏并朗读。当前固件 **2.5.2.3**，唤醒词 **你好宗主**。

这个项目连接的是 Bot 的 Webhook，不调用 xAI Chat Completions。需要一台保持运行、与板子局域网互通的电脑；Bot 必须能在该电脑本机写文件。仅有 xAI API Key 无法代替这两项能力。

## 已实现

- 语音识别后直接提交 Bot，无需“让机器人”前缀；唤醒词使用本地回复。
- Bot 将实际回答写入关联的本机 JSON 文件，后端校验后回传字幕和 EdgeTTS 音频。
- 提交后显示等待秒数并暂停普通收音；唤醒或按键可追加。默认等待 300 秒，超时保留任务，不自动重发。
- 圆屏保留 25 组 IKUN 动画，有文字时扩大正文区域，长文字滚动；朗读结束保留完整回复。下一轮通过唤醒或按键开始。
- 回复期间保持连接，未送达的回复可在下次连接时补送；同一设备相同指令有 30 秒进程内去重。

链路：板子 → 本机 FunASR → Bot Webhook → 本机回复文件 → 后端 → 圆屏字幕与扬声器。

## 文件

| 路径 | 内容 |
| --- | --- |
| `xiaozhi-esp32/` | 含宗主 UI、唤醒词、动画资源及 bot_ui 协议的完整固件源码 |
| `xiaozhi-esp32-server/main/xiaozhi-server/` | 实际运行的 Python 后端源码，含 Bot 桥接与测试 |
| `firmware/zongzhu-1.75c-2.5.2.3/` | 已验证的分段固件、校验值、构建和验收记录 |
| `examples/` | 不含真实凭证的配置模板 |
| `docs/TASK-RECORD.md` | 脱敏后的实施过程与历次验收记录 |
| `docs/VALIDATION.md` | 当前版本测试范围及限制 |
| `UPSTREAM.json` | 两个上游项目的来源与基线提交 |

## 本机部署（已在 Apple Silicon macOS 验证）

以下操作均从本仓库根目录开始。使用 Python 3.10；另外需要 FFmpeg、Opus，macOS 可用 `brew install python@3.10 ffmpeg opus` 安装。首次安装依赖和下载模型需要网络。

```sh
python3.10 -m venv .venv
.venv/bin/python -m pip install -r requirements-macos.txt
mkdir -p logs private/bot-replies xiaozhi-esp32-server/main/xiaozhi-server/data
chmod 700 private private/bot-replies
cp examples/backend.config.yaml xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml
cp examples/grok-bot-webhook.example.json private/grok-bot-webhook.json
chmod 600 private/grok-bot-webhook.json xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml
.venv/bin/python - <<'PY'
from pathlib import Path
import json
root = Path.cwd()
p = root / 'private/grok-bot-webhook.json'
data = json.loads(p.read_text())
data['reply_dir'] = str(root / 'private/bot-replies')
p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
PY
```

编辑私有 JSON，填写已有 Bot Webhook 的 URL 和 Bearer 令牌。编辑私有 YAML，将 `192.168.1.100` 替换为电脑的局域网 IP；保持 `LLM: BotOnly`、`Intent: nointent`，无需配置模型 API Key。

下载未随仓库分发的 SenseVoiceSmall 权重到后端目录（较大，需要一些时间）：

```sh
.venv/bin/python - <<'PY'
from modelscope import snapshot_download
snapshot_download('iic/SenseVoiceSmall', local_dir='xiaozhi-esp32-server/main/xiaozhi-server/models/SenseVoiceSmall')
PY
./start.sh
```

`start.sh` 在前台运行，关闭终端会停止服务；没有安装开机自启。不要同时启动多个实例。`requirements-macos.lock.txt` 保留原验收环境的依赖快照，常规安装使用 `requirements-macos.txt`。

板子配网时选择与电脑可互访的 2.4GHz Wi-Fi，OTA 地址填 `http://电脑局域网IP:8003/xiaozhi/ota/`。电脑 IP 改变后同时更新 YAML 中的 WebSocket 地址和板子的 OTA 地址。

## Bot 的要求

已有 Bot 自动化需要接受 `Authorization: Bearer ...` 的 HTTPS POST，处理 JSON 中的 `command`，成功接受后返回包含 `success: true` 和 `runUuid` 的响应。此实现针对当前已验证的接口契约，不是任意 Webhook 的通用适配器。

后端会在 command 中附上实际用户请求和回传约定：Bot 用已有的本机文件能力，将 UTF-8 JSON `{"request_id":"ESP32-...","text":"实际回答"}` 写入指定绝对路径。先写临时文件再重命名。回复不能只放在云端同名路径或 Bot 聊天窗口中。Bot 的其他操作继续遵守它自身已有的授权规则。

`reply_dir` 必须是绝对路径；可在私有 JSON 调整 `reply_wait_seconds`。已提交不等于已完成；`.sent.json` 只表示后端已交给播放队列，不代表取得硬件播放确认。

## 固件安装与构建

本包对应 **1.75C**，不要用于其他板型。完整分段包不会写 NVS，但会初始化 OTA 选择数据。刷入前备份自己的设备配置，确认串口与板型。校验并安装：

```sh
cd firmware/zongzhu-1.75c-2.5.2.3
shasum -a 256 -c SHA256SUMS
esptool --chip esp32s3 --port /dev/cu.YOUR_PORT --baud 921600 write-flash @flash_args
```

本次已验收实体板只更新了当前分区 0 的应用。其他设备不得据此假定当前活动分区相同，不要直接照抄应用地址覆盖未知分区。

从源码构建时先安装并加载 ESP-IDF >= 6.0.1 环境（本版实测 6.0.1），然后：

```sh
cd xiaozhi-esp32
python scripts/build.py waveshare/esp32-s3-touch-amoled-1.75 --name esp32-s3-touch-amoled-1.75c
```

## 测试

```sh
cd xiaozhi-esp32-server/main/xiaozhi-server
../../../.venv/bin/python -m unittest tests.test_grok_bot tests.test_grok_bot_reply -v
```

根目录的 `verify_bot_bridge.py`、`verify_bot_reply.py`、`verify_bot_speech.py` 会真实调用已配置的 Bot，仅用于你授权的测试环境；先启动后端。`verify_bot_speech.py` 会生成 `logs/bot-reply-speech.wav`。随后可运行 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python verify_bot_wait_display.py`：它使用上述音频和本机测试回复文件，正常通过时不会调用 Webhook。

现场验收：说“你好宗主”，等回应后说“请回复三句话，介绍宗主现在的等待和朗读功能”。观察等待秒数、正文朗读和读完后文字保留。当前版本这三项已由用户现场确认正常；其余细分测试范围见 [验证记录](docs/VALIDATION.md)。

## 来源与边界

固件基于 [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)，后端基于 [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)。本仓库是带本次修改的源码快照，保留上游 MIT 许可证、署名及各资源原有说明；未复制上游 Git 历史。后端只收录运行所需的 Python 服务，不包含上游管理后台和移动端。

IKUN 动画来自本项目已有角色与 AI 生成图集，本项目非硬件厂商或相关人物的官方产品。真实密钥、Wi-Fi 配置、NVS/整机备份、模型权重、运行日志、对话音频和原始 Bot 回复均留在本机，不随仓库分发。
