#!/usr/bin/env python3
"""最小测试接收端：等音箱 Client 连上 4399，打印握手里的 token 是否正确，问一次版本号，收几秒消息后退出。
用法：.venv/bin/python test_server.py <token 文件> [等待秒数]
"""
import asyncio
import json
import sys
import uuid

import websockets

TOKEN = open(sys.argv[1]).read().strip()
WAIT = float(sys.argv[2]) if len(sys.argv) > 2 else 120
done = asyncio.Event()


async def handler(ws):
    auth = ws.request.headers.get("Authorization", "")
    print(f"连上：{ws.remote_address}，token {'正确' if auth == f'Bearer {TOKEN}' else '不对或没带'}", flush=True)
    req_id = str(uuid.uuid4())
    await ws.send(json.dumps({"Request": {"id": req_id, "command": "get_version", "payload": None}}))
    try:
        async with asyncio.timeout(8):
            async for msg in ws:
                if isinstance(msg, bytes):
                    print(f"二进制消息 {len(msg)} 字节", flush=True)
                    continue
                print("收到：", msg[:300], flush=True)
    except TimeoutError:
        pass
    done.set()


async def main():
    async with websockets.serve(handler, "0.0.0.0", 4399):
        print("在 4399 等待……", flush=True)
        try:
            async with asyncio.timeout(WAIT):
                await done.wait()
        except TimeoutError:
            print("超时，没有 Client 连上", flush=True)


asyncio.run(main())
