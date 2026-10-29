[中文](README.md) | English

# Zongzhu Bot

![Zongzhu: a desktop voice terminal with a pair of white eyes on a black round screen](docs/images/banner.jpg)

[![Firmware](https://img.shields.io/badge/firmware-2.5.2.9-black)](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest)
[![Board](https://img.shields.io/badge/board-Waveshare_1.75C_|_Lichuang_SZPI_S3-blue)](#what-you-need)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Talk to the board: tasks go to your Grok Bot, while playing music, pausing and volume run on your computer right away.**

[Full guide](docs/GUIDE.en.md) · [All docs](docs/README.md) (Chinese) · [Web flasher](https://liu-zhongxian.github.io/zongzhu-bot/)

---

An ESP32-S3 screen board plus a backend that runs on your computer. The board listens and speaks; its screen is a pair of eyes that blink, follow your finger, and get dizzy when you shake it. The backend recognizes speech and decides who gets each sentence:

```
Zongzhu board      ⇄   backend on your computer                ⇄   Grok Bot
listens, speaks,        recognizes speech
eyes                    ├ music and volume → runs on this computer
                        └ everything else → to the Bot, reply read aloud    works, replies
```

> A community project built on the open-source Xiaozhi firmware and backend. Not an official Xiaozhi, Grok or xAI project.

> **Language note:** the wake word, speech recognition, on-screen system messages and the instructions sent to the Bot are Chinese-first. The project is built and tested for Mandarin speakers.

## Features

**Hand tasks to your Grok Bot**

- **Just say it**: after the wake word, say what you need ("帮我把这周的 X 热点整理一下", sum up this week's X trends); no prefix needed.
- **Waits with you**: the screen counts the seconds; the reply is read aloud when it arrives and stays on screen, long replies scroll.
- **Nothing lost**: replies that arrive while disconnected are delivered on the next connection; saying the wake word again mid-conversation only gets a short "我在" (I'm here), not a new task.

**Local music (optional, off by default)**

- **Ask for a song**: "放周杰伦的晴天" (play Jay Chou's Sunny Day), "来一首孤勇者"; about 1.5 seconds later it plays on the computer and the title shows on the screen.
- **Control it casually**: pause, next, "快进五秒" (skip ahead 5 seconds), play from the start, repeat one, "音量调到三十" (volume to 30), "who sings this?".
- **Finds the original**: NetEase Cloud Music first; if it lacks the original, QQ Music, Kugou, Kuwo and Migu are searched together. Covers, live versions, remixes and look-alike uploaders are skipped, and the best bitrate wins.
- **Survives misrecognition**: a title heard wrong ("请帖" for "晴天") is matched by pronunciation.
- **Leaves the Bot's work alone**: "pause that download task" or "keep writing yesterday's report" still go to the Bot.

**Accurate recognition**

- Local, offline speech recognition (X-ASR) that handles mixed Chinese and English.
- Hotwords and post-recognition corrections; with local music on, common singers and song titles are added as hotwords.

**A living screen**

- 13 eye expressions drawn in real time, following the device state; touch, tilt and shake all get a reaction.
- Three subtitle modes (full / brief / off), switched by a long press on BOOT.

Gestures, the expression list and what you can say for music are in the [full guide](docs/GUIDE.en.md).

## What you need

- **Board**: Waveshare ESP32-S3-Touch-AMOLED-1.75C, or the Lichuang (立创) SZPI ESP32-S3 ([notes](docs/BOARD-SZP.md), Chinese). An M5Stack StopWatch build exists but hasn't run on a board yet ([notes](docs/BOARD-STOPWATCH.md), Chinese).
- **Computer**: an always-on Mac (verified on Apple Silicon) runs the backend, on the same 2.4 GHz LAN as the board. A public server works too: [deploy to a server](deploy/README.md) (Chinese).
- **Bot**: your Grok Bot must expose a webhook **and be able to write files on this computer**, or replies never reach the board ([interface](docs/GUIDE.en.md#bot-interface)).

## Getting started

1. Open the **[web flasher](https://liu-zhongxian.github.io/zongzhu-bot/)** in Chrome or Edge on your computer and connect the board over USB.
2. First time only, install the backend: the page shows a one-line command to paste into Terminal. It installs dependencies, downloads the speech model (about 200MB), asks for your Bot webhook, and prints the computer address to enter back on the page.
3. Back on the page, go through the six steps: detect the board, pick the wake word, pick the style, enter the backend address, enter Wi-Fi, flash and check the connection.
4. Say "你好宗主", then your request. The screen counts the seconds while waiting and reads the Bot's reply aloud when it arrives.

For local music:

```sh
bash tools/local_music_setup.sh    # downloads go-music-dl and mpv into local-music/, checks their SHA-256
```

Then turn on `local_music` in the backend config as the script tells you, and restart the backend. For NetEase members-only songs, sign in by QR code in go-music-dl's web page. Details: [full guide · local music](docs/GUIDE.en.md#local-music-optional).

Prefer not to use the web page, want to build the firmware yourself, or the page doesn't work for you: see [manual setup](docs/GUIDE.en.md#manual-setup-without-the-web-page).

## Security

- **Use it on your LAN only.** Don't expose the backend's ports 8000 and 8003 to the internet. On a server, follow the [deployment notes](deploy/README.md): the backend listens on 127.0.0.1 only and the device allowlist is on.
- **Whatever your Bot can do, a voice command can make it do.** What the board hears goes to your Bot as is, with all its permissions (sending messages, changing files, spending money). The webhook URL and token live in `private/` (mode 600); never commit them.
- **Local music**:
  - go-music-dl listens on port 18080 on every network interface, so while the backend runs, any device on your LAN can use it to search and download.
  - Sign-in cookies stay in `local-music/go-music-dl/data/`, which is not in Git.
  - The music comes from the platforms' unofficial interfaces; keep it to personal use.

## Documentation

| | |
| --- | --- |
| [docs/GUIDE.en.md](docs/GUIDE.en.md) | Full guide: features, local music, manual setup, flashing, troubleshooting, Bot interface, building, tests, known limitations |
| [docs/README.md](docs/README.md) | Index of all docs, including board notes (Chinese) |
| [deploy/README.md](deploy/README.md) | Deploying to a public server (Chinese) |

## About this repository

This project's own changes are in:
- **Firmware**: `xiaozhi-esp32/main/boards/common/zongzhu/` and the board directories.
- **Backend**: under `xiaozhi-esp32-server/main/xiaozhi-server/core/`, the files `handle/grokBot*.py`, `handle/localCommandHandle.py`, `music/` and `utils/asr_text.py`.
- **Everything else**: `web/`, `tools/`, `deploy/`, `examples/` and `docs/`.

The rest of the two upstream directories is kept mostly as is, so that later upstream merges, which keep up with Xiaozhi firmware updates, stay simple. Upstream base commits are in `UPSTREAM.json`.

## Credits and license

- This project's code: [MIT License](LICENSE).
- The firmware is based on [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) and the backend on [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server), both MIT.
- Local music uses [go-music-dl](https://github.com/guohuiyuan/go-music-dl) (AGPL-3.0) and [mpv](https://github.com/mpv-player/mpv). Neither is in this repository: `tools/local_music_setup.sh` downloads them from their release pages, and they run as separate programs under their own licenses.
- Real keys, Wi-Fi settings, flash backups, model weights, sign-in cookies, logs and conversations stay on the local machine and are not in this repository.
