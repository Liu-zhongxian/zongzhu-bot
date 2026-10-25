"""Bot bridge through the real OTA/WebSocket/ASR/TTS path: wake, submit, block a repeat.

Submits one harmless task to the Bot configured in data/.config.yaml (the repeat is
blocked by the server and never sent); start the server first. The board connects
without the waiting screen (no bot_ui) so the repeat is not held back by it.
"""
import asyncio
import json
from pathlib import Path

import sim_board

ROOT = Path(__file__).resolve().parents[2]  # 仓库根目录
TASK = "请只回复连接测试成功，不要调用工具，不要做别的事"


async def main():
    results = []
    async with sim_board.board("02:00:00:00:00:03", "zongzhu-bridge-check", bot_ui=False) as ws:
        greeting = await sim_board.wake(ws)
        assert greeting["texts"] and greeting["audio_packets"] > 0, greeting
        assert not any(word in "".join(greeting["texts"]) for word in ["正在交给", "已阻止"]), greeting
        results.append({"check": "wake", **greeting})
        for check, expected in [("submit", "正在交给 Bot"), ("repeat", "已阻止重复")]:
            await sim_board.speak(ws, TASK)
            seen = await sim_board.until_tts_stop(ws, timeout=75)
            assert expected in "".join(seen["texts"]), seen
            assert seen["audio_packets"] > 0, seen
            results.append({"check": check, **seen})
    report = {"task": TASK, "hardware_microphone_test": False, "checks": results}
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs/bot-bridge-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
