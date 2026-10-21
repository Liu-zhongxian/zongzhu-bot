import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.handle import grokBotPhrases as phrases
from core.handle.grokBotHandle import handle_grok_bot, _recent


class FakeTTS:
    voice = "test-voice"

    def __init__(self):
        self.calls = []

    def to_tts(self, text):
        self.calls.append(text)
        return [b"opus-1", b"opus-2"]


def _conn(config_file, tts=None):
    return SimpleNamespace(
        config={"grok_bot": {"enabled": True, "config_file": str(config_file)}, "wakeup_words": ["你好宗主"]},
        headers={"device-id": "device-1"}, logger=mock.MagicMock(), tts=tts, sample_rate=24000,
        client_abort=False, session_id="session-1", features={"bot_ui": True},
        websocket=SimpleNamespace(send=mock.AsyncMock()), dialogue=mock.MagicMock(),
    )


class PhraseTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        phrases._cache.clear()
        _recent.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "config.json"
        self.config.write_text(json.dumps({"url": "https://example.test/webhook", "token": "t",
                                           "reply_dir": str(Path(self.temp.name) / "replies")}))
        self.audio = SimpleNamespace(sendAudioMessage=mock.AsyncMock(), send_tts_message=mock.AsyncMock(),
                                     send_stt_message=mock.AsyncMock())
        self.speak_txt = mock.MagicMock()
        patcher = mock.patch.dict(sys.modules, {
            "core.handle.sendAudioHandle": self.audio,
            "core.handle.intentHandler": SimpleNamespace(speak_txt=self.speak_txt),
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_warm_once_then_replay_from_memory(self):
        tts = FakeTTS()
        conn = _conn(self.config, tts)
        await phrases.warm(conn)
        await phrases.warm(conn)
        self.assertEqual(tts.calls, list(phrases.PHRASES))
        self.assertTrue(await phrases.speak(conn, phrases.ACK))
        first = self.audio.sendAudioMessage.await_args_list[0].args
        self.assertEqual(first[2], [b"opus-1", b"opus-2"])
        self.audio.send_tts_message.assert_not_awaited()

    async def test_uncached_phrase_plays_nothing_and_warms(self):
        tts = FakeTTS()
        conn = _conn(self.config, tts)
        self.assertFalse(await phrases.speak(conn, phrases.HERE))
        await asyncio.sleep(0.05)
        self.audio.sendAudioMessage.assert_not_awaited()
        self.assertEqual(tts.calls, [phrases.HERE])

    async def test_failed_synthesis_is_not_cached(self):
        tts = FakeTTS()
        tts.to_tts = lambda text: None
        conn = _conn(self.config, tts)
        await phrases.warm(conn)
        self.assertFalse(await phrases.speak(conn, phrases.ACK))

    async def _run(self, status, cached=True):
        tts = FakeTTS()
        conn = _conn(self.config, tts)
        if cached:
            await phrases.warm(conn)
        order = []
        real_speak = phrases.speak

        async def speak(*args, **kwargs):
            order.append("ack")
            return await real_speak(*args, **kwargs)

        async def post(submission):
            order.append("post")
            self.assertTrue(submission.pending.exists())
            return status, "结果：" + status
        with mock.patch("core.handle.grokBotHandle.post_submission", post), \
                mock.patch.object(phrases, "speak", speak):
            self.assertTrue(await handle_grok_bot(conn, "帮我查天气"))
        return conn, order

    async def test_accepted_says_only_the_acknowledgement(self):
        conn, order = await self._run("accepted")
        self.assertEqual(sorted(order), ["ack", "post"])
        self.speak_txt.assert_not_called()
        conn.websocket.send.assert_not_awaited()

    async def test_rejected_after_ack_leaves_wait_screen_and_explains(self):
        conn, _ = await self._run("rejected")
        message = json.loads(conn.websocket.send.await_args.args[0])
        self.assertEqual((message["type"], message["state"], message["text"]), ("bot_wait", "reply", "结果：rejected"))
        self.audio.send_tts_message.assert_awaited_with(conn, "start")
        self.speak_txt.assert_called_once_with(conn, "结果：rejected")

    async def test_unknown_after_ack_keeps_waiting(self):
        conn, _ = await self._run("unknown")
        conn.websocket.send.assert_not_awaited()
        self.speak_txt.assert_called_once_with(conn, "结果：unknown")

    async def test_uncached_ack_falls_back_to_the_old_reply(self):
        conn, _ = await self._run("accepted", cached=False)
        self.speak_txt.assert_called_once_with(conn, "结果：accepted")

    async def test_local_check_failure_never_posts(self):
        conn = _conn(self.config, FakeTTS())
        await phrases.warm(conn)
        with mock.patch("core.handle.grokBotHandle.post_submission") as post:
            self.assertTrue(await handle_grok_bot(conn, "你好宗主，" + "长" * 2001))
        post.assert_not_called()
        self.audio.sendAudioMessage.assert_not_awaited()
        self.assertIn("太长", self.speak_txt.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
