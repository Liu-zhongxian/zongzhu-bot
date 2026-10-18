# 宗主 ESP32 × Grok Bot

让一块 466×466 圆屏 ESP32 开发板变成 Grok Bot 的语音终端：说「你好宗主」唤醒，直接说需求，Bot 的回答回到屏幕上显示并朗读。屏幕是一对会眨眼、会跟手、会被摇晕的黑底白眼睛。

- 当前固件：**2.5.2.5**
- 硬件：Waveshare ESP32-S3-Touch-AMOLED-1.75C（只适用这块板子）
- 唤醒词：**你好宗主**

## 功能

**语音 → Bot → 回传**

- 唤醒后说的话直接提交给 Bot，不用加"让机器人"之类的前缀。
- Bot 把回答写进本机回复文件，后端校验后把字幕和 EdgeTTS 语音发回板子。
- 等待时显示秒数，并暂停普通收音。默认最多等 300 秒，超时任务会保留，不会自动重发。唤醒或按键可以追加内容。
- 长回复会自动滚动，朗读完后保留全文。连接断开期间没送出的回复，下次连上会补发。

**屏幕表情（2.5.2.5）**

- 13 种程序绘制的眼睛表情：待机、聆听、思考、说话、开心、兴奋、好奇、困惑、生气、惊讶、难过、困倦、眩晕。会跟着设备状态和服务端情绪自动切换。
- 有文字时眼睛缩小，给字幕腾出位置。

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
| BOOT 键 | 开始 / 结束对话 |

反应持续 2–3 秒，之后回到当前状态（聆听、思考、说话等）。碰一下屏幕也会唤醒省电变暗的屏幕。板子没有震动马达，所以没有震动反馈。

## 工作原理

```
板子麦克风 ─▶ 本机后端（FunASR 识别）─▶ Bot Webhook
                                            │
圆屏字幕 + 扬声器 ◀─ 后端（EdgeTTS）◀─ 本机回复文件 ◀┘
```

需要一台一直开着的电脑运行后端，并且和板子在同一个局域网。Bot 必须能往这台电脑写文件。本项目对接的是 Bot 的 Webhook，不调用 xAI Chat Completions，只有 xAI API Key 是不够的。

## 仓库结构

| 路径 | 内容 |
| --- | --- |
| `xiaozhi-esp32/` | 完整固件源码；本项目的改动集中在 `main/boards/waveshare/esp32-s3-touch-amoled-1.75/` |
| `xiaozhi-esp32-server/main/xiaozhi-server/` | 实际运行的 Python 后端，包含 Bot 桥接和测试 |
| `firmware/zongzhu-1.75c-2.5.2.5/` | 编译好的分段固件、校验值、构建记录 |
| `examples/` | 不含真实凭证的配置模板 |
| `docs/TASK-RECORD.md` | 脱敏后的实施过程和每次验收记录 |
| `docs/VALIDATION.md` | 当前版本的测试范围和限制 |
| `verify_*.py` | 连真实 Bot 的端到端验证脚本 |

板级关键文件：

| 文件 | 作用 |
| --- | --- |
| `avatar_round_display.h` | 圆屏布局、眼睛渲染、眨眼、触摸手势、字幕 |
| `kk_avatar.h` | 13 种表情的眼睛形状和动画 |
| `qmi8658_motion.h` | QMI8658 驱动，倾斜跟随和摇晃检测 |
| `config.h` | 引脚和 IMU 轴向映射 |

## 快速开始

### 1. 后端（已在 Apple Silicon macOS 上验证）

需要 Python 3.10、FFmpeg、Opus（`brew install python@3.10 ffmpeg opus`）。下面的命令都在仓库根目录执行：

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

然后改两处配置：

- `private/grok-bot-webhook.json`：填 Bot Webhook 的 URL 和 Bearer 令牌。
- `.config.yaml`：把 `192.168.1.100` 换成电脑的局域网 IP，保持 `LLM: BotOnly`、`Intent: nointent`，不需要模型 API Key。

