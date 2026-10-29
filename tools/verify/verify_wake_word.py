"""G8b on a simulated board: tools/wake_word.py changes the wake word over MCP.

The simulated board declares MCP and answers like the firmware: initialize, an empty
tools list ([user] tools are never listed), then self.assets.set_download_url and
self.reboot. The check downloads the URL the board was given and reads the wake word
in it. Nothing is flashed and the Bot is not called.

    .venv/bin/python tools/verify/verify_wake_word.py
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import httpx

from sim_board import board

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "xiaozhi-esp32-server/main/xiaozhi-server"))
from core.gateway.wake_assets import wake_word_of  # noqa: E402

DEVICE = "02:00:00:00:00:0b"
ASSETS = ROOT / "firmware/zongzhu-szp-2.5.2.9/generated_assets.bin"


async def answer_mcp(ws, calls):
    """Answer the server's MCP requests like the firmware until self.reboot."""
    while True:
        raw = await ws.recv()
        if isinstance(raw, bytes):
            continue
        message = json.loads(raw)
        if message.get("type") != "mcp":
            continue
        request = message["payload"]
        method, params = request.get("method"), request.get("params") or {}
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "sim-board", "version": "2.5.2.9"}}
        elif method == "tools/list":
            result = {"tools": []}
        elif method == "tools/call":
            calls.append((params["name"], params.get("arguments") or {}))
            result = {"content": [{"type": "text", "text": "true"}], "isError": False}
        else:
            continue
        await ws.send(json.dumps({"type": "mcp", "payload": {"jsonrpc": "2.0", "id": request["id"], "result": result}}))
        if method == "tools/call" and params["name"] == "self.reboot":
            return


async def main():
    calls = []
    async with board(DEVICE, "verify-wake-word", mcp=True) as ws:
        responder = asyncio.create_task(answer_mcp(ws, calls))
        await asyncio.sleep(2)  # the server asks for the tools list 1 s after initialize
        cli = await asyncio.create_subprocess_exec(
            sys.executable, str(ROOT / "tools/wake_word.py"), "你好小雨", "--device", DEVICE[-5:],
            "--assets", str(ASSETS), "--yes", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = (await cli.communicate())[0].decode()
        print(output)
        assert cli.returncode == 0, "脚本失败"
        await asyncio.wait_for(responder, 10)
    names = [name for name, _ in calls]
    assert names == ["self.assets.set_download_url", "self.reboot"], names
    url = calls[0][1]["url"]
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(url)
        response.raise_for_status()
        assert response.headers["Content-Length"] == str(len(response.content))
        wake = wake_word_of(response.content)
        print("下载", url, len(response.content), "字节，唤醒词", wake)
        assert wake == {"command": "ni hao xiao yu", "text": "你好小雨", "action": "wake"}, wake
        # The board is gone now: the server must say so instead of hanging.
        refused = await client.post("http://127.0.0.1:8003/gateway/api/wake_word", content=ASSETS.read_bytes(),
                                    params={"device": DEVICE, "text": "你好小雨", "command": "ni hao xiao yu"})
        print("板子断开后：", refused.status_code, refused.json())
        assert refused.status_code == 409
        assert (await client.get(url.rsplit("/", 1)[0] + "/..%2Fgateway_boards.json")).status_code == 404
    print("通过")


asyncio.run(main())
