"""G19i 第 1、2 步：宗主后端开端口接小米音箱，认唤醒词回"在"。假 Client 照 open-xiaoai Client 的消息格式回应
（zongzhu-speaker/client/client-rust/src/services/connect/）。"""
import asyncio
import json
import socket
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import websockets

from core.gateway.xiaoai import prompts, server, wake
from core.gateway.xiaoai.protocol import (PLAY_CONFIG, RECORD_CONFIG, ClientError, SpeakerLink, mic_mono,
                                          playback_active, silence)


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
        """pcm 是单声道；照音箱的样子发成 4 声道：3 个麦克风都是它，第 4 个（音箱自己放的声音）是很响的干扰"""
        pcm = four_channels(pcm)
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
        await asyncio.wait_for(self.server.ready.wait(), 5)  # 等端口真的开了

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


def four_channels(mono, playback=30000):
    samples = struct.unpack(f"<{len(mono) // 2}h", mono)
    return struct.pack(f"<{len(samples) * 4}h", *[v for s in samples for v in (s, s, s, playback)])


class MicMonoTest(unittest.TestCase):
    def test_playback_is_seen_on_the_fourth_channel(self):
        sound = struct.pack("<8h", 0, 0, 0, 3000, 0, 0, 0, -3000)
        self.assertTrue(playback_active(sound))
        self.assertFalse(playback_active(four_channels(b"\x00\x40" * 10, playback=0)))  # 只有人声
        # stop_play 以后 ch3 停在 -256（2026-11-02 录音）：不算出声
        self.assertFalse(playback_active(four_channels(b"\0\0" * 10, playback=-256)))

    def test_averages_the_three_microphones_and_drops_playback(self):
        raw = struct.pack("<8h", 300, 600, 900, 32000, -3, -3, -3, -32000)
        self.assertEqual(mic_mono(raw), struct.pack("<2h", 600, -3))
        self.assertEqual(mic_mono(four_channels(b"WAKE" * 4)), b"WAKE" * 4)


class FakeSpotter:
    """收到含 WAKE 的声音就"认出"唤醒词"""
    skipped = []

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

    def test_new_wake_words_are_swapped_in_on_the_listening_thread(self):
        class Other:
            def create_stream(self):
                return None

            def feed(self, stream, pcm):
                return "宗主" if b"NEW" in pcm else None

        heard = []
        listener = wake.WakeListener(FakeSpotter(), heard.append)
        listener.use(Other())
        listener.feed(b"WAKE")  # 旧的词不认了
        listener.feed(b"NEW")
        listener.close()
        listener.thread.join(2)
        self.assertEqual(heard, ["宗主"])

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


class SpeakerInfoTest(unittest.TestCase):
    def test_parses_what_the_speaker_printed(self):
        from core.gateway.xiaoai import info
        # 2026-11-02 音箱上真实的输出格式（序列号、MAC 换成假的）
        out = ("model=OH2P\nsn=12345/A0B000000\nmac=00:11:22:33:44:55\nboot=boot0\n"
               "rom=1.62.2\nchannel=release\nhardware=OH2P\n"
               'play={\t"code": 0,\t"info": "{ \\"status\\": 1, \\"volume\\": 31, \\"loop_type\\": 1 }"}\n')
        self.assertEqual(info.parse(out), {"model": "OH2P", "sn": "12345/A0B000000", "mac": "00:11:22:33:44:55",
                                           "boot": "boot0", "rom": "1.62.2", "channel": "release",
                                           "hardware": "OH2P", "volume": 31, "play": "playing"})
        self.assertEqual(info.parse("model=\nplay=not json\n"), {})  # 读不到的不放


class SpeakerControlTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from core.gateway.xiaoai import control
        self.control = control
        self.commands = []

        async def call(command, payload=None, timeout=None):
            self.commands.append(payload)
            return {"stdout": "", "stderr": "", "exit_code": 0}

        self.link = mock.Mock(call=call)
        self.speaker = mock.Mock(interrupt=mock.AsyncMock())
        control.speakers.clear()
        control.speakers["aa:bb:cc:dd:ee:77"] = (self.link, self.speaker)
        self.addCleanup(control.speakers.clear)

    async def act(self, action, value=None, device="ee:77"):
        with mock.patch.object(self.control.info, "read", mock.AsyncMock(return_value={})), \
                mock.patch.object(self.control.status, "note_info"):
            result = await self.control.act({}, device, action, value)
            for _ in range(3):
                await asyncio.sleep(0)  # 后台重读信息也在替身里跑完，不写真文件
            return result

    async def test_volume_and_play_run_fixed_commands(self):
        self.assertEqual((await self.act("speaker_volume", "40"))["message"], "音箱音量调到 40。")
        await self.act("speaker_pause")
        self.assertEqual(self.commands, ["ubus call mediaplayer player_set_volume '{\"volume\":40}'",
                                         "ubus call mediaplayer player_play_operation "
                                         "'{\"action\":\"pause\",\"media\":\"common\"}'"])

    async def test_stop_xiaoai_stops_what_it_is_saying(self):
        await self.act("speaker_stop_xiaoai")
        self.assertTrue(self.commands[0].startswith("killall tts_play.sh miplayer"))

    async def test_bad_values_never_reach_the_speaker(self):
        for value in ("101", "-1", "40; reboot", None):
            with self.assertRaises(self.control.ControlError):
                await self.act("speaker_volume", value)
        with self.assertRaises(self.control.ControlError):
            await self.act("speaker_say", "x" * (self.control.SAY_MAX + 1))
        with self.assertRaises(self.control.ControlError):
            await self.act("speaker_play", device="no-such")
        self.assertEqual(self.commands, [])

    async def test_say_is_synthesized_here_and_played_as_sound(self):
        # 要念的文字不进音箱的命令行
        with mock.patch.object(self.control.prompts, "speech", mock.AsyncMock(return_value=b"\1\0" * 10)):
            await self.act("speaker_say", "你好'; reboot")
        self.speaker.interrupt.assert_awaited_once()
        self.speaker.player.add.assert_called_once_with(b"\1\0" * 10)
        self.assertEqual(self.commands, [])