下载语音识别模型并启动：

```sh
.venv/bin/python - <<'PY'
from modelscope import snapshot_download
snapshot_download('iic/SenseVoiceSmall', local_dir='xiaozhi-esp32-server/main/xiaozhi-server/models/SenseVoiceSmall')
PY
./start.sh
```

`start.sh` 在前台运行，关掉终端服务就停了，不要同时开多个。

### 2. 刷固件

先备份自己板子的配置，确认串口和板型无误：

```sh
cd firmware/zongzhu-1.75c-2.5.2.5
shasum -a 256 -c SHA256SUMS
esptool --chip esp32s3 --port /dev/cu.YOUR_PORT --baud 921600 write-flash @flash_args
```

完整分段包不写 NVS（Wi-Fi 等设置会保留），但会把 OTA 启动选择重置到分区 0。

### 3. 配网

板子开机后连它的热点，选一个和电脑互通的 2.4GHz Wi-Fi。OTA 地址填 `http://电脑局域网IP:8003/xiaozhi/ota/`。电脑 IP 变了的话，YAML 里的 WebSocket 地址和板子的 OTA 地址都要改。

### 从源码构建

加载 ESP-IDF 6.0.1 或更高版本的环境（本版用 6.0.1 实测）。源码路径不能有中文。

```sh
cd xiaozhi-esp32
python scripts/build.py waveshare/esp32-s3-touch-amoled-1.75 --name esp32-s3-touch-amoled-1.75c
```

如果倾斜方向和视线方向是反的，在 `config.h` 里调整 `QMI8658_SCREEN_X/Y`。

## Bot 接口要求

Bot 需要满足以下条件：

- 接受带 `Authorization: Bearer ...` 的 HTTPS POST，读取 JSON 里的 `command`。
- 接受任务后返回 `success: true` 和 `runUuid`。
- 把回答以 UTF-8 JSON `{"request_id":"ESP32-...","text":"实际回答"}` 写到后端指定的绝对路径，先写临时文件再重命名。

回复必须写到这台电脑上。只写在云端或 Bot 聊天窗口里，后端是收不到的。`.sent.json` 只表示已经交给播放队列，不代表板子确实播放了。

## 测试

```sh
cd xiaozhi-esp32-server/main/xiaozhi-server
../../../.venv/bin/python -m unittest tests.test_grok_bot tests.test_grok_bot_reply -v
```

`verify_bot_bridge.py`、`verify_bot_reply.py`、`verify_bot_speech.py` 会真的调用你配置的 Bot，只在你有权限的测试环境里用，运行前先启动后端。`verify_bot_wait_display.py` 用的是本机测试文件，正常情况下不会调用 Webhook。

现场试一下：说"你好宗主"，等它回应后说"请回复三句话，介绍宗主现在的等待和朗读功能"。

## 已知限制

- 说话时眼睛的起伏是按状态播放的动画，不跟音量同步。
- 倾斜方向需要按自己的握持方式确认，手势阈值也可能要微调。
- 只能在局域网内用，电脑必须开着。
- MQTT 路径参与了编译，但没有单独做实机网络验收。

## 来源与许可

- 固件基于 [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)，后端基于 [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)，都是 MIT 许可证。
- 眼睛表情的比例和手势、摇晃阈值参考了 [Trentct/m5stack-stopwatch-avatar](https://github.com/Trentct/m5stack-stopwatch-avatar)。为这块板子重写的相关文件（`kk_avatar.h`、`avatar_round_display.h`、`qmi8658_motion.h`）按原项目的 AGPL-3.0-or-later 发布，见同目录的 `kk-avatar-NOTICE.md` 和 `kk-avatar-LICENSE`。
- 源码快照不含上游的 Git 历史。上游基线提交记录在 `UPSTREAM.json`。

真实密钥、Wi-Fi 配置、Flash 备份、模型权重、运行日志和对话内容都只留在本机，不在这个仓库里。
