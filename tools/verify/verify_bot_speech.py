"""Real Bot round trip; verifies reply subtitles and decoded speech audio.

Calls the Bot configured in data/.config.yaml once; start the server first.
"""
import array
import asyncio
import json
import time
import wave
from pathlib import Path

import opuslib_next

import sim_board

ROOT = Path(__file__).resolve().parents[2]  # 仓库根目录
TASK = "请只回复一句话：宗主朗读测试成功，不要做别的事"
ACK = "正在交给 Bot"


async def main():
    async with sim_board.board("02:00:00:00:00:06", "zongzhu-speech-check") as ws:
        await sim_board.speak(ws, TASK)
        started = time.monotonic()
        report = {"task": TASK, "hardware_speaker_test": False, "stt": None, "ack_text": [], "reply_subtitles": [],
                  "audio_packets": 0, "reply_audio_packets": 0}
        decoder = opuslib_next.Decoder(16000, 1)
        pcm = bytearray()
        replying = False
        while True:
            raw = await asyncio.wait_for(ws.recv(), max(.1, 300 - (time.monotonic() - started)))
            if isinstance(raw, bytes):
                report["audio_packets"] += 1
                if replying:
                    report["reply_audio_packets"] += 1
                    pcm.extend(decoder.decode(raw, 960))
                continue
            data = json.loads(raw)
            if data.get("type") == "stt":
                report["stt"] = data.get("text")
            if data.get("type") != "tts":
                continue
            if data.get("state") == "start" and data.get("request_id"):
                replying = True
                report["request_id"] = data["request_id"]
            if data.get("text"):
                (report["reply_subtitles"] if replying else report["ack_text"]).append(data["text"])
            if replying and data.get("state") == "stop":
                report["elapsed_seconds"] = round(time.monotonic() - started, 2)
                break
        assert ACK in "".join(report["ack_text"]), report
        assert report["reply_subtitles"], report
        assert report["reply_audio_packets"] > 0, report
        samples = array.array("h", pcm)
        report["pcm_peak"] = max(abs(n) for n in samples)
        report["reply_audio_seconds"] = round(len(samples) / 16000, 2)
        assert report["pcm_peak"] > 100, report
        (ROOT / "logs").mkdir(exist_ok=True)
        with wave.open(str(ROOT / "logs/bot-reply-speech.wav"), "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(pcm)
        (ROOT / "logs/bot-speech-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