class CallWordTest(unittest.IsolatedAsyncioTestCase):
    async def test_ai_name_heard_while_the_speaker_talks_is_ignored(self):
        # 音箱自己会说"好的，正在交给 Bot。"：放声音时听到 bot 不算，听到唤醒词照样打断
        srv = server.XiaoaiServer({})
        srv.call_words = {"bot": "grok_bot"}
        device = mock.Mock(state="speaking")
        device.player.playing_recently.return_value = True
        notes = []
        with mock.patch.object(srv, "_reply") as reply, mock.patch.object(server.logger, "bind"), \
                mock.patch.object(server.status, "note_wake"):
            srv._woken(None, None, "bot", notes.append, device)
            reply.assert_not_called()
            self.assertEqual(notes, ["放声音时认出呼名，忽略：bot"])
            srv._woken(None, None, "宗主", notes.append, device)
            reply.assert_called_once()
            device.player.playing_recently.return_value = False
            srv._woken(None, None, "bot", notes.append, device)
            self.assertEqual(device.call_agent, "grok_bot")


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


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class PlayerTest(unittest.IsolatedAsyncioTestCase):
    async def test_sends_in_pieces_and_never_more_than_a_second_ahead(self):
        from core.gateway.xiaoai import device
        clock = FakeClock()
        sent = []
        link = mock.Mock(play=mock.AsyncMock(side_effect=lambda pcm: sent.append((clock.now, len(pcm)))))

        async def sleep(seconds):
            clock.now += seconds
            await asyncio.sleep(0)

        player = device.Player(link, clock=clock, sleep=sleep)
        player.add(b"\0\0" * 24000 * 3)  # 3 秒
        for _ in range(50):
            await asyncio.sleep(0)
        player.close()
        self.assertEqual(sum(n for _, n in sent), 24000 * 2 * 3)
        self.assertTrue(all(n <= 24000 for _, n in sent))  # 每次最多 0.5 秒
        start = sent[0][0]
        for k, (t, n) in enumerate(sent):
            already = sum(m for _, m in sent[:k]) / 48000
            self.assertLessEqual(already - (t - start), device.SEND_AHEAD + 1e-6)


    async def test_notes_when_each_sentence_starts_and_when_the_speaker_runs_dry(self):
        from core.gateway.xiaoai import device
        clock = FakeClock()
        notes = []
        player = device.Player(mock.Mock(play=mock.AsyncMock()), clock=clock, note=notes.append)
        player.mark("第一句")
        player.add(b"\0\0" * 12000)  # 0.5 秒
        await asyncio.sleep(0.01)
        clock.now += 0.8               # 放完了 0.3 秒，下一句才到
        player.mark("第二句")
        player.add(b"\0\0" * 12000)
        await asyncio.sleep(0.01)
        player.close()
        self.assertEqual(notes[0], "开始放：第一句（约 0.00 秒后出声）")
        self.assertEqual(notes[1], "音箱空了 0.30 秒（上一段放完，下一段还没到）")
        self.assertTrue(notes[2].startswith("开始放：第二句"))


class DeviceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import opuslib_next
        from core.gateway.xiaoai import device
        self.device_mod = device
        self.clock = FakeClock()
        self.link = mock.Mock(play=mock.AsyncMock(), stop_play=mock.AsyncMock())
        self.dev = device.SpeakerDevice(self.link, ws_server=None, device_id="xiaoai-test", address="1.2.3.4",
                                        wake_word="你好宗主", clock=self.clock)
        self.sent = []

        async def connect():
            self.dev.socket = device.VirtualSocket({}, "1.2.3.4", self.dev._from_server, self.dev._closed)
            self.dev.socket.put = self.sent.append
            self.dev.handler = SimpleNamespace(session_id="s1", sample_rate=24000)
            self.dev.decoder = opuslib_next.Decoder(24000, 1)
            return True

        self.dev.connect = connect
        self.encoder = opuslib_next.Encoder(24000, 1, opuslib_next.APPLICATION_AUDIO)

    async def asyncTearDown(self):
        self.dev.watch.cancel()
        self.dev.player.close()

    def texts(self):
        return [json.loads(m) for m in self.sent if isinstance(m, str)]

    def frames(self):
        return [m for m in self.sent if isinstance(m, bytes)]

    def mic(self, seconds, playing=False):
        for _ in range(round(seconds / 0.06)):
            self.dev.on_mic(b"\1\0" * 960, playing)

    async def test_listen_starts_after_the_reply_and_its_echo_and_mic_goes_out_as_opus(self):
        await self.dev.start_listening()
        self.assertEqual(self.texts()[-1]["state"], "start")
        self.assertEqual(self.texts()[-1]["mode"], "auto")
        self.mic(0.42)                 # "在"还没从音箱出来：不发
        self.mic(0.36, playing=True)   # 音箱在放"在"：不发
        self.mic(0.48)                 # 回声（放完不到 0.5 秒）：不发
        self.assertFalse(self.frames())
        self.mic(0.12)
        self.assertEqual(len(self.frames()), 2)  # 60 毫秒一帧

    async def test_once_open_the_mic_stays_open_for_this_listen(self):
        await self.dev.start_listening(expect_playback=False)
        self.mic(0.12)
        sent = len(self.frames())
        self.assertTrue(sent)
        self.mic(0.12, playing=True)  # 以前这里会又停发，你说的后半句没了
        self.assertEqual(len(self.frames()), sent + 2)

    async def test_listen_does_not_wait_forever_for_the_reply(self):
        await self.dev.start_listening()
        self.mic(1.44)
        self.assertFalse(self.frames())
        self.mic(0.12)
        self.assertTrue(self.frames())

    async def test_reply_is_played_and_then_idle(self):
        await self.dev.start_listening(expect_playback=False)
        await self.dev._from_server(json.dumps({"type": "stt", "text": "现在几点"}))
        self.assertEqual(self.dev.state, "thinking")
        await self.dev._from_server(json.dumps({"type": "tts", "state": "start"}))
        self.assertEqual(self.dev.state, "speaking")
        self.dev.on_mic(b"\1\0" * 960)  # 说的时候不发麦克风
        self.assertFalse([m for m in self.sent if isinstance(m, bytes)])
        await self.dev._from_server(self.encoder.encode(b"\0\0" * 1440, 1440))
        self.assertTrue(self.dev.player.busy())
        await self.dev._from_server(json.dumps({"type": "tts", "state": "stop"}))
        await asyncio.sleep(0.05)  # 让 Player 把声音发出去
        self.clock.now += 5        # 放完了
        for _ in range(30):
            await asyncio.sleep(0.02)
            if self.dev.state == "idle":
                break
        self.assertEqual(self.dev.state, "idle")

    async def test_late_reply_while_idle_is_played(self):
        # Bot 晚到的回答：音箱在待机也照样放
        await self.dev.connect()
        await self.dev._from_server(json.dumps({"type": "tts", "state": "start"}))
        await self.dev._from_server(self.encoder.encode(b"\0\0" * 1440, 1440))
        self.assertEqual(self.dev.state, "speaking")
        self.assertTrue(self.dev.player.busy())

    async def test_wake_while_speaking_interrupts(self):
        await self.dev.connect()
        await self.dev._from_server(json.dumps({"type": "tts", "state": "start"}))
        self.dev.player.add(b"\0\0" * 24000)
        await self.dev.interrupt()
        self.assertEqual(self.texts()[-1], {"type": "abort", "session_id": "s1"})
        self.assertFalse(self.dev.player.buffer)
        self.link.stop_play.assert_awaited_once()  # 已经发到音箱的也停掉

    async def test_wake_while_quiet_does_not_stop_the_speaker(self):
        await self.dev.connect()
        await self.dev.interrupt()
        self.link.stop_play.assert_not_awaited()
        self.assertFalse([t for t in self.texts() if t.get("type") == "abort"])

    async def test_calling_an_ai_by_name_switches_to_it(self):
        with mock.patch("core.gateway.use_agent") as use_agent:
            self.dev.call_agent = "grok_bot"
            await self.dev.start_listening()
        use_agent.assert_called_once_with(self.dev.handler, "grok_bot")
        self.assertIsNone(self.dev.call_agent)

    async def test_listens_again_after_answering_only_the_name(self):
        # 2026-11-02：喊名字回"我在。"以后音箱待机了，接着问的问题没人听
        await self.dev.start_listening(expect_playback=False)
        handler = self.dev.handler
        handler.gateway_listen_again = True
        await self.dev._from_server(json.dumps({"type": "tts", "state": "start"}))
        await self.dev._from_server(json.dumps({"type": "tts", "state": "stop"}))
        for _ in range(30):
            await asyncio.sleep(0.02)
            if self.dev.state == "listening":
                break
        self.assertEqual(self.dev.state, "listening")
        self.assertFalse(handler.gateway_listen_again)

    async def test_nothing_heard_goes_back_to_idle(self):
        await self.dev.start_listening()
        self.clock.now += self.device_mod.LISTEN_TIMEOUT + 1
        for _ in range(30):
            await asyncio.sleep(0.02)
            if self.dev.state == "idle":
                break
        self.assertEqual(self.dev.state, "idle")
