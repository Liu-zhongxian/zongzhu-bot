[中文](README.md) | English

# Zongzhu Bot

![Zongzhu: a desktop voice terminal with a pair of white eyes on a black round screen](docs/images/banner.jpg)

[![Firmware](https://img.shields.io/badge/firmware-2.5.2.9-black)](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest)
[![Board](https://img.shields.io/badge/board-Waveshare_ESP32--S3--Touch--AMOLED--1.75C-blue)](#prerequisites)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Zongzhu (宗主) turns a 466×466 round-screen ESP32 board into a voice terminal for Grok Bot. Say the wake word "你好宗主" (*ni hao zongzhu*), speak your request, and the Bot's answer comes back to the screen and is read aloud. The screen is a pair of white eyes on black that blink, follow your finger, and get dizzy when you shake the board.

> **Language note:** the wake word, speech recognition settings, on-screen system messages and the instructions sent to the Bot are all in Chinese. The project is built and tested for Mandarin speakers.

## Prerequisites

Check all three before you start. If any one is missing, the pipeline won't work:

- **Board**: Waveshare ESP32-S3-Touch-AMOLED-1.75C. The firmware supports this board only.
- **Computer**: an always-on computer that runs the backend (verified on Apple Silicon macOS), on the same 2.4 GHz LAN as the board.
- **Bot**: your Grok Bot must expose a webhook **and be able to write files on this computer**. If the reply only stays in the cloud or in the chat window, the board never receives it.

## Features

**Voice → Bot → reply**

- Whatever you say after the wake word goes straight to the Bot. No "ask the robot to…" prefix needed.
- The Bot writes its answer to a local reply file. The backend validates it and sends subtitles plus EdgeTTS speech back to the board.
- While waiting, the screen shows a seconds counter and normal listening pauses. The default wait is 300 seconds. Timed-out tasks are kept, not resent. You can add to a request by waking it again or pressing the button.
- Long replies scroll automatically, and the full text stays on screen after playback. Replies that couldn't be delivered while the board was disconnected are sent when it reconnects.
- Saying the wake word again mid-conversation (including misrecognitions such as "你好中主" or "你好宗猪") just gets "我在" ("I'm here") and is not submitted as a task. "你好宗主, check the weather for me" has the wake word stripped and only submits "check the weather for me".

**Eye expressions**

- 13 expressions drawn in real time, switching automatically with the device state and the emotion reported by the server.
- Blinks close fast and open slowly, sometimes twice in a row. The eyes glance around at random while idle, listening or speaking.
- The eyes are drawn as solid shapes, and each frame only redraws the area the eyes moved through. No image sequences.

<details>
<summary>The 13 expressions</summary>

Idle, listening, thinking, speaking, happy (arc ∩), excited, curious, confused, angry, surprised, sad, sleepy (squint ∪), dizzy.

</details>

**Subtitle modes**: long-press BOOT to cycle. The setting survives power-off.

| Mode | What's shown |
| --- | --- |
| Full | What you said and the Bot's full text, auto-scrolling; eyes shrink |
| Brief | Only the first sentence of the reply, up to two lines; medium eyes |
| Off | No conversation text; largest eyes |

System messages for Wi-Fi setup, activation and updates are always shown in full, as is the waiting counter.

**Touch, motion and buttons**

<details>
<summary>Show the gesture table</summary>

| Action | Reaction |
| --- | --- |
| Tap | Happy |
| Double tap | Surprised |
| Long press | Angry |
| Press and drag | Eyes follow your finger |
| Swipe left / right | Cycle expressions |
| Swipe up / down | Surprised / sleepy |
| Tilt the board | Gaze follows the tilt |
| Shake hard left-right 4 times | Dizzy, recovers once still |
| BOOT short press | Start talking; stops playback if something is playing |
| BOOT long press | Cycle subtitle mode |

Reactions last 2–3 seconds, then the eyes return to the current state (listening, thinking, speaking, etc.). Touching the screen also wakes it from power-saving dim. The board has no vibration motor, so there is no haptic feedback.

</details>

## How it works

![Architecture: the board streams voice to the backend, which transcribes it and hands it to Grok Bot via webhook; the Bot writes its reply to a file on the computer, and the backend sends subtitles and speech back to the board](docs/images/architecture.svg)

## Quick start

### 1. Get the firmware

Download `zongzhu-1.75c-2.5.2.9.zip` from [Releases](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest), or use `firmware/zongzhu-1.75c-2.5.2.9/` in this repo.

### 2. Backend

You need Python 3.10, FFmpeg and Opus (`brew install python@3.10 ffmpeg opus`). Run everything from the repo root:

```sh
python3.10 -m venv .venv
.venv/bin/python -m pip install -r requirements-macos.txt
mkdir -p logs private/bot-replies xiaozhi-esp32-server/main/xiaozhi-server/data
chmod 700 private private/bot-replies
cp examples/backend.config.yaml xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml
cp examples/grok-bot-webhook.example.json private/grok-bot-webhook.json
chmod 600 private/grok-bot-webhook.json xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml
```

Then edit two config files:

- `private/grok-bot-webhook.json`: fill in the webhook `url` and `token`; set `reply_dir` to `<absolute repo path>/private/bot-replies` (`echo "$PWD/private/bot-replies"` prints it).
- `xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml`: replace every `192.168.1.100` with the computer's LAN IP (`ipconfig getifaddr en0` on macOS). Keep `LLM: BotOnly` and `Intent: nointent`. No model API key is needed.

Download the speech recognition model and start:

```sh
.venv/bin/python - <<'PY'
from modelscope import snapshot_download
snapshot_download('iic/SenseVoiceSmall', local_dir='xiaozhi-esp32-server/main/xiaozhi-server/models/SenseVoiceSmall')
PY
./start.sh
```

`start.sh` runs in the foreground; closing the terminal stops the service. Don't run more than one. The backend uses port 8000 (WebSocket) and 8003 (HTTP/OTA).

### 3. Flash the firmware

Connect the board over USB-C, find the serial port, and back up the whole flash first so you can restore it:

```sh
ls /dev/cu.usbmodem*
esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX read-flash 0 ALL zongzhu-backup.bin
```

Then verify and write:

```sh
cd firmware/zongzhu-1.75c-2.5.2.9
shasum -a 256 -c SHA256SUMS
esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX --baud 921600 write-flash @flash_args
```

The full image set does not touch NVS (Wi-Fi and other settings are kept), but it resets the OTA boot selection to partition 0. If the port doesn't show up or the connection fails, hold BOOT while plugging in USB to enter download mode, then retry.

### 4. Wi-Fi setup

After boot, join the board's hotspot and pick a 2.4 GHz Wi-Fi network that can reach the computer. Set the OTA URL to `http://<computer LAN IP>:8003/xiaozhi/ota/`.

### 5. Try it

Say "你好宗主", wait for the response, then make a request. The screen first shows the waiting counter; once the Bot writes the reply file, the board starts reading it aloud. That means the whole pipeline works.

## Troubleshooting

| Symptom | Check first |
| --- | --- |
| Board never connects | Board and computer on the same subnet; the IP in `.config.yaml` and in the board's OTA URL is the computer's current IP; macOS firewall allows Python on ports 8000/8003 |
| Computer's IP changed | Update two places: the WebSocket URL in `.config.yaml` and the OTA URL on the board's setup page |
| "Task submitted" but no reply ever arrives | The Bot didn't write the file on this computer. Make sure it has local file write access, writes under `reply_dir`, and the `request_id` in the file matches the request |
| Screen says the Bot rejected the request | The webhook returned 4xx; check `url` and `token` |
| Screen says the reply directory is unavailable | `reply_dir` isn't an existing, writable absolute path |
| Wake word misfires or won't trigger | Threshold is `CONFIG_CUSTOM_WAKE_WORD_THRESHOLD` in the board's `config.json` (currently 20; lower is more sensitive but misfires more). Rebuild after changing it |
| Gaze moves opposite to the tilt | Adjust `QMI8658_SCREEN_X/Y` in `config.h` and rebuild |

## Bot interface

The backend sends an HTTPS POST to the webhook with `Authorization: Bearer <token>`. The body looks like this:

```json
{
  "command": "Instructions in Chinese, including the user's words, the reply path and format",
  "user_text": "帮我查一下明天的天气",
  "request_id": "ESP32-3f2a…",
  "device": "board device ID",
  "source": "zongzhu-voice"
}
```

`command` already contains the full instructions for the Bot, including the absolute path of the reply file. The Bot must:

1. Return `{"success": true, "runUuid": "..."}` as soon as it accepts the task.
2. When done, write the answer as UTF-8 JSON to that path, **writing a temp file in the same directory first and then renaming it**:

   ```json
   {"request_id": "ESP32-3f2a…", "text": "the actual answer, plain text, up to 2000 characters"}
   ```

Subtitles and speech are pushed only after the backend sees the file. A `.sent.json` file only means the reply was handed to the playback queue, not that the board actually played it.

## Build from source

Load an ESP-IDF 6.0.1+ environment (this release was tested with 6.0.1). The source path must not contain non-ASCII characters.

```sh
cd xiaozhi-esp32
python scripts/build.py waveshare/esp32-s3-touch-amoled-1.75 --name esp32-s3-touch-amoled-1.75c
```

## Repository layout

| Path | Contents |
| --- | --- |
| `xiaozhi-esp32/` | Full firmware source; this project's changes live in `main/boards/waveshare/esp32-s3-touch-amoled-1.75/` |
| `xiaozhi-esp32-server/main/xiaozhi-server/` | The Python backend that actually runs; the Bot bridge is `core/handle/grokBotHandle.py` |
| `firmware/zongzhu-1.75c-2.5.2.9/` | Prebuilt image set, checksums, build info |
| `examples/` | Config templates without real credentials |
| `docs/TASK-RECORD.md` | Redacted implementation log and acceptance records (Chinese) |
| `docs/VALIDATION.md` | Test scope and limits of the current release (Chinese) |
| `verify_*.py` | End-to-end checks against a real Bot |

<details>
<summary>Key board files</summary>

| File | Purpose |
| --- | --- |
| `eye_model.h` | Shapes and motion of the 13 expressions (pure math, no LVGL) |
| `eye_display.h` | Round-screen layout, eye drawing, blinking and gaze, touch gestures, subtitle modes |
| `qmi8658_motion.h` | QMI8658 driver, tilt following and shake detection |
| `config.h` | Pins and IMU axis mapping |
| `config.json` | Build options: wake word, 1 ms tick (`CONFIG_FREERTOS_HZ=1000`) |

</details>

## Tests

```sh
cd xiaozhi-esp32-server/main/xiaozhi-server
../../../.venv/bin/python -m unittest tests.test_grok_bot tests.test_grok_bot_reply -v
```

`verify_bot_bridge.py`, `verify_bot_reply.py` and `verify_bot_speech.py` call the Bot you configured for real. Only use them in a test environment you're authorized for, and start the backend first. `verify_bot_wait_display.py` uses local test files and normally doesn't call the webhook. Per-release results are in [docs/VALIDATION.md](docs/VALIDATION.md).

## Known limitations

- The eyes' motion while speaking is a state-based animation, not synced to volume.
- Animation logic runs at about 35–42 fps. The display task has lower priority than audio so sound never stutters, which means occasional ~100 ms pauses while speaking.
- Gesture thresholds were tuned on the test board and may need adjustment for a different grip.
- LAN only, and the computer must stay on.
- The MQTT path is compiled in but hasn't had its own on-device network test.

## Credits and license

- Firmware is based on [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) and the backend on [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server), both MIT licensed.
- The source snapshots don't include upstream Git history. Upstream base commits are recorded in `UPSTREAM.json`.

Real keys, Wi-Fi settings, flash backups, model weights, runtime logs and conversation content stay on the local machine and are not in this repository.
