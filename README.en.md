[中文](README.md) | English

# Zongzhu Bot

![Zongzhu: a desktop voice terminal with a pair of white eyes on a black round screen](docs/images/banner.jpg)

[![Firmware](https://img.shields.io/badge/firmware-2.5.2.9-black)](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest)
[![Board](https://img.shields.io/badge/board-Waveshare_1.75C_|_Lichuang_SZPI_S3-blue)](#what-you-need)
[![Speaker](https://img.shields.io/badge/optional-Xiaomi_Smart_Speaker_Pro-orange)](#xiaomi-smart-speaker-pro-optional-experimental)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Talk to the board: tasks go to your Grok Bot, while playing music, pausing and volume run on your computer right away.**

[Full guide](docs/GUIDE.en.md) · [All docs](docs/README.md) (Chinese) · [Web flasher](https://liu-zhongxian.github.io/zongzhu-bot/)

---

Zongzhu has two parts: an ESP32-S3 screen board, and a backend that runs on your computer.

- **The board** listens and speaks. Its screen is a pair of eyes that blink, follow your finger, and get dizzy when you shake it.
- **The backend** recognizes speech, and its gateway decides who gets each sentence.
- A **Xiaomi Smart Speaker Pro** with patched firmware can join too. It works like a Zongzhu board without a screen.

```
Zongzhu board ─┐                    backend on your computer
               ├─ voice ─▶ recognize → gateway ┬ music, pause, volume → runs on this computer
Xiaomi speaker ┘                               └ everything else → Grok Bot ─▶ works, replies ─▶ read aloud
                          gateway page: status, devices, firmware updates (in a browser)
```

> A community project built on the open-source Xiaozhi firmware and backend. Not an official Xiaozhi, Grok or xAI project.

> **Language note:** the wake word, speech recognition, on-screen system messages and the instructions sent to the Bot are Chinese-first. The project is built and tested for Mandarin speakers.

## Features

### Hand tasks to your Grok Bot

- **Just say it**: after the wake word, say what you need, e.g. "帮我把这周的 X 热点整理一下" (sum up this week's X trends). No prefix needed.
- **Waits with you**: the screen counts the seconds while you wait. The reply is read aloud when it arrives and stays on screen; long replies scroll.
- **Nothing lost**: replies that arrive while disconnected are delivered on the next connection. Saying the wake word again mid-conversation only gets a short "我在" (I'm here), not a new task.
- **Pick who gets it**: say "嗨" (hi) plus the Bot's name, and the rest goes straight to that Bot. You can change the names on the gateway page, including spellings it often mishears.

### Gateway page

Open `http://<computer address>:8003/gateway` in a browser. Phones and computers on your LAN can view it. The page never shows any key.

- **Overview**: which boards are online and what they are doing (listening, speaking, seconds spent waiting for the Bot), and whether each module is healthy.
- **Recent sentences**: who got each sentence, how long until it spoke, and what the AI replied.
- **Devices**:
  - See the board's Wi-Fi signal, IP, version and memory.
  - Set volume and brightness, and reboot the board.
  - Change the wake word without reflashing.
  - Control the Xiaomi speaker: volume, play / pause, make it say something, interrupt XiaoAI.
- **Handed-over tasks**: every task given to the Bot, listed separately as waiting, replied, read aloud or timed out.
- **How it works**: draws, from your current config, each step a sentence takes from the microphone to the reply.
- **Firmware updates**: upload firmware for your own board on the page, then choose "update now" or "update at next boot". Model, chip and version are checked before upload, so firmware for the wrong board is refused.

### Automatic firmware updates

When the project publishes new firmware, your backend gets it automatically, and your board updates at its next boot.

- Published firmware is signed by the project owner, and the backend checks it with the public key built into the code. A wrong signature or a modified file is refused.
- Your backend downloads only the models your own boards use, then checks the size, SHA-256 and the firmware contents.
- Published firmware carries nobody's backend address, so after the update your board still connects to your own backend.
- On by default. Turn it off on the page, or set `gateway.firmware_releases: false` in the config.

### Local music (optional, off by default)

- **Ask for a song**: e.g. "放周杰伦的晴天" (play Jay Chou's Sunny Day) or "来一首孤勇者". About 1.5 seconds later it plays on the computer and the title shows on the screen.
- **Control it casually**: pause, next, "快进五秒" (skip ahead 5 seconds), play from the start, repeat one, "音量调到三十" (volume to 30), "who sings this?".
- **Finds the original**: NetEase Cloud Music is searched first. If it lacks the original, QQ Music, Kugou, Kuwo and Migu are searched together. Covers, live versions, remixes and look-alike uploaders are skipped, and among identical versions the best bitrate wins.
- **Survives misrecognition**: a title heard wrong ("请帖" for "晴天") is matched by pronunciation.
- **Leaves the Bot's work alone**: "pause that download task" or "keep writing yesterday's report" still go to the Bot.

### Xiaomi Smart Speaker Pro (optional, experimental)

After you flash the open-xiaoai patched firmware, the speaker connects straight to the Zongzhu backend, and XiaoAI keeps working.

- Say "宗主" or the Bot's name. What you say next goes to the Bot, and the answer is spoken by the speaker.
- You can interrupt the speaker while it is speaking and ask something new. Once the new answer is done, it finishes what it was saying before.
- Tested end to end only on the OH2P with firmware 1.62.2. Flashing can brick the speaker. The steps are in the [GUIDE](docs/GUIDE.en.md#xiaomi-smart-speaker-pro-optional); flashing details and the way back are in [zongzhu-speaker](zongzhu-speaker/README.md) (Chinese).

### Accurate recognition, a living screen

- **Recognition**: local, offline speech recognition (X-ASR) that handles mixed Chinese and English.
- **Corrections**: hotwords plus corrections after recognition. With local music on, common singers and song titles are added as hotwords too.
- **Expressions**: 13 eye expressions drawn in real time, following the device state. Touch, tilt and shake all get a reaction.
- **Subtitles**: three modes (full / brief / off), switched by a long press on BOOT.

Gestures, the expression list and what you can say for music are in the [full guide](docs/GUIDE.en.md).

## What you need

- **Board** (pick one):
  - Waveshare ESP32-S3-Touch-AMOLED-1.75C;
  - Lichuang (立创) SZPI ESP32-S3 ([notes](docs/BOARD-SZP.md), Chinese).
  - An M5Stack StopWatch build exists too, but hasn't run on a real board yet ([notes](docs/BOARD-STOPWATCH.md), Chinese).
- **Computer**: an always-on Mac (verified on Apple Silicon) runs the backend. It must be on the same 2.4 GHz LAN as the board. On Windows or Linux, [run it in Docker](deploy/docker/README.md) (everything but local music) or [on a public server](deploy/README.md) (both Chinese).
- **Bot**: your Grok Bot must expose a webhook **and be able to write files on this computer**, or replies never reach the board ([interface](docs/GUIDE.en.md#bot-interface)).

## Getting started

1. On your computer, open the **[web flasher](https://liu-zhongxian.github.io/zongzhu-bot/)** in Chrome or Edge and connect the board over USB.
2. The first time, install the backend: the page shows a one-line command to paste into Terminal. It:
   - installs dependencies;
   - downloads the speech model (about 200MB);
   - asks for your Bot webhook;
   - prints the computer address to enter back on the page.
3. Back on the page, go through the six steps: detect the board, pick the wake word, pick the style, enter the backend address, enter Wi-Fi, flash and check the connection.
4. Say "你好宗主", then your request. If the screen starts counting seconds and the Bot's reply is read aloud when it arrives, everything is working.
5. Open the gateway page at `http://<computer address>:8003/gateway` and check that the board shows as online.

For local music:

```sh
bash tools/local_music_setup.sh    # downloads go-music-dl and mpv into local-music/, checks their SHA-256
```

Then turn on `local_music` in the backend config as the script tells you, and restart the backend. For NetEase members-only songs, sign in by QR code in go-music-dl's web page. Details: [full guide · local music](docs/GUIDE.en.md#local-music-optional).

If you'd rather not use the web page, want to build the firmware yourself, or the page doesn't work for you, see [manual setup](docs/GUIDE.en.md#manual-setup-without-the-web-page).

## Security

- **Use it on your LAN only**:
  - Don't expose the backend's ports 8000 and 8003 to the internet.
  - On a server, follow the [deployment notes](deploy/README.md): the backend listens on 127.0.0.1 only and the device allowlist is on.
  - To keep people on your LAN from changing settings, set `gateway.password` and the gateway page will ask for it first.
- **Whatever your Bot can do, a voice command can make it do**:
  - What the board hears goes to your Bot as is. Whatever permissions the Bot has (sending messages, changing files, spending money), a voice command can use them.
  - The webhook URL and token live in `private/` (mode 600); never commit them.
- **Firmware updates**:
  - Automatic updates accept only releases signed by the project owner. The signing key is not in this repository, so nobody else can publish one.
  - Everyone else can update only their own boards, from their own gateway page.
- **Local music**:
  - go-music-dl listens on port 18080 on every network interface. While the backend runs, any device on your LAN can use it to search for and download music.
  - Sign-in cookies stay in `local-music/go-music-dl/data/`, which is not in Git.
  - The music comes from the platforms' unofficial interfaces; keep it to personal use.
- **Xiaomi speaker**:
  - Flashing can brick it. Make the read-only backup first, and write only one of the two A/B system slots.
  - The patched firmware enables root SSH (you set the password) and turns off Xiaomi's automatic updates.
  - The speaker and the backend authenticate with a token. Keep the backend's port 4399 on your LAN.

## Documentation

| | |
| --- | --- |
| [docs/GUIDE.en.md](docs/GUIDE.en.md) | Full guide: features, the gateway page, local music, the Xiaomi speaker, manual setup, flashing, troubleshooting, Bot interface, building, tests, known limitations |
| [docs/README.md](docs/README.md) | Index of all docs, including board notes (Chinese) |
| [deploy/docker/README.md](deploy/docker/README.md) | Running the backend in Docker (Chinese) |
| [deploy/README.md](deploy/README.md) | Deploying to a public server (Chinese) |
| [zongzhu-speaker/README.md](zongzhu-speaker/README.md) | Xiaomi Smart Speaker Pro: flashing and the Client (Chinese) |

## About this repository

This project's own changes are in:

| Part | Where |
| --- | --- |
| Firmware | `xiaozhi-esp32/main/boards/common/zongzhu/` and the board directories |
| Backend | under `xiaozhi-esp32-server/main/xiaozhi-server/core/`:<br>`gateway/`: the gateway and its page; music in `gateway/skills/music/`, the Xiaomi speaker in `gateway/xiaoai/`, firmware releases in `gateway/releases.py`<br>`handle/grokBot*.py`: sending to the Bot and its replies<br>`utils/asr_text.py`: hotwords and corrections |
| The speaker side | `zongzhu-speaker/`: patches, the Client source, flashing and install scripts |
| Everything else | `web/` (web flasher), `tools/` (building and publishing firmware, changing the wake word), `deploy/` (server, Docker), `examples/`, `docs/` |

The rest of the two upstream directories is kept mostly as is, so later upstream merges stay simple and the project keeps up with Xiaozhi firmware updates. Upstream base commits are in `UPSTREAM.json`.

## Credits and license

- This project's code: [MIT License](LICENSE).
- The firmware is based on [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) and the backend on [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server), both MIT.
- Local music uses [go-music-dl](https://github.com/guohuiyuan/go-music-dl) (AGPL-3.0) and [mpv](https://github.com/mpv-player/mpv). Neither is in this repository: `tools/local_music_setup.sh` downloads them from their release pages, and they run as separate programs under their own licenses.
