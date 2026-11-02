"""Real Bot round trip: speaks one harmless task and waits for the reply on screen.

Calls the Bot configured in data/.config.yaml once; start the server first.
"""
import asyncio
import json
import time
from pathlib import Path

import sim_board

ROOT = Path(__file__).resolve().parents[2]  # 仓库根目录
TASK = "请只回复收到两个字，不要做别的事"
ACK = "正在交给 Bot"


async def main():
    async with sim_board.board("02:00:00:00:00:04", "zongzhu-reply-check") as ws:
        await sim_board.speak(ws, TASK)
        started = time.monotonic()
        report = {"task": TASK, "hardware_screen_test": False, "stt": None, "ack_text": [], "audio_packets": 0}
        while True:
            raw = await asyncio.wait_for(ws.recv(), max(.1, 180 - (time.monotonic() - started)))
            if isinstance(raw, bytes):
                report["audio_packets"] += 1
                continue
            data = json.loads(raw)
            if data.get("type") == "stt":
                report["stt"] = data.get("text")
            if data.get("type") == "tts" and data.get("text"):
                if data.get("request_id"):
                    report.update({"request_id": data["request_id"], "display_text": data["text"],
                                   "elapsed_seconds": round(time.monotonic() - started, 2)})
                    break
                report["ack_text"].append(data["text"])
        assert ACK in "".join(report["ack_text"]), report
        assert report["audio_packets"] > 0, report
        (ROOT / "logs").mkdir(exist_ok=True)
        (ROOT / "logs/bot-reply-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
