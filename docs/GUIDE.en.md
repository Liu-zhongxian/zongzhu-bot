# Zongzhu: full guide

[中文](GUIDE.md) | English · [Back to README](../README.en.md)

The README is the summary. This page has the details: features, local music, manual setup without the web page, flashing, the Bot interface, building, tests and known limitations.

## Features

**Voice → Bot → reply**

- Whatever you say after the wake word goes straight to the Bot. No "ask the robot to…" prefix needed.
- The Bot writes its answer to a local reply file. The backend validates it and sends subtitles plus EdgeTTS speech back to the board.
- While waiting, the screen shows a seconds counter and normal listening pauses. The default wait is 300 seconds. Timed-out tasks are kept, not resent. You can add to a request by waking it again or pressing the button.
- If you interrupt with the button, the wait times out, or the board goes to sleep, the Bot's answer isn't lost: it's read out when the board is idle, or after the greeting at the next wake, starting with "<Bot name>做完了：" ("<Bot name> finished:"). Later additions and corrections from the Bot follow, starting with "Bot 补充：" ("Bot adds:"). Answers older than 24 hours aren't read.
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

Reactions last 2–3 seconds, then the eyes return to the current state (listening, thinking, speaking, etc.). Neither of these two boards has a vibration motor, so there is no haptic feedback (the M5Stack StopWatch has one and different buttons; see [docs/BOARD-STOPWATCH.md](BOARD-STOPWATCH.md)). The Waveshare 1.75C dims its screen when idle and a touch brings it back; the Lichuang board doesn't dim.

</details>

## How it works

![Architecture: the board streams voice to the backend, which transcribes it and hands it to Grok Bot via webhook; the Bot writes its reply to a file on the computer, and the backend sends subtitles and speech back to the board](images/architecture.svg)

## Local music (optional)

