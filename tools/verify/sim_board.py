"""Simulated board for the checks in this folder: OTA, hello, wake word and spoken sentences.

In Bot mode the server takes any `listen detect` text for the board's wake word (the
board only sends detect on wake), so commands are spoken: macOS `say` (Tingting),
encoded to Opus and streamed like the microphone in manual listening mode, and the
server's own ASR recognises them. Needs macOS and ffmpeg.
"""
import asyncio
import json
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import opuslib_next
import websockets

FRAME = 960  # 60 ms at 16 kHz
OTA_URL = "http://127.0.0.1:8003/xiaozhi/ota/"
WS_URL = "ws://127.0.0.1:8000/xiaozhi/v1/"


def speech_frames(text):
    """Opus frames of `text` spoken by macOS, 16 kHz mono like the board."""
    with tempfile.TemporaryDirectory() as tmp:
        aiff, pcm = Path(tmp) / "s.aiff", Path(tmp) / "s.pcm"
        subprocess.run(["say", "-v", "Tingting", "-o", str(aiff), text], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(aiff), "-ar", "16000", "-ac", "1",
                        "-f", "s16le", str(pcm)], check=True)
        data = pcm.read_bytes() + bytes(FRAME * 2 * 8)  # trailing silence
    encoder = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)
    return [encoder.encode(data[i:i + FRAME * 2].ljust(FRAME * 2, b"\0"), FRAME)
            for i in range(0, len(data), FRAME * 2)]


@asynccontextmanager
async def board(device, client_id, bot_ui=True):
    """A connected board past the hello exchange; bot_ui=True behaves like our firmware."""
    headers = {"Device-Id": device, "Client-Id": client_id}
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.post(OTA_URL, headers=headers,
                                     json={"application": {"version": "2.5.2.9"}, "board": {"type": "local-test"}})
        response.raise_for_status()
        headers["Authorization"] = "Bearer " + response.json()["websocket"]["token"]
    async with websockets.connect(WS_URL, additional_headers=headers) as ws:
        hello = {"type": "hello", "version": 1, "transport": "websocket",
                 "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}}
        if bot_ui:
            hello["features"] = {"bot_ui": True}
        await ws.send(json.dumps(hello))
        assert json.loads(await asyncio.wait_for(ws.recv(), 20))["type"] == "hello"
        yield ws


async def speak(ws, text):
    await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "manual"}))
    for frame in speech_frames(text):
        await ws.send(frame)
        await asyncio.sleep(0.02)
    await ws.send(json.dumps({"type": "listen", "state": "stop"}))


async def until_tts_stop(ws, timeout=30):
    """Texts and audio packets up to the next `tts stop`."""
    seen = {"stt": None, "texts": [], "audio_packets": 0}
    deadline = time.monotonic() + timeout
    while True:
        raw = await asyncio.wait_for(ws.recv(), max(0.1, deadline - time.monotonic()))
        if isinstance(raw, bytes):
            seen["audio_packets"] += 1
            continue
        data = json.loads(raw)
        if data.get("type") == "stt":
            seen["stt"] = data.get("text")
        elif data.get("type") == "tts" and data.get("text"):
            seen["texts"].append(data["text"])
        elif data.get("type") == "tts" and data.get("state") == "stop":
            return seen


async def wake(ws, word="你好宗主"):
    """Say the wake word the way the board reports it; returns the greeting."""
    await ws.send(json.dumps({"type": "listen", "state": "detect", "text": word}))
    seen = await until_tts_stop(ws)
    # The server ignores audio for 2 s counted from the first frame after the wake word;
    # the board streams the microphone all along, so send silence through that window.
    silence = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO).encode(bytes(FRAME * 2), FRAME)
    for _ in range(42):
        await ws.send(silence)
        await asyncio.sleep(0.06)
    return seen
