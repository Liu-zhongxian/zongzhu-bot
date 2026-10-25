"""Simulated device: music commands are handled on this Mac and never reach the Bot.

Each command is spoken with macOS `say` (Tingting), encoded to Opus and sent the
way the board streams the microphone (sim_board.py), so the server's own
ASR recognises it. (A listen/detect text would be taken for the board's wake word in
Bot mode.) Plays music on this Mac for a few seconds; it does not change the
system volume and does not call the Bot webhook.

    .venv/bin/python tools/verify/verify_local_music.py
"""
import asyncio
import json
import time

import httpx
import websockets

from sim_board import speech_frames

DEVICE = "02:00:00:00:00:08"


async def main():
    headers = {"Device-Id": DEVICE, "Client-Id": "local-music-check"}
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.post("http://127.0.0.1:8003/xiaozhi/ota/", headers=headers,
                                     json={"application": {"version": "2.5.2.9"}, "board": {"type": "local-test"}})
        response.raise_for_status()
        headers["Authorization"] = "Bearer " + response.json()["websocket"]["token"]
    report = []
    async with websockets.connect("ws://127.0.0.1:8000/xiaozhi/v1/", additional_headers=headers) as ws:
        await ws.send(json.dumps({"type": "hello", "version": 1, "transport": "websocket",
                                  "features": {"bot_ui": True},
                                  "audio_params": {"format": "opus", "sample_rate": 16000,
                                                   "channels": 1, "frame_duration": 60}}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 20))["type"] == "hello"

        async def say(text, settle=3):
            await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "manual"}))
            for frame in speech_frames(text):
                await ws.send(frame)
                await asyncio.sleep(0.02)
            await ws.send(json.dumps({"type": "listen", "state": "stop"}))
            t0 = time.monotonic()
            seen = {"text": text, "stt": None, "bot_wait": None, "screen": None, "audio_packets": 0,
                    "first_audio": None, "tts_stop": None}
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), 20)
                except asyncio.TimeoutError:
                    break
                if isinstance(raw, bytes):
                    seen["audio_packets"] += 1
                    seen["first_audio"] = seen["first_audio"] or round(time.monotonic() - t0, 2)
                    continue
                data = json.loads(raw)
                if data.get("type") == "stt":
                    seen["stt"] = data.get("text")
                elif data.get("type") == "bot_wait":
                    seen["bot_wait"] = data.get("text")
                    seen["screen"] = data.get("text")
                elif data.get("type") == "tts" and data.get("state") == "stop":
                    seen["tts_stop"] = round(time.monotonic() - t0, 2)
                    # the song name follows a moment later for slow commands
                    try:
                        while True:
                            late = await asyncio.wait_for(ws.recv(), 4)
                            if isinstance(late, str) and json.loads(late).get("type") == "bot_wait":
                                seen["screen"] = json.loads(late).get("text")
                    except asyncio.TimeoutError:
                        pass
                    break
            report.append(seen)
            print(seen)
            await asyncio.sleep(settle)

        await say("放周杰伦的晴天", settle=4)
        await say("下一首", settle=3)
        await say("这是什么歌")
        await say("暂停", settle=1)
        await say("继续", settle=2)
        await say("快进五秒", settle=2)
        await say("从头播放", settle=2)
        await say("别再放了", settle=0)  # 2026-10-25 实机：多一个"再"字曾被交给 Bot

    ok = all(r["bot_wait"] and r["audio_packets"] and r["tts_stop"] for r in report)
    ok = ok and report[-1]["bot_wait"] == "已停止播放。"
    print("通过" if ok else "未通过")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(main()) else 1)
