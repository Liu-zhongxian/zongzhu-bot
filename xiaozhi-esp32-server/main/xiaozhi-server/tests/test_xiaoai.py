"""G19i 第 1 步：宗主后端开端口接小米音箱。假 Client 照 open-xiaoai Client 的消息格式回应
（xiaoai-bridge/speaker/client/client-rust/src/services/connect/）。"""
import asyncio
import json
import socket
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import websockets

from core.gateway.xiaoai import server
from core.gateway.xiaoai.protocol import PLAY_CONFIG, RECORD_CONFIG, ClientError, SpeakerLink


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeClient:
    """连上服务的假音箱：记下收到的指令和要放的声音，能发麦克风数据"""

    def __init__(self, ws, fail=()):
        self.ws = ws
        self.fail = set(fail)
        self.commands = []
        self.played = bytearray()

    async def run(self):
        async for message in self.ws:
            if isinstance(message, bytes):
                stream = json.loads(message)
                if stream["tag"] == "play":
                    self.played += bytes(stream["bytes"])
                continue
            request = json.loads(message)["Request"]
            self.commands.append((request["command"], request["payload"]))
            if request["command"] in self.fail:
                response = {"id": request["id"], "code": -1, "msg": "boom"}
            elif request["command"] == "get_version":
                response = {"id": request["id"], "data": "1.0.0"}
            else:
                response = {"id": request["id"], "code": 0, "msg": "success"}
            await self.ws.send(json.dumps({"Response": response}))

    async def record(self, pcm):
        await self.ws.send(json.dumps({"id": "x", "tag": "record", "bytes": list(pcm)}).encode())


class ServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.TemporaryDirectory()
        token = Path(self.dir.name) / "token.txt"
        token.write_text("secret\n", encoding="utf-8")
        self.port = free_port()
        self.config = {"gateway": {"xiaoai": {"enabled": True, "port": self.port, "token_file": str(token)}}}
        self.levels = []
        self.server = server.XiaoaiServer(self.config)
        self.task = asyncio.create_task(self.server.start())
        await asyncio.sleep(0.2)

    async def asyncTearDown(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        self.dir.cleanup()

    def connect(self, token="secret"):
        return websockets.connect(f"ws://127.0.0.1:{self.port}",
                                  additional_headers={"Authorization": f"Bearer {token}"})

    async def test_wrong_token_is_rejected(self):
        with self.assertRaises(websockets.InvalidStatus) as caught:
            async with self.connect("wrong"):
                pass
        self.assertEqual(caught.exception.response.status_code, 401)

    async def test_connect_starts_recording_and_plays_the_beep(self):
        async with self.connect() as ws:
            client = FakeClient(ws)
            runner = asyncio.create_task(client.run())
            for _ in range(50):
                if client.played:
                    break
                await asyncio.sleep(0.05)
            runner.cancel()
        commands = [c for c, _ in client.commands]
        self.assertEqual(commands, ["get_version", "start_recording", "start_play"])
        self.assertEqual(client.commands[1][1], RECORD_CONFIG)
        self.assertEqual(client.commands[2][1], PLAY_CONFIG)
        # 两声提示音加空白，24 kHz 16 位
        self.assertEqual(len(client.played), len(server.beep(880) + server.silence(100) + server.beep(1320) + server.silence(200)))

    async def test_microphone_level_is_reported(self):
        reports = []
        meter = server.LevelMeter
        with mock.patch.object(server, "LevelMeter", lambda report: meter(reports.append, seconds=60)):
            async with self.connect() as ws:
                client = FakeClient(ws)
                runner = asyncio.create_task(client.run())
                one_second = struct.pack("<16000h", *([1000, -1000] * 8000))
                await client.record(one_second[:16000])
                await client.record(one_second[16000:])
                for _ in range(50):
                    if reports:
                        break
                    await asyncio.sleep(0.05)
                runner.cancel()
        self.assertEqual(reports, [1000])

    async def test_port_in_use_does_not_crash(self):
        # bridge 还占着端口时只报错，后端照常跑
        other = server.XiaoaiServer(self.config)
        with mock.patch.object(server.logger, "bind") as bind:
            await asyncio.wait_for(other.start(), 2)
        self.assertIn("被占用", bind.return_value.error.call_args.args[0])


class ConfigTest(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_by_default(self):
        with mock.patch.object(server.websockets, "serve") as serve:
            await server.XiaoaiServer({}).start()
        serve.assert_not_called()

    async def test_no_token_file_means_no_server(self):
        with mock.patch.object(server.websockets, "serve") as serve, mock.patch.object(server.logger, "bind"):
            await server.XiaoaiServer({"gateway": {"xiaoai": {"enabled": True}}}).start()
        serve.assert_not_called()


class LinkTest(unittest.IsolatedAsyncioTestCase):
    async def test_client_error_is_raised(self):
        sent = []

        class Ws:
            async def send(self, message):
                sent.append(json.loads(message)["Request"])

        link = SpeakerLink(Ws())
        call = asyncio.create_task(link.call("run_shell", "ls"))
        await asyncio.sleep(0)
        await link._on_text({"Response": {"id": sent[0]["id"], "code": -1, "msg": "boom"}})
        with self.assertRaises(ClientError):
            await call

    async def test_pending_calls_fail_when_the_speaker_disconnects(self):
        class Ws:
            def __init__(self):
                self.closed = asyncio.Event()

            async def send(self, message):
                pass

            def __aiter__(self):
                return self

            async def __anext__(self):
                await self.closed.wait()
                raise StopAsyncIteration

        ws = Ws()
        link = SpeakerLink(ws)
        runner = asyncio.create_task(link.run())
        call = asyncio.create_task(link.call("get_version"))
        await asyncio.sleep(0)
        ws.closed.set()
        await runner
        with self.assertRaises(ConnectionError):
            await call


if __name__ == "__main__":
    unittest.main()
