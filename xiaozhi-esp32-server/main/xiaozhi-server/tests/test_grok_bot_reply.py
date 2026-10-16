import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from core.handle.grokBotReply import (prepare_reply, read_reply, deliver_replies,
                                      waiting_for_reply, hold_connection, watch_replies,
                                      update_wait_ui, resume_bot_input)
from core.handle.grokBotHandle import submit_command, _recent


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
        with patch("core.handle.grokBotReply.asyncio.sleep", AsyncMock(side_effect=[None, asyncio.CancelledError])), \
             patch("core.handle.grokBotReply.hold_connection", AsyncMock()) as hold:
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

    async def test_second_request_can_enter_wait_again(self):
        self.conn.features = {"bot_ui": True}
        self.conn.reset_audio_states = Mock()
        await update_wait_ui(self.conn, self.directory, 300)
        resume_bot_input(self.conn)
        prepare_reply(self.directory, "ESP32-" + "b" * 32, "board-1")
        await update_wait_ui(self.conn, self.directory, 300)
        self.assertTrue(self.conn.bot_ui_waiting)
        self.assertEqual(self.conn.websocket.send.await_count, 2)


if __name__ == "__main__":
    unittest.main()
