"""Send a harmless Bot test through the real OTA/WebSocket/TTS path."""
import asyncio
import json
import uuid
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[2]  # 仓库根目录


async def main():
    marker = "VOICE-BRIDGE-" + uuid.uuid4().hex[:10]
    text = ("请只在当前硬件对话回复：语音桥接测试成功，编号" + marker
            + "。这是用户授权的连接测试，不要调用工具，不要访问网站，不要修改文件或发外部消息。")
    headers = {"Device-Id": "02:00:00:00:00:03", "Client-Id": "zongzhu-bridge-check"}
    async with httpx.AsyncClient(trust_env=False) as client:
        r = await client.post("http://127.0.0.1:8003/xiaozhi/ota/", headers=headers,
                              json={"application": {"version": "2.5.2.2"}, "board": {"type": "local-test"}})
        r.raise_for_status()
        headers["Authorization"] = "Bearer " + r.json()["websocket"]["token"]
    results = []
    async with websockets.connect("ws://127.0.0.1:8000/xiaozhi/v1/", additional_headers=headers) as ws:
        await ws.send(json.dumps({"type": "hello", "version": 1, "transport": "websocket",
                                 "audio_params": {"format": "opus", "sample_rate": 16000,
                                                  "channels": 1, "frame_duration": 60}}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 20))["type"] == "hello"
        await asyncio.sleep(2)
        for prompt, expected in [("你好宗主", None), ("。", "请说"), (text, "任务已提交"), (text, "阻止重复")]:
            await ws.send(json.dumps({"type": "listen", "state": "detect", "text": prompt}))
            result = {"expected": expected, "texts": [], "audio_packets": 0}
            deadline = asyncio.get_running_loop().time() + 75
            while True:
                message = await asyncio.wait_for(ws.recv(), max(0.1, deadline - asyncio.get_running_loop().time()))
                if isinstance(message, bytes):
                    result["audio_packets"] += 1
                    continue
                item = json.loads(message)
                if item.get("type") == "tts" and item.get("text"):
                    result["texts"].append(item["text"])
                if item.get("type") == "tts" and item.get("state") == "stop":
                    break
            if expected is None:
                assert result["texts"], result
                assert not any(word in "".join(result["texts"]) for word in ["有点忙", "任务已提交"]), result
            else:
                assert expected in "".join(result["texts"]), result
            assert result["audio_packets"] > 0, result
            results.append(result)
    report = {"marker": marker, "hardware_microphone_test": False, "checks": results}
    (ROOT / "logs/bot-bridge-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