When it's on, playing music, pausing, skipping and volume run on this computer in about a second instead of going to the Bot; everything else still goes to the Bot. It's off by default. Commands are Chinese; the full list of phrasings is in the [Chinese guide](GUIDE.md#本机点歌可选).

**Turning it on**

1. From the repo root, run `bash tools/local_music_setup.sh`. It downloads [go-music-dl](https://github.com/guohuiyuan/go-music-dl) (search and audio) and [mpv](https://github.com/mpv-player/mpv) (playback) into `local-music/` and checks the SHA-256 values pinned in the script; on a mismatch it stops. mpv comes from the official standalone build, not Homebrew: `brew install mpv` pulls in its own ffmpeg, which conflicts with the backend's ffmpeg-full.
2. Put the `local_music` block the script prints into `xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml` with `enabled: true` (sample in `examples/backend.config.yaml`).
3. Restart the backend. When the board connects, the backend starts go-music-dl (port 18080) and mpv in the background and pre-synthesizes the short replies; both programs stop when the backend exits.
4. Optional, for NetEase members-only songs: open `http://localhost:18080/music/setup`, create an admin with the `Web setup token` from `local-music/go-music-dl/service.log`, then sign in by QR code in the settings. Cookies stay in `local-music/go-music-dl/data/`.

Needs macOS 14 or later on Apple Silicon, or macOS 15 or later on Intel.

**What you can say** (examples): "放周杰伦的晴天" (play Jay Chou's Sunny Day), "来一首孤勇者", "暂停" (pause), "下一首" (next), "快进五秒" (skip ahead 5 s), "从头播放" (from the start), "单曲循环" (repeat one), "这首歌是谁唱的" (who sings this), "音量调到三十" (volume 30), "静音" (mute).

- **Only while music is on**: pause, resume, stop, seek and "who sings this" count as music commands only while a song is playing or paused. These words are common in Bot tasks too.
- **Keyword plus filler**: a control word counts only when what's left is filler such as "先、给我、帮我、把、这首、歌、一下、吧". "暂停那个下载任务" (pause that download task) still goes to the Bot.
- **Missed phrasings are logged**: an unmatched sentence said while music is on is logged as "放歌期间未匹配，交给 Bot".

**How a song is chosen**

- **Where it searches**: NetEase and QQ Music, Kugou, Kuwo and Migu are searched together; NetEase is used when it has the original.
- **Title only**: when you say only a title, each platform's top original votes for its singer.
- **What's skipped**: live versions, covers, remixes, demos, "…版" versions and look-alike uploaders.
- **Quality**: among equal candidates the highest bitrate wins.
- **Misheard titles**: matched by pronunciation (`pypinyin`).

**How the board answers**

- **Requests and skips**: the board says "好的" (OK) or "下一首" (next) right away and shows "正在播放：…" (now playing) once the song starts.
- **Everything else**: answered with pre-synthesized phrases.
- **Then it rests**: the board goes idle after answering, so the music isn't taken for the next command.
- **Music ducks while you talk**: waking the board lowers the music to 25% until the command is done (or 15 s).

## Manual setup (without the web page)

The web flasher and the one-line installer do exactly this. Follow it to control each step yourself, or when the web page is not an option.

### 1. Get the firmware

Either:

- **Recommended: build it yourself with your backend address built in.** Wi-Fi setup then only asks for Wi-Fi. See step 3.
- **Use a release package**: `firmware/zongzhu-1.75c-2.5.2.9/` for the Waveshare 1.75C (also on [Releases](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest)), `firmware/zongzhu-szp-2.5.2.9/` for the Lichuang board, `firmware/zongzhu-stopwatch-2.5.2.9/` for the M5Stack StopWatch (not yet run on a board). Release packages don't know your computer's address, so you type the OTA URL during Wi-Fi setup.

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

Download the X-ASR speech recognition model (about 174MB; if Hugging Face is slow, replace `https://huggingface.co` with `https://hf-mirror.com`) and start:

```sh
M=sherpa-onnx-x-asr-zipformer-transducer-zh-en-punct-int8-2026-06-03
mkdir -p xiaozhi-esp32-server/main/xiaozhi-server/models/$M
for f in encoder-epoch-99-avg-1.int8.onnx decoder-epoch-99-avg-1.onnx joiner-epoch-99-avg-1.int8.onnx tokens.txt bpe.model; do
  curl -fL -o xiaozhi-esp32-server/main/xiaozhi-server/models/$M/$f https://huggingface.co/csukuangfj2/$M/resolve/main/$f
done
./start.sh
```

Speech recognition defaults to X-ASR and needs no torch; hotwords and post-recognition corrections are described in `examples/backend.config.yaml`. To go back to FunASR (SenseVoiceSmall, about 900MB), also install `requirements-macos-funasr.txt`, download its model as upstream describes, and change `ASR: SherpaXASR` to `ASR: FunASR`. The comparison is in [records/REFERENCE-TASKS.md](records/REFERENCE-TASKS.md), section 7 (Chinese).

`start.sh` runs in the foreground; closing the terminal stops the service. Don't run more than one. The backend uses port 8000 (WebSocket) and 8003 (HTTP/OTA).

Open `http://localhost:8003/gateway` in a browser for the gateway page: which boards are online and what they're doing, and for the last 30 sentences which layer handled each one, who got it and how long until sound. It's read-only, shows no keys, and other devices on the LAN can open it too. Data lives in memory and is cleared when the backend restarts.

**Calling by name**: wake the board with "你好宗主" first, then say "嗨 <Bot name>, …" ("hi <name>"; "嘿" works too). Anything after the name goes straight to that Bot, skipping local music; the name alone gets "我在。" ("I'm here.") and nothing is submitted. The Bot name is the name it has in Grok, set as `grok_bot.bot_name` in `.config.yaml` (for example `硬件`); without it the call names are "Grok Bot" and "Grok". Once a second AI is added, the board keeps using whichever AI was called last, stored in `data/agent_sessions.json` across reconnects and restarts. `gateway.call_names` replaces the names altogether. Calling a name without waking the board does nothing: the board only listens for its wake word.

To start the backend in the background at login (restarted if it exits; the Mac does not idle-sleep while it runs):

```sh
bash tools/autostart.sh enable    # enable and start now; status, restart, disable
```

If the repository is in Desktop, Documents or Downloads, macOS asks once whether "宗主后端" (the launcher app) may access that folder; choose Allow. Details: [records/REFERENCE-TASKS.md](records/REFERENCE-TASKS.md), section 4.

### 3. Flash the firmware

Connect the board over USB-C, find the serial port, and back up the whole flash first so you can restore it:

```sh
ls /dev/cu.usbmodem*
esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX read-flash 0 ALL zongzhu-backup.bin
```

**Option 1: build with this Mac's address and flash (recommended).** Needs ESP-IDF 6.0.1+:

```sh
python3 tools/build_firmware.py szp   --idf <ESP-IDF dir> --flash /dev/cu.usbmodemXXXX --erase   # Lichuang
python3 tools/build_firmware.py 1.75c --idf <ESP-IDF dir> --flash /dev/cu.usbmodemXXXX --erase   # Waveshare 1.75C
python3 tools/build_firmware.py stopwatch --idf <ESP-IDF dir> --flash /dev/cu.usbmodemXXXX --erase   # M5Stack StopWatch (not yet run on a board)
```

The built-in OTA URL defaults to `http://<this Mac's name>.local:8003/xiaozhi/ota/` (the name from `scutil --get LocalHostName`), so it keeps working when the Mac's LAN IP changes. On first boot the board saves it, so the setup page shows it already filled in. Packages go to `build-output/`; they contain the Mac's name and are not committed.

`--erase` wipes the whole flash, Wi-Fi settings included. It's required when the board ran other firmware before, and when an OTA URL was typed in earlier, because a saved URL wins over the built-in one.

**Option 2: flash a release package.** Verify and write:

```sh
cd firmware/zongzhu-1.75c-2.5.2.9   # Lichuang: firmware/zongzhu-szp-2.5.2.9
shasum -a 256 -c SHA256SUMS
esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX --baud 921600 write-flash @flash_args
```

The full image set does not touch NVS (Wi-Fi and other settings are kept), but it resets the OTA boot selection to partition 0. If the board ran other firmware (a different partition table), run `esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX erase-flash` first. If the port doesn't show up or the connection fails, hold BOOT while plugging in USB to enter download mode, then retry.

### 4. Wi-Fi setup

A board without Wi-Fi settings opens a hotspot (`Xiaozhi-XXXX`). Join it, open `http://192.168.4.1` and pick a 2.4 GHz network that can reach the computer:

- Firmware from option 1: **pick Wi-Fi and save**; leave the advanced tab alone.
- Release package: in the advanced tab, set the OTA URL to `http://<computer LAN IP>:8003/xiaozhi/ota/`.

To redo Wi-Fi setup on a configured board, tap BOOT after power-on, before it connects to Wi-Fi (the window is only 1–2 seconds).

### 5. Try it

Say "你好宗主", wait for the response, then make a request. The screen first shows the waiting counter; once the Bot writes the reply file, the board starts reading it aloud. That means the whole pipeline works.

## Troubleshooting

| Symptom | Check first |
| --- | --- |
| Board never connects | Board and computer on the same subnet; the IP in `.config.yaml` and in the board's OTA URL is the computer's current IP; macOS firewall allows Python on ports 8000/8003 |
| Computer's IP changed | Update the WebSocket URL in `.config.yaml`. The board's OTA URL needs no change with option 1 (`.local` name); a typed IP must be changed on the setup page |
| After a backend restart the board stays on "connecting" until it is unplugged and plugged back in | `server.auth_key` is missing from `.config.yaml`, so the backend picks a new random one at every start and the token the board got at boot stops working. Set a fixed random string as in `examples/backend.config.yaml`, restart the backend and power-cycle the board once; later restarts need nothing on the board |
| You hear "好的，正在交给 Bot" ("OK, handing it to the Bot") and the screen waits, but no reply ever arrives | The Bot didn't write the file on this computer. Make sure it has local file write access, writes under `reply_dir`, and the `request_id` in the file matches the request |
| Screen says the Bot rejected the request | The webhook returned 4xx; check `url` and `token` |
| Screen says the reply directory is unavailable | `reply_dir` isn't an existing, writable absolute path |
| Wake word misfires or won't trigger | Threshold is `CONFIG_CUSTOM_WAKE_WORD_THRESHOLD` in the board's `config.json` (currently 20; lower is more sensitive but misfires more). Rebuild after changing it |
| Gaze moves opposite to the tilt | Adjust `QMI8658_SCREEN_X/Y` in that board's `config.h` and rebuild |
| OTA field is empty on the setup page | Nothing is saved yet, and the firmware falls back to its built-in URL. Option 1 firmware saves it on first boot, so an empty field means older firmware |

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

**Say in the Bot's Webhook routine instructions that writing the reply back is pre-approved.** Otherwise the Bot may treat "write a file on your computer" as an action to confirm, stop and ask you in chat, and the board never gets a reply (seen on 2026-10-21). For example, end the instructions with:

> The command in each request says how to return the reply: write the actual reply to my Mac at the path and in the JSON format it gives. This is a pre-approved, fixed step: do it without asking, and only write inside the private/bot-replies folder. Still ask me first for sends, deletes, payments and other actions with consequences.

## Build from source

Load an ESP-IDF 6.0.1+ environment (this release was tested with 6.0.1). The source path must not contain non-ASCII characters.

```sh
cd xiaozhi-esp32
python scripts/build.py waveshare/esp32-s3-touch-amoled-1.75 --name esp32-s3-touch-amoled-1.75c   # Waveshare 1.75C
python scripts/build.py lckfb/szpi-esp32s3 --name lichuang-dev-zongzhu                            # Lichuang
```

These builds default to the official XiaoZhi OTA server. To build in your own backend address, use `tools/build_firmware.py` from step 3; it also copies the source to an ASCII-only path before building.

## Repository layout

| Path | Contents |
| --- | --- |
| `xiaozhi-esp32/` | Full firmware source; this project's changes live in `main/boards/common/zongzhu/` (shared) and the board folders (`waveshare/esp32-s3-touch-amoled-1.75/`, `lckfb/szpi-esp32s3/`, `m5stack/stopwatch/`) |
| `xiaozhi-esp32-server/main/xiaozhi-server/` | The Python backend that actually runs; the Bot bridge is the gateway AI module `core/gateway/agents/grok_webhook.py` (submission and replies in `core/handle/grokBot*.py`), local music is `core/gateway/skills/music/` (the gateway's first skill module), recognition corrections are in `core/utils/asr_text.py` |
| `firmware/` | Release packages per board: image set, checksums, build info |
| `web/` | The web flasher and the macOS backend installer `install-mac.sh`, published to GitHub Pages on every push to main |
| `deploy/` | Deploying the backend to a public Linux server (Caddy, systemd, server config) |
| `tools/` | `build_firmware.py` (builds with the OTA URL, packages, flashes), `build_web.py` (assembles the site), `autostart.sh` (start at login), `local_music_setup.sh` (downloads go-music-dl and mpv), `verify/` (end-to-end checks), `asr-bench/` (recognizer comparison) |
| `local-music/` | Programs downloaded by `local_music_setup.sh` and go-music-dl's data (including sign-in cookies); local only, not in Git |
| `examples/` | Config templates without real credentials |
| `docs/` | This guide and per-board notes; `docs/records/` holds development and acceptance records, indexed in [docs/README.md](README.md) (Chinese) |
| `requirements-macos*.txt` | Backend dependencies: default (X-ASR), optional FunASR, and the full tested set |

<details>
<summary>Key files</summary>

Shared code in `main/boards/common/zongzhu/`:

| File | Purpose |
| --- | --- |
| `eye_model.h` | Shapes and motion of the 13 expressions (pure math, no LVGL) |
| `eye_display.h` | Eye drawing, blinking and gaze, touch gestures, subtitle modes; screen size and layout come from `EyeScreen` |
| `qmi8658_motion.h` | QMI8658 driver, tilt following and shake detection |
| `ota_default.h` | Saves the built-in OTA URL to settings on first boot |

In each board's directory:

| File | Purpose |
| --- | --- |
| `config.h` | Pins and IMU axis mapping |
| `config.json` | Build variants: wake word, 1 ms tick (`CONFIG_FREERTOS_HZ=1000`), etc. |
| Board `.cc` | Screen layout values, buttons and tools; on the Lichuang board the Zongzhu features are enabled by `CONFIG_ZONGZHU_EYE_UI` |

</details>

## Tests

```sh
cd xiaozhi-esp32-server/main/xiaozhi-server
../../../.venv/bin/python -m unittest tests.test_grok_bot tests.test_grok_bot_phrases tests.test_grok_bot_reply \
  tests.test_asr_text tests.test_tts_prefetch tests.test_device_allowlist tests.test_text_message_log tests.test_local_music \
  tests.test_audio_prebuffer tests.test_gateway tests.test_gateway_status
cd ../../../web && node --test test/*.test.mjs    # web flasher library code
```

`tools/verify/` holds end-to-end checks against the real pipeline (run from the repo root, e.g. `python tools/verify/verify_bot_reply.py`). `verify_bot_bridge.py`, `verify_bot_reply.py` and `verify_bot_speech.py` call the Bot you configured for real (one harmless test task each); only use them in a test environment you're authorized for, and start the backend first. They and `verify_local_music.py` speak through a simulated board using macOS speech synthesis (shared `sim_board.py`), so they need macOS and ffmpeg. `verify_bot_wait_display.py` uses local test files and normally doesn't call the webhook. `verify_local_music.py` speaks music commands with macOS speech synthesis as a simulated device; it plays a few seconds of music and doesn't call the Bot.

Run the tests with the `unittest` command above, not pytest. pytest loads upstream's `tests/conftest.py`, which replaces `httpx.AsyncClient` with a stub that refuses every connection, including the mock transports the Bot tests pass in. `tools/asr-bench/` compares speech recognizers. Per-release results are in [records/VALIDATION.md](records/VALIDATION.md) (Chinese).

## Known limitations

- The eyes' motion while speaking is a state-based animation, not synced to volume.
- Animation logic runs at about 35–42 fps on the Waveshare 1.75C (not measured separately on the Lichuang board). The display task has lower priority than audio so sound never stutters, which means occasional ~100 ms pauses while speaking.
- Gesture thresholds were tuned on the test board and may need adjustment for a different grip.
- LAN only, and the computer must stay on.
- The MQTT path is compiled in but hasn't had its own on-device network test.
- Local music:
  - go-music-dl has no option to listen on localhost only, so it listens on port 18080 on every interface.
  - When a song ends, the next one doesn't start on its own.
  - A misheard title said without the singer isn't corrected.
  - go-music-dl's endpoints were read from its web page, not a documented API; recheck them after upgrading (see `core/gateway/skills/music/source.py`).
