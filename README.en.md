[中文](README.md) | English

# Zongzhu Bot

![Zongzhu: a desktop voice terminal with a pair of white eyes on a black round screen](docs/images/banner.jpg)

[![Firmware](https://img.shields.io/badge/firmware-2.5.2.9-black)](https://github.com/Liu-zhongxian/zongzhu-bot/releases/latest)
[![Board](https://img.shields.io/badge/board-Waveshare_1.75C_|_Lichuang_SZPI_S3-blue)](#what-you-need)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Zongzhu (宗主) turns an ESP32-S3 screen board into a voice terminal for Grok Bot. Say the wake word "你好宗主" (*ni hao zongzhu*), speak your request, and the Bot's answer comes back to the screen and is read aloud. The screen is a pair of white eyes on black that blink, follow your finger, and get dizzy when you shake the board.

> **Language note:** the wake word, speech recognition, on-screen system messages and the instructions sent to the Bot are Chinese-first. The project is built and tested for Mandarin speakers.

## What you need

- **Board**: Waveshare ESP32-S3-Touch-AMOLED-1.75C, or the Lichuang (立创) SZPI ESP32-S3 ([notes](docs/BOARD-SZP.md), Chinese). An M5Stack StopWatch build exists but hasn't run on a board yet ([notes](docs/BOARD-STOPWATCH.md), Chinese).
- **Computer**: an always-on Mac (verified on Apple Silicon) runs the backend, on the same 2.4 GHz LAN as the board. A public server works too: [deploy to a server](deploy/README.md) (Chinese).
- **Bot**: your Grok Bot must expose a webhook **and be able to write files on this computer**, or replies never reach the board ([interface](docs/GUIDE.en.md#bot-interface)).

## Getting started

1. Open the **[web flasher](https://liu-zhongxian.github.io/zongzhu-bot/)** in Chrome or Edge on your computer and connect the board over USB.
2. First time only, install the backend: the page shows a one-line command to paste into Terminal. It installs dependencies, downloads the speech model (about 200MB), asks for your Bot webhook, and prints the computer address to enter back on the page.
3. Back on the page, go through the six steps: detect the board, pick the wake word, pick the style, enter the backend address, enter Wi-Fi, flash and check the connection.
4. Say "你好宗主", then your request. The screen counts the seconds while waiting and reads the Bot's reply aloud when it arrives.

Prefer not to use the web page, want to build the firmware yourself, or the page doesn't work for you: see [manual setup](docs/GUIDE.en.md#manual-setup-without-the-web-page).

## What it does

- Everything you say after waking goes to the Bot; the wait is shown in seconds. Replies are shown and read aloud, and replies that arrive while disconnected are delivered on the next connection.
- Local, offline speech recognition (X-ASR) that handles mixed Chinese and English, with automatic fixes for common misrecognitions.
- 13 eye expressions drawn in real time, following the device state; touch, tilt and shake all get a reaction.
- Three subtitle modes (full / brief / off), switched by a long press on BOOT.

Gestures, the expression list and troubleshooting are in the [full guide](docs/GUIDE.en.md).

## Documentation

| | |
| --- | --- |
| [docs/GUIDE.en.md](docs/GUIDE.en.md) | Full guide: features, manual setup, flashing, troubleshooting, Bot interface, building, tests, known limitations |
| [docs/README.md](docs/README.md) | Index of all docs, including board notes and development records (Chinese) |
| [deploy/README.md](deploy/README.md) | Deploying to a public server (Chinese) |

## Credits and license

The firmware is based on [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) and the backend on [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server), both MIT; upstream base commits are in `UPSTREAM.json`. Real keys, Wi-Fi settings, flash backups, model weights, logs and conversations stay on the local machine and are not in this repository.
