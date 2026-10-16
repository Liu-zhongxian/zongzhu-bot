import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import httpx
from core.handle.grokBotHandle import extract_command, submit_command, handle_grok_bot, _recent


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


if __name__ == "__main__":
    unittest.main()
