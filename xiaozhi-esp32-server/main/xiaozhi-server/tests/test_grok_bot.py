import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import httpx
from unittest import mock

from core.handle.grokBotHandle import (extract_command, submit_command, handle_grok_bot,
                                      strip_wake_phrase, _recent)


def _fake_handlers(speak):
    """Stand-ins for the audio/intent modules, which load server config on import."""
    return mock.patch.dict(sys.modules, {
        "core.handle.sendAudioHandle": SimpleNamespace(send_stt_message=mock.AsyncMock()),
        "core.handle.intentHandler": SimpleNamespace(speak_txt=speak),
    })


class GrokBotTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _recent.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "config.json"
        self.config.write_text(json.dumps({"url": "https://example.test/webhook", "token": "test-secret"}))

    def test_all_conversation_preserves_negation_and_optional_prefix(self):
        self.assertEqual(extract_command("让 Bot，整理新闻。"), "整理新闻。")
        self.assertEqual(extract_command("请让机器人整理新闻"), "整理新闻")
        self.assertEqual(extract_command('{"content":"让波特回复成功","speaker":"甲"}'), "回复成功")
        self.assertEqual(extract_command("不要让 Bot 删除文件"), "不要让 Bot 删除文件")
        self.assertEqual(extract_command("什么是 Bot"), "什么是 Bot")
        self.assertEqual(extract_command("请回复宗主测试成功"), "请回复宗主测试成功")

    async def test_success_and_duplicate(self):
        requests = []
        def respond(request):
            requests.append(request)
            self.assertEqual(request.headers["Authorization"], "Bearer test-secret")
            body = json.loads(request.content)
            self.assertEqual(body["command"], "回复成功")
            self.assertIn(body["device"], ("device-1", "device-2"))
            self.assertTrue(body["request_id"].startswith("ESP32-"))
            return httpx.Response(200, json={"success": True, "runUuid": "run-1"})
        transport = httpx.MockTransport(respond)
        reply = await submit_command("回复成功", "device-1", self.config, transport)
        self.assertIn("任务已提交", reply)
        duplicate = await submit_command("回复成功。", "device-1", self.config, transport)
        self.assertIn("阻止重复", duplicate)
        self.assertEqual(len(requests), 1)
        await submit_command("回复成功", "device-2", self.config, transport)
        self.assertEqual(len(requests), 2)

    async def test_rejection_allows_retry(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(401))
        for _ in range(2):
            reply = await submit_command("测试", "device-1", self.config, transport)
            self.assertIn("任务未提交", reply)

    async def test_timeout_does_not_claim_success_or_retry(self):
        def timeout(request):
            raise httpx.ReadTimeout("timeout", request=request)
        reply = await submit_command("测试", "device-1", self.config, httpx.MockTransport(timeout))
        self.assertIn("无法确认", reply)
        again = await submit_command("测试", "device-1", self.config, httpx.MockTransport(timeout))
        self.assertIn("阻止重复", again)

    async def test_invalid_reply_and_missing_config(self):
        for body in [{"success": False}, {"success": True}, []]:
            _recent.clear()
            reply = await submit_command("测试", "device-1", self.config,
                                         httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
            self.assertIn("无法确认", reply)
        self.assertIn("配置不可用", await submit_command("测试", "device-1", "/nonexistent/config"))

    async def test_empty_command_never_sends(self):
        self.assertIn("请说", await submit_command("。", "device-1", self.config))

    async def test_wake_phrase_stays_local(self):
        conn = SimpleNamespace(config={"grok_bot": {"enabled": True}, "wakeup_words": ["你好宗主"]})
        self.assertFalse(await handle_grok_bot(conn, "你好，宗主。"))

    def test_misheard_wake_phrase_is_recognised(self):
        for text in ["个你好，中猪公", "你好，中主", "你好总主。", "嗯，你好宗主"]:
            self.assertEqual(strip_wake_phrase(text), (True, ""), text)
        self.assertEqual(strip_wake_phrase("你好宗主，帮我查天气"), (True, "帮我查天气"))
        self.assertEqual(strip_wake_phrase("你好中主 整理新闻。"), (True, "整理新闻"))
        for text in ["你好", "你好，请整理新闻", "你好中午吃什么", "宗主你好", "整理你好宗主的文件"]:
            self.assertEqual(strip_wake_phrase(text)[0], False, text)

    def test_board_wake_word_is_matched_exactly(self):
        self.assertEqual(strip_wake_phrase("嗯，小志，帮我查天气", ["小志"]), (True, "帮我查天气"))
        self.assertEqual(strip_wake_phrase("你好，小雨。", ["你好小雨"]), (True, ""))
        self.assertEqual(strip_wake_phrase("小雨伞在哪", ["你好小雨"])[0], False)
        # The fuzzy rule for the default wake word still applies alongside.
        self.assertEqual(strip_wake_phrase("你好中主", ["你好小雨"]), (True, ""))

    def test_repeated_and_cut_off_wake_phrases_are_all_stripped(self):
        for text in ["宗主。你好宗主。", "宗主", "你好宗主，你好宗主", "嗯，宗主，你好中主"]:
            self.assertEqual(strip_wake_phrase(text, ["你好宗主"]), (True, ""), text)
        self.assertEqual(strip_wake_phrase("宗主，帮我查天气", ["你好宗主"]), (True, "帮我查天气"))
        self.assertEqual(strip_wake_phrase("小雨。你好小雨，整理新闻", ["你好小雨"]), (True, "整理新闻"))
        # A name that starts a sentence is not a wake word
        for text in ["宗主你好", "小雨伞在哪", "种猪价格"]:
            self.assertFalse(strip_wake_phrase(text, ["你好宗主", "你好小雨"])[0], text)

    async def test_board_reported_wake_word_stays_local(self):
        conn = SimpleNamespace(config={"grok_bot": {"enabled": True}, "wakeup_words": []},
                               device_wake_word="你好小雨")
        self.assertFalse(await handle_grok_bot(conn, "你好，小雨。"))

    async def test_board_wake_prefix_is_stripped_before_submit(self):
        conn = SimpleNamespace(config={"grok_bot": {"enabled": True, "config_file": str(self.config)},
                                       "wakeup_words": []},
                               logger=mock.MagicMock(), headers={"device-id": "device-1"},
                               client_abort=False, device_wake_word="你好小雨")
        def fake_submit(command, *args):
            fake_submit.command = command
            return "任务已提交"
        with mock.patch("core.handle.grokBotHandle.prepare_submission", fake_submit), \
                _fake_handlers(mock.MagicMock()):
            self.assertTrue(await handle_grok_bot(conn, "你好小雨，整理新闻"))
        self.assertEqual(fake_submit.command, "整理新闻")

    async def test_repeated_wake_phrase_is_not_submitted(self):
        conn = SimpleNamespace(config={"grok_bot": {"enabled": True, "config_file": str(self.config)},
                                       "wakeup_words": ["你好宗主"]},
                               logger=mock.MagicMock(), headers={"device-id": "device-1"})
        speak = mock.MagicMock()
        with mock.patch("core.handle.grokBotHandle.prepare_submission") as submit, _fake_handlers(speak):
            for text in ["个你好，中猪公", "宗主。你好宗主。"]:
                speak.reset_mock()
                self.assertTrue(await handle_grok_bot(conn, text))
                speak.assert_called_once_with(conn, "我在。")
            submit.assert_not_called()

    async def test_wake_prefix_is_stripped_before_submit(self):
        conn = SimpleNamespace(config={"grok_bot": {"enabled": True, "config_file": str(self.config)},
                                       "wakeup_words": ["你好宗主"]},
                               logger=mock.MagicMock(), headers={"device-id": "device-1"},
                               client_abort=False)
        def fake_submit(command, *args):
            fake_submit.command = command
            return "任务已提交"
        with mock.patch("core.handle.grokBotHandle.prepare_submission", fake_submit), \
                _fake_handlers(mock.MagicMock()):
            self.assertTrue(await handle_grok_bot(conn, "你好中主，帮我查天气"))
        self.assertEqual(fake_submit.command, "帮我查天气")


if __name__ == "__main__":
    unittest.main()
