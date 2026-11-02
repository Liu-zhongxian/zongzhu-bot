"""G19i 第 1、2 步：宗主后端开端口接小米音箱，认唤醒词回"在"。假 Client 照 open-xiaoai Client 的消息格式回应
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

from core.gateway.xiaoai import prompts, server, wake
from core.gateway.xiaoai.protocol import PLAY_CONFIG, RECORD_CONFIG, ClientError, SpeakerLink, silence


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
        self.spotter = FakeSpotter()
        patches = [mock.patch.object(server.wake, "Spotter", lambda *a, **k: self.spotter),
                   mock.patch.object(prompts, "phrase", mock.AsyncMock(return_value=b"\x01\x00" * 2400))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
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
        # 一声提示音，开头不垫静音
        self.assertEqual(bytes(client.played), server.beep(1320, 200))

    async def test_wake_word_gets_a_reply(self):
        async with self.connect() as ws:
            client = FakeClient(ws)
            runner = asyncio.create_task(client.run())
            for _ in range(50):
                if client.played:
                    break
                await asyncio.sleep(0.05)
            before = len(client.played)
            await client.record(b"WAKE" * 100)
            for _ in range(50):
                if len(client.played) > before:
                    break
                await asyncio.sleep(0.05)
            runner.cancel()
        self.assertEqual(bytes(client.played[before:]), b"\x01\x00" * 2400)  # "在"，原样

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


class FakeSpotter:
    """收到含 WAKE 的声音就"认出"唤醒词"""

    def create_stream(self):
        return None

    def feed(self, stream, pcm):
        return "你好宗主" if b"WAKE" in pcm else None


class WakeListenerTest(unittest.TestCase):
    def test_wake_while_muted_is_ignored_but_audio_still_goes_in(self):
        now = [100.0]
        heard, fed = [], []
        spotter = FakeSpotter()
        original = spotter.feed
        spotter.feed = lambda stream, pcm: (fed.append(pcm), original(stream, pcm))[1]
        listener = wake.WakeListener(spotter, heard.append, clock=lambda: now[0])
        listener.mute(1.0)
        listener.feed(b"WAKE")  # 放"在"的时候认出来的：不算
        listener.feed(b"....")
        listener.close()
        listener.thread.join(2)
        self.assertEqual(heard, [])
        self.assertEqual(fed, [b"WAKE", b"...."])  # 声音照样送进去，紧跟着喊的唤醒词不会缺开头

        listener = wake.WakeListener(FakeSpotter(), heard.append, clock=lambda: now[0])
        listener.feed(b"WAKE")
        listener.close()
        listener.thread.join(2)
        self.assertEqual(heard, ["你好宗主"])

    @unittest.skipUnless(Path(wake.DEFAULT_MODEL_DIR, "tokens.txt").exists(), "本机没有唤醒词模型")
    def test_keyword_lines_with_the_real_model(self):
        model = Path(wake.DEFAULT_MODEL_DIR)
        lines = wake.keyword_lines(["你好宗主"], str(model / "tokens.txt"), str(model / "bpe.model"))
        self.assertEqual(lines, ["你 好 宗 主 @你好宗主"])


class ReplyTest(unittest.IsolatedAsyncioTestCase):
    async def test_tts_failure_falls_back_to_a_beep(self):
        link, listener = mock.Mock(play=mock.AsyncMock()), mock.Mock()
        with mock.patch.object(prompts, "phrase", mock.AsyncMock(side_effect=RuntimeError("offline"))), \
                mock.patch.object(server.logger, "bind"):
            await server.XiaoaiServer({})._reply(link, listener)
        link.play.assert_awaited_once_with(server.beep(1320))
        listener.mute.assert_called_once()


class PlayTest(unittest.IsolatedAsyncioTestCase):
    async def test_player_starts_once_and_audio_goes_out_as_is(self):
        sent = []

        class Ws:
            async def send(self, message):
                sent.append(message)

        link = SpeakerLink(Ws())
        link.call = mock.AsyncMock()
        await link.play(b"\x01\x00" * 10)
        await link.play(b"\x02\x00" * 10)
        first, second = (bytes(json.loads(m)["bytes"]) for m in sent)
        self.assertEqual(first, b"\x01\x00" * 10)
        self.assertEqual(second, b"\x02\x00" * 10)
        link.call.assert_awaited_once_with("start_play", PLAY_CONFIG)


class TrimTest(unittest.TestCase):
    def test_silence_before_and_after_is_cut(self):
        # 和 EdgeTTS 的"在"一样：前 0.127 秒静音、0.29 秒有声、后 1.45 秒静音（2026-11-02 实测）
        rate = 24000
        voice = struct.pack("<6960h", *([8000, -8000] * 3480))
        pcm = silence(127) + voice + silence(1455)
        trimmed = prompts.trim(pcm, rate)
        margin = rate * 30 // 1000 * 2
        self.assertEqual(len(trimmed), len(voice) + 2 * margin)
        self.assertIn(voice, trimmed)

    def test_all_silence_is_left_alone(self):
        self.assertEqual(prompts.trim(silence(100), 24000), silence(100))


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
