import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from core.gateway import waiting
from core.gateway.agents.grok_webhook import GrokWebhookAgent
from core.handle.grokBotReply import prepare_reply, read_reply, waiting_for_reply, accept_reply
from core.handle.grokBotHandle import submit_command, _recent

AGENT = GrokWebhookAgent()
# The waiting screen and reply delivery moved to core/gateway/waiting.py (G4); these keep the
# old names so the assertions below are the ones written for the Grok-only code.
hold_connection = waiting.hold_connection
resume_bot_input = waiting.resume_input


def _use(conn, directory, wait_seconds=300, hint_seconds=30):
    webhook = Path(directory) / "webhook.json"
    webhook.write_text(json.dumps({"reply_dir": str(directory), "reply_wait_seconds": wait_seconds,
                                   "approval_hint_seconds": hint_seconds}))
    conn.config = dict(getattr(conn, "config", {}), grok_bot={"config_file": str(webhook)})


async def deliver_replies(conn, directory):
    _use(conn, directory)
    return await waiting.deliver(conn, AGENT)


async def update_wait_ui(conn, directory, wait_seconds, hint_seconds=30):
    _use(conn, directory, wait_seconds, hint_seconds)
    await waiting.update_screen(conn, AGENT)


async def watch_replies(conn):
    await waiting.watch(conn, AGENT)


class GrokBotReplyTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.request_id = "ESP32-" + "a" * 32
        self.pending, self.result = prepare_reply(self.directory, self.request_id, "board-1")
        self.conn = SimpleNamespace(
            headers={"device-id": "board-1"}, stop_event=asyncio.Event(),
            client_is_speaking=False, client_have_voice=False, just_woken_up=False,
            websocket=SimpleNamespace(send=AsyncMock()), session_id="session-1", logger=Mock(),
            tts=Mock(), client_abort=False,
        )
        self.speak = Mock()
        mock_intent = patch.dict("sys.modules", {"core.handle.intentHandler": SimpleNamespace(speak_txt=self.speak)})
        mock_intent.start()
        self.addCleanup(mock_intent.stop)

    def write_reply(self, request_id=None, text="这是 Bot 的实际回复。"):
        self.result.write_text(json.dumps({"request_id": request_id or self.request_id, "text": text}), encoding="utf-8")

    async def test_reply_queued_once_with_speaking_state_and_subtitles(self):
        self.write_reply()
        self.assertTrue(await deliver_replies(self.conn, self.directory))
        message = json.loads(self.conn.websocket.send.call_args.args[0])
        self.assertEqual(message["text"], "这是 Bot 的实际回复。")
        self.assertEqual(message["state"], "sentence_start")
        self.assertEqual(message["request_id"], self.request_id)
        self.assertTrue(self.conn.client_is_speaking)
        self.assertFalse(self.conn.client_abort)
        self.assertEqual(self.conn.sentence_id, self.conn.bot_reply_sentence_id)
        self.speak.assert_called_once_with(self.conn, "这是 Bot 的实际回复。")
        first = json.loads(self.conn.websocket.send.call_args_list[0].args[0])
        self.assertEqual(first["state"], "start")
        self.assertFalse(self.pending.exists())
        self.conn.client_is_speaking = False
        await deliver_replies(self.conn, self.directory)
        self.assertEqual(self.conn.websocket.send.await_count, 2)
        self.speak.assert_called_once()

    async def test_wrong_device_or_request_never_delivered(self):
        self.write_reply(request_id="ESP32-" + "b" * 32)
        await deliver_replies(self.conn, self.directory)
        self.write_reply()
        self.conn.headers["device-id"] = "board-2"
        await deliver_replies(self.conn, self.directory)
        self.conn.websocket.send.assert_not_awaited()
        self.assertTrue(self.pending.exists())

    async def test_busy_device_defers_reply(self):
        self.write_reply()
        for field in ["client_is_speaking", "client_have_voice", "just_woken_up"]:
            setattr(self.conn, field, True)
            await deliver_replies(self.conn, self.directory)
            setattr(self.conn, field, False)
        self.conn.websocket.send.assert_not_awaited()
        await deliver_replies(self.conn, self.directory)
        self.speak.assert_called_once()

    async def test_tts_initialization_defers_delivery(self):
        self.write_reply()
        self.conn.tts = None
        await deliver_replies(self.conn, self.directory)
        self.speak.assert_not_called()
        self.conn.websocket.send.assert_not_awaited()
        self.assertTrue(self.pending.exists())

    async def test_queue_failure_restores_state_and_preserves_reply(self):
        self.write_reply()
        self.speak.side_effect = RuntimeError("queue unavailable")
        with self.assertRaises(RuntimeError):
            await deliver_replies(self.conn, self.directory)
        self.assertTrue(self.pending.exists())
        self.assertFalse(self.conn.client_is_speaking)
        self.assertEqual(json.loads(self.conn.websocket.send.call_args.args[0])["state"], "stop")

    async def test_user_interrupt_during_start_does_not_queue_or_replay(self):
        self.write_reply()
        async def interrupt(message):
            self.conn.client_abort = True
            self.conn.client_is_speaking = False
        self.conn.websocket.send.side_effect = interrupt
        await deliver_replies(self.conn, self.directory)
        self.speak.assert_not_called()
        self.assertFalse(self.pending.exists())

    async def test_long_reply_keeps_connection_after_pending_is_consumed(self):
        self.pending.unlink()
        config = self.directory / "config.json"
        config.write_text(json.dumps({"reply_dir": str(self.directory)}))
        self.conn.config = {"grok_bot": {"config_file": str(config)}}
        self.conn.client_is_speaking = True
        self.conn.bot_reply_sentence_id = self.conn.sentence_id = "reply-playing"
        with patch("core.gateway.waiting.asyncio.sleep", AsyncMock(side_effect=[None, asyncio.CancelledError])), \
             patch("core.gateway.waiting.hold_connection", AsyncMock()) as hold:
            with self.assertRaises(asyncio.CancelledError):
                await watch_replies(self.conn)
            hold.assert_awaited_once_with(self.conn)

    async def test_send_failure_keeps_reply_for_reconnect(self):
        self.write_reply()
        self.conn.websocket.send.side_effect = ConnectionError("disconnected")
        with self.assertRaises(ConnectionError):
            await deliver_replies(self.conn, self.directory)
        self.assertTrue(self.pending.exists())
        self.conn.websocket = SimpleNamespace(send=AsyncMock())
        self.conn.session_id = "reconnected-session"
        await deliver_replies(self.conn, self.directory)
        message = json.loads(self.conn.websocket.send.call_args.args[0])
        self.assertEqual(message["session_id"], "reconnected-session")

    def test_waiting_only_for_recent_undelivered_request_of_this_device(self):
        created = json.loads(self.pending.read_text())["created"]
        self.assertTrue(waiting_for_reply(self.directory, "board-1", 300, created + 10))
        self.assertFalse(waiting_for_reply(self.directory, "board-2", 300, created + 10))
        self.assertFalse(waiting_for_reply(self.directory, "board-1", 300, created + 301))
        self.pending.rename(self.pending.with_name(self.request_id + ".sent.json"))
        self.assertFalse(waiting_for_reply(self.directory, "board-1", 300, created + 10))

    async def test_hold_refreshes_idle_timer_and_rate_limits_keepalive(self):
        self.conn.last_activity_time = 0.0
        await hold_connection(self.conn)
        await hold_connection(self.conn)
        self.assertGreater(self.conn.last_activity_time, 0)
        self.conn.websocket.send.assert_awaited_once()
        self.assertEqual(json.loads(self.conn.websocket.send.call_args.args[0])["type"], "bot_wait")

    async def test_reply_from_earlier_session_is_labelled(self):
        self.write_reply()
        self.conn.bot_reply_since = json.loads(self.pending.read_text())["created"] + 1
        await deliver_replies(self.conn, self.directory)
        message = json.loads(self.conn.websocket.send.call_args.args[0])
        self.assertEqual(message["text"], "稍早的 Bot 回复：这是 Bot 的实际回复。")

    def test_partial_invalid_oversized_or_symlink_reply_rejected(self):
        self.result.write_text('{"request_id":')
        self.assertIsNone(read_reply(self.pending, "board-1"))
        for text in [None, {}, " ", "字" * 8001]:
            self.write_reply(text=text)
            self.assertIsNone(read_reply(self.pending, "board-1"))
        self.result.unlink()
        target = self.directory / "other.json"
        target.write_text(json.dumps({"request_id": self.request_id, "text": "other"}))
        self.result.symlink_to(target)
        self.assertIsNone(read_reply(self.pending, "board-1"))

    async def test_submission_prepares_correlated_return_and_retains_uncertain(self):
        _recent.clear()
        config = self.directory / "config.json"
        config.write_text(json.dumps({"url": "https://example.test", "token": "test-secret", "reply_dir": str(self.directory)}))
        requests = []
        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            self.assertEqual(body["user_text"], "今天怎么样")
            self.assertIn(body["request_id"] + ".json", body["command"])
            self.assertNotIn("test-secret", body["command"])
            self.assertTrue((self.directory / (body["request_id"] + ".pending.json")).exists())
            raise httpx.ReadTimeout("unknown", request=request)
        result = await submit_command("今天怎么样", "board-1", config, httpx.MockTransport(respond))
        self.assertIn("无法确认", result)
        self.assertTrue((self.directory / (requests[0]["request_id"] + ".pending.json")).exists())

    async def test_wait_ui_requires_capability_and_finished_acknowledgement(self):
        await update_wait_ui(self.conn, self.directory, 300)
        self.conn.features = {"bot_ui": True}
        self.conn.client_is_speaking = True
        await update_wait_ui(self.conn, self.directory, 300)
        self.conn.websocket.send.assert_not_awaited()
        self.conn.client_is_speaking = False
        self.conn.reset_audio_states = Mock()
        await update_wait_ui(self.conn, self.directory, 300)
        self.assertTrue(self.conn.bot_ui_waiting)
        self.assertEqual(json.loads(self.conn.websocket.send.call_args.args[0])["state"], "waiting")
        self.conn.reset_audio_states.assert_called_once()

    async def test_explicit_wake_does_not_reenter_same_wait_or_interrupt_input(self):
        self.conn.features = {"bot_ui": True}
        self.conn.reset_audio_states = Mock()
        await update_wait_ui(self.conn, self.directory, 300)
        resume_bot_input(self.conn)
        await update_wait_ui(self.conn, self.directory, 300)
        self.assertFalse(self.conn.bot_ui_waiting)
        self.conn.websocket.send.assert_awaited_once()
        self.write_reply()
        await deliver_replies(self.conn, self.directory)
        self.speak.assert_not_called()
        self.assertTrue(self.pending.exists())

    async def test_wait_timeout_is_announced_once_and_keeps_pending(self):
        self.conn.features = {"bot_ui": True}
        self.conn.reset_audio_states = Mock()
        await update_wait_ui(self.conn, self.directory, 300)
        await update_wait_ui(self.conn, self.directory, 0)
        await update_wait_ui(self.conn, self.directory, 0)
        self.assertEqual(self.conn.websocket.send.await_count, 2)
        self.assertEqual(json.loads(self.conn.websocket.send.call_args.args[0])["state"], "timeout")
        self.assertTrue(self.pending.exists())

    async def test_reply_restores_full_text_and_exits_wait_before_audio(self):
        self.conn.features = {"bot_ui": True}
        self.conn.bot_ui_waiting = True
        self.write_reply(text="完整正文。第二句也要保留。")
        await deliver_replies(self.conn, self.directory)
        messages = [json.loads(call.args[0]) for call in self.conn.websocket.send.call_args_list]
        self.assertEqual(messages[0]["state"], "reply")
        self.assertEqual(messages[0]["text"], "完整正文。第二句也要保留。")
        self.assertEqual(messages[1]["state"], "start")
        self.assertFalse(self.conn.bot_ui_waiting)

    async def test_long_wait_shows_approval_hint_once(self):
        self.conn.features = {"bot_ui": True}
        self.conn.reset_audio_states = Mock()
        await update_wait_ui(self.conn, self.directory, 300)
        self.assertEqual(self.conn.websocket.send.await_count, 1)
        created = json.loads(self.pending.read_text())["created"]
        with patch("core.handle.grokBotReply.time.time", return_value=created + 31):
            await update_wait_ui(self.conn, self.directory, 300)
            await update_wait_ui(self.conn, self.directory, 300)
        self.assertEqual(self.conn.websocket.send.await_count, 2)
        message = json.loads(self.conn.websocket.send.call_args.args[0])
        self.assertEqual(message["state"], "sentence_start")
        self.assertIn("授权", message["text"])
        self.assertTrue(self.conn.bot_ui_waiting)

    async def test_approval_hint_skipped_after_wake_or_when_disabled(self):
        self.conn.features = {"bot_ui": True}
        self.conn.reset_audio_states = Mock()
        created = json.loads(self.pending.read_text())["created"]
        with patch("core.handle.grokBotReply.time.time", return_value=created + 31):
            await update_wait_ui(self.conn, self.directory, 300, 0)
            self.assertEqual(self.conn.websocket.send.await_count, 1)
            resume_bot_input(self.conn)
            await update_wait_ui(self.conn, self.directory, 300)
        self.assertEqual(self.conn.websocket.send.await_count, 1)

    async def test_second_request_can_enter_wait_again(self):
        self.conn.features = {"bot_ui": True}
        self.conn.reset_audio_states = Mock()
        await update_wait_ui(self.conn, self.directory, 300)
        resume_bot_input(self.conn)
        prepare_reply(self.directory, "ESP32-" + "b" * 32, "board-1")
        await update_wait_ui(self.conn, self.directory, 300)
        self.assertTrue(self.conn.bot_ui_waiting)
        self.assertEqual(self.conn.websocket.send.await_count, 2)


    def write_follow_up(self, n, text, request_id=None):
        path = self.directory / f"{request_id or self.request_id}.more-{n}.json"
        path.write_text(json.dumps({"request_id": request_id or self.request_id, "text": text}), encoding="utf-8")
        return path

    async def test_follow_ups_are_said_after_the_first_answer(self):
        # 2026-10-25 实机: the first answer was wrong, the correction only reached the Grok chat
        self.write_follow_up(1, "更正：其实能看到。")
        await deliver_replies(self.conn, self.directory)
        self.speak.assert_not_called()  # nothing before the first answer
        self.write_reply(text="看不到其他 Bot。")
        await deliver_replies(self.conn, self.directory)
        self.conn.client_is_speaking = False
        await deliver_replies(self.conn, self.directory)
        self.conn.client_is_speaking = False
        self.write_follow_up(2, "New Bot 回复了：你好。")
        await deliver_replies(self.conn, self.directory)
        self.conn.client_is_speaking = False
        await deliver_replies(self.conn, self.directory)  # each said once
        said = [c.args[1] for c in self.speak.call_args_list]
        self.assertEqual(said, ["看不到其他 Bot。", "Bot 补充：更正：其实能看到。", "Bot 补充：New Bot 回复了：你好。"])
        self.assertTrue((self.directory / f"{self.request_id}.more-2.sent.json").exists())

    async def test_follow_ups_only_for_this_board_and_recent_requests(self):
        self.write_reply()
        await deliver_replies(self.conn, self.directory)
        self.conn.client_is_speaking = False
        self.speak.reset_mock()
        sent = self.directory / f"{self.request_id}.sent.json"
        other = "ESP32-" + "c" * 32
        prepare_reply(self.directory, other, "board-2")[0].rename(self.directory / f"{other}.sent.json")
        self.write_follow_up(1, "别的板子的。", other)
        metadata = json.loads(sent.read_text())
        metadata["created"] -= 2 * 24 * 3600
        sent.write_text(json.dumps(metadata))
        self.write_follow_up(1, "两天前的请求。")
        await deliver_replies(self.conn, self.directory)
        self.speak.assert_not_called()

    def test_instructions_tell_the_bot_where_follow_ups_go(self):
        _recent.clear()
        config = self.directory / "config.json"
        config.write_text(json.dumps({"url": "https://example.test", "token": "t", "reply_dir": str(self.directory)}))
        from core.handle.grokBotHandle import prepare_submission
        submission = prepare_submission("帮我查天气", "board-1", config)
        self.assertIn(submission.payload["request_id"] + ".more-1.json", submission.payload["command"])

    async def test_hello_without_features_is_not_an_error(self):
        # conn.features stays None when the board's hello has no features field.
        self.conn.features = None
        await update_wait_ui(self.conn, self.directory, 300)
        self.conn.websocket.send.assert_not_awaited()

class HttpReplyTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.request_id = "ESP32-" + "c" * 32
        self.pending, self.result = prepare_reply(self.directory, self.request_id, "board-1", "one-time")

    def test_pending_keeps_only_token_hash(self):
        metadata = json.loads(self.pending.read_text())
        self.assertNotIn("one-time", self.pending.read_text())
        self.assertEqual(len(metadata["token_sha256"]), 64)

    def test_posted_reply_becomes_deliverable_result_once(self):
        self.assertEqual(accept_reply(self.directory, self.request_id, "one-time", "  回复内容  "), 200)
        self.assertEqual(read_reply(self.pending, "board-1")[1], "回复内容")
        self.assertEqual(self.result.stat().st_mode & 0o777, 0o600)
        self.assertEqual(accept_reply(self.directory, self.request_id, "one-time", "第二次"), 409)
        self.assertEqual(list(self.directory.glob(".*.tmp")), [])

    def test_rejects_wrong_token_unknown_request_and_bad_text(self):
        self.assertEqual(accept_reply(self.directory, self.request_id, "guess", "x"), 403)
        self.assertEqual(accept_reply(self.directory, "ESP32-" + "d" * 32, "one-time", "x"), 404)
        self.assertEqual(accept_reply(self.directory, "../etc/passwd", "one-time", "x"), 400)
        self.assertEqual(accept_reply(self.directory, self.request_id, "one-time", "   "), 400)
        self.assertEqual(accept_reply(self.directory, self.request_id, "one-time", "长" * 8001), 400)
        self.assertEqual(accept_reply(self.directory, self.request_id, None, "x"), 400)
        self.assertFalse(self.result.exists())

    def test_file_mode_request_cannot_be_answered_over_http(self):
        rid = "ESP32-" + "e" * 32
        prepare_reply(self.directory, rid, "board-1")
        self.assertEqual(accept_reply(self.directory, rid, "anything", "x"), 403)

    def test_expired_request_rejected(self):
        metadata = json.loads(self.pending.read_text())
        metadata["created"] -= 2 * 24 * 3600
        self.pending.write_text(json.dumps(metadata))
        self.assertEqual(accept_reply(self.directory, self.request_id, "one-time", "x"), 404)

    async def test_http_mode_instruction_keeps_webhook_secret_and_posts_reply(self):
        _recent.clear()
        config = self.directory / "config.json"
        config.write_text(json.dumps({
            "url": "https://example.test", "token": "test-secret", "reply_dir": str(self.directory),
            "reply_url": "https://nas.example.test/bot/reply",
        }))
        seen = {}
        def respond(request):
            seen["auth"] = request.headers["Authorization"]
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"success": True, "runUuid": "run-1"})
        result = await submit_command("查天气", "board-1", config, httpx.MockTransport(respond))
        self.assertIn("任务已提交", result)
        self.assertEqual(seen["auth"], "Bearer test-secret")
        body = seen["body"]
        self.assertNotIn("test-secret", body["command"])
        self.assertIn("curl -sS -X POST https://nas.example.test/bot/reply", body["command"])
        token = json.loads(body["command"].split("\n")[3])["token"]
        self.assertEqual(accept_reply(self.directory, body["request_id"], token, "晴"), 200)

    async def test_plain_http_reply_url_refused(self):
        _recent.clear()
        config = self.directory / "config.json"
        config.write_text(json.dumps({
            "url": "https://example.test", "token": "t", "reply_dir": str(self.directory),
            "reply_url": "http://nas.local/bot/reply",
        }))
        transport = httpx.MockTransport(lambda request: self.fail("must not submit"))
        self.assertIn("HTTPS", await submit_command("查天气", "board-1", config, transport))


class BotReplyEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        from core.api.bot_reply_handler import BotReplyHandler
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        self.config_file = directory / "config.json"
        self.config_file.write_text(json.dumps({"reply_dir": str(directory), "reply_url": "https://x/bot/reply"}))
        self.request_id = "ESP32-" + "f" * 32
        prepare_reply(directory, self.request_id, "board-1", "tok")
        app = web.Application()
        with patch("core.api.bot_reply_handler.setup_logging", Mock()):
            handler = BotReplyHandler({"grok_bot": {"config_file": str(self.config_file)}})
        app.router.add_post("/bot/reply", handler.handle_post)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_accepts_valid_reply_and_reports_errors(self):
        ok = await self.client.post("/bot/reply", json={"request_id": self.request_id, "token": "tok", "text": "好"})
        self.assertEqual((ok.status, (await ok.json())["ok"]), (200, True))
        again = await self.client.post("/bot/reply", json={"request_id": self.request_id, "token": "tok", "text": "好"})
        self.assertEqual(again.status, 409)
        bad = await self.client.post("/bot/reply", data=b"not json", headers={"Content-Type": "application/json"})
        self.assertEqual(bad.status, 400)
        big = await self.client.post("/bot/reply", data=b"x" * (65 * 1024))
        self.assertEqual(big.status, 413)

    async def test_disabled_without_reply_url(self):
        self.config_file.write_text(json.dumps({"reply_dir": "/tmp"}))
        response = await self.client.post("/bot/reply", json={"request_id": self.request_id, "token": "tok", "text": "好"})
        self.assertEqual(response.status, 503)


if __name__ == "__main__":
    unittest.main()
