"""Exercise wait/resume/timeout/reply using local fixtures, without calling the Bot."""
import array
import asyncio
import json
import time
import uuid
import wave
from pathlib import Path

import httpx
import opuslib_next
import websockets

ROOT = Path(__file__).resolve().parents[2]  # 仓库根目录
DEVICE = "02:00:00:00:00:07"


async def main():
    config = json.loads((ROOT / "private/grok-bot-webhook.json").read_text())
    directory = Path(config["reply_dir"])
    owned = []
    report = {"physical_hardware": False, "calls_bot_webhook": False}

    def pending():
        request_id = "ESP32-" + uuid.uuid4().hex
        path = directory / (request_id + ".pending.json")
        data = {"request_id": request_id, "device": DEVICE, "created": time.time()}
        path.write_text(json.dumps(data))
        path.chmod(0o600)
        owned.append(request_id)
        return path, data

    headers = {"Device-Id": DEVICE, "Client-Id": "wait-display-check"}
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.post("http://127.0.0.1:8003/xiaozhi/ota/", headers=headers,
                                     json={"application": {"version": "2.5.2.3"}, "board": {"type": "local-test"}})
        response.raise_for_status()
        headers["Authorization"] = "Bearer " + response.json()["websocket"]["token"]
    try:
        async with websockets.connect("ws://127.0.0.1:8000/xiaozhi/v1/", additional_headers=headers) as ws:
            await ws.send(json.dumps({"type": "hello", "version": 1, "transport": "websocket",
                                     "features": {"bot_ui": True},
                                     "audio_params": {"format": "opus", "sample_rate": 16000,
                                                      "channels": 1, "frame_duration": 60}}))
            assert json.loads(await asyncio.wait_for(ws.recv(), 20))["type"] == "hello"

            async def wait_state(state, timeout=25):
                deadline = time.monotonic() + timeout
                while True:
                    raw = await asyncio.wait_for(ws.recv(), max(.1, deadline - time.monotonic()))
                    if isinstance(raw, str):
                        data = json.loads(raw)
                        assert data.get("type") != "stt", "Unexpected ASR during wait"
                        if data.get("type") == "bot_wait" and data.get("state") == state:
                            return data

            path, data = pending()
            await wait_state("waiting")
            encoder = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)
            # Real spoken PCM from the previously verified harmless speech test.
            with wave.open(str(ROOT / "logs/bot-reply-speech.wav")) as wav:
                assert wav.getframerate() == 16000 and wav.getnchannels() == 1
                pcm = wav.readframes(wav.getnframes())
            for offset in range(0, len(pcm), 1920):
                await ws.send(encoder.encode(pcm[offset:offset + 1920].ljust(1920, b"\0"), 960))
                await asyncio.sleep(.06)
            await asyncio.sleep(2)
            device_pending = [p for p in directory.glob("*.pending.json")
                              if json.loads(p.read_text()).get("device") == DEVICE]
            assert device_pending == [path], "Wait audio created an extra request"
            report["waiting_speech_did_not_submit"] = True
            data["created"] -= config.get("reply_wait_seconds", 300) + 1
            path.write_text(json.dumps(data))
            await wait_state("timeout")
            assert path.exists()
            path.unlink()
            report["timeout_retains_pending"] = True

            path, data = pending()
            await wait_state("waiting")
            await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "auto"}))
            resumed = time.monotonic()
            text = "宗主等待和显示测试成功。等待期间暂停普通收音，再次唤醒可以追加指令。回复到达后朗读，完整正文会保留在屏幕上。"
            result = directory / (data["request_id"] + ".json")
            result.write_text(json.dumps({"request_id": data["request_id"], "text": text}, ensure_ascii=False))
            result.chmod(0o600)
            message = await wait_state("reply", 25)
            report["resume_input_grace_seconds"] = round(time.monotonic() - resumed, 2)
            assert report["resume_input_grace_seconds"] >= 14
            assert message["text"] == text
            decoder = opuslib_next.Decoder(16000, 1)
            samples = array.array("h")
            subtitles = []
            while True:
                raw = await asyncio.wait_for(ws.recv(), 30)
                if isinstance(raw, bytes):
                    samples.frombytes(decoder.decode(raw, 960))
                else:
                    message = json.loads(raw)
                    if message.get("type") == "tts":
                        if message.get("text"):
                            subtitles.append(message["text"])
                        if message.get("state") == "stop":
                            break
            assert max(abs(n) for n in samples) > 100
            assert text in subtitles
            assert not path.exists()
            report.update(full_text_preserved=True, reply_audio_seconds=round(len(samples) / 16000, 2),
                          pcm_peak=max(abs(n) for n in samples), reply_finished=True)
        (ROOT / "logs/bot-wait-display-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        for request_id in owned:
            for suffix in (".pending.json", ".json", ".sent.json"):
                (directory / (request_id + suffix)).unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
