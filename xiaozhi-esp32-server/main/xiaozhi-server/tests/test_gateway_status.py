import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core import gateway
from core.gateway import agent_store, status
from core.gateway.page import GatewayPageHandler

CONFIG = {"wakeup_words": ["你好宗主"], "server": {"http_port": 8003},
          "grok_bot": {"enabled": True, "config_file": "secret-webhook.json"}}


def make_conn(device="94:a9:90:2d:a3:70", **extra):
    values = dict(config=CONFIG, device_id=device, client_ip="192.168.1.20", device_wake_word="你好宗主",
                  bot_ui_waiting=False, client_is_speaking=False, logger=mock.MagicMock())
    values.update(extra)
    return SimpleNamespace(**values)


class StatusTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for store in (status._boards, status._conns, status._recent):
            store.clear()
        status._totals.update(sentences=0, local=0)
        # the board's chosen AI is read from data/agent_sessions.json; keep the real one out of it
        temp = Path(tempfile.mkdtemp())
        for target, name in ((agent_store, "agent_sessions.json"),):
            patcher = mock.patch.object(target, "PATH", temp / name)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(status, "BOARDS_PATH", temp / "gateway_boards.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def patch_handlers(self, music=False, bot=False):
        for target, value in (("core.gateway.skills.music.command.handle_local_command", music),
                              ("core.gateway.hand_over", bot)):
            patcher = mock.patch(target, mock.AsyncMock(return_value=value))
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_each_sentence_records_the_layer_that_took_it(self):
        conn = make_conn()
        self.patch_handlers(music=True)
        await gateway.dispatch(conn, "暂停")
        self.patch_handlers(bot=True)
        await gateway.dispatch(conn, "帮我查天气")
        await gateway.dispatch(conn, "宗主。你好宗主。")
        await gateway.dispatch(conn, "你好宗主")
        recent = status.snapshot(CONFIG)["recent"]
        self.assertEqual([(r["text"], r["layer"], r["target"]) for r in recent], [
            ("你好宗主", "wake", "唤醒问候"), ("宗主。你好宗主。", "filter", "不提交"),
            ("帮我查天气", "agent", "Grok Bot"), ("暂停", "skill", "点歌")])
        # the wake greeting is not counted as something said
        self.assertEqual(status.snapshot(CONFIG)["totals"], {"sentences": 3, "local": 2})

    async def test_repeat_blocked_by_the_bot_is_not_shown_as_handed_over(self):
        conn = make_conn()

        async def bot(conn, agent, text):  # what hand_over does when the Bot blocks a repeat within 30s
            conn.gateway_not_sent = "刚才已尝试提交同一条指令，已阻止重复发送。请在 Bot 对话里查看。"
            return True

        self.patch_handlers()
        with mock.patch("core.gateway.hand_over", bot):
            await gateway.dispatch(conn, "别再放了")
        self.patch_handlers(bot=True)
        await gateway.dispatch(conn, "别再放了")  # the flag does not stick to the next sentence
        recent = status.snapshot(CONFIG)["recent"]
        self.assertEqual([(r["layer"], r["target"]) for r in recent],
                         [("agent", "Grok Bot"), ("filter", "拦下重复")])

    async def test_wake_row_shows_the_board_wake_word(self):
        self.patch_handlers()
        conn = make_conn(config=dict(CONFIG, wakeup_words=["你好宗主", "嘿你好呀"]))
        await gateway.dispatch(conn, "嘿，你好呀")  # what upstream passes on after a wake word
        self.assertEqual(status.snapshot(CONFIG)["recent"][0]["text"], "你好宗主")

    async def test_recent_keeps_the_last_thirty(self):
        self.patch_handlers(bot=True)
        conn = make_conn()
        for i in range(35):
            await gateway.dispatch(conn, f"任务 {i}")
        recent = status.snapshot(CONFIG)["recent"]
        self.assertEqual(len(recent), 30)
        self.assertEqual(recent[0]["text"], "任务 34")

    async def test_asr_original_shown_only_when_correction_changed_it(self):
        self.patch_handlers(music=True)
        conn = make_conn()
        status.note_asr(conn, "放周杰伦的请帖", "放周杰伦的晴天")
        await gateway.dispatch(conn, "放周杰伦的晴天")
        status.note_asr(conn, "暂停", "暂停")
        await gateway.dispatch(conn, "暂停")
        status.note_asr(conn, "别放了，不要了", "别放了， 不要了")  # spacing only
        await gateway.dispatch(conn, "别放了， 不要了")
        recent = status.snapshot(CONFIG)["recent"]
        self.assertEqual([r["raw"] for r in recent], ["", "", "放周杰伦的请帖"])

    async def test_first_audio_is_timed_once(self):
        self.patch_handlers(music=True)
        conn = make_conn()
        await gateway.dispatch(conn, "暂停")
        status.note_audio(conn)
        first = conn.gateway_record["first_audio"]
        await asyncio.sleep(0.02)
        status.note_audio(conn)
        self.assertIsNotNone(first)
        self.assertEqual(conn.gateway_record["first_audio"], first)

    async def test_time_to_sound_counts_from_the_end_of_speech(self):
        self.patch_handlers(music=True)
        conn = make_conn()
        status.note_asr(conn, "暂停", "暂停", status.time.monotonic() - 0.5)
        await gateway.dispatch(conn, "暂停")
        status.note_audio(conn)
        self.assertAlmostEqual(conn.gateway_record["first_audio"], 0.5, delta=0.05)

    def test_boards_online_offline_and_state(self):
        status.note_ota("94:a9:90:2d:a3:70", "lichuang-dev", "2.5.2.9", "192.168.1.20")
        status.note_ota("aa:bb:cc:dd:ee:01", "esp32-s3-touch-amoled-1.75c", "2.5.2.9", "192.168.1.21")
        status.note_ota("02:00:00:00:00:04", "local-test", "2.5.2.9", "127.0.0.1")
        live = make_conn(bot_ui_waiting=True, gateway_wait_since=status.time.time() - 12)
        status.connected(live)
        boards = status.snapshot(CONFIG)["boards"]
        # the check script's simulated board is hidden once it is not connected
        self.assertEqual([(b["name"], b["online"]) for b in boards], [("立创实战派", True), ("微雪 1.75C", False)])
        self.assertEqual(boards[0]["state"]["kind"], "waiting")
        self.assertAlmostEqual(boards[0]["state"]["seconds"], 12, delta=1)
        self.assertEqual((boards[0]["wake"], boards[0]["agent"]), ("你好宗主", "Grok Bot"))
        status.disconnected(live)
        self.assertFalse(status.snapshot(CONFIG)["boards"][0]["online"])

    def test_board_stays_on_the_page_across_a_restart(self):
        # 2026-10-25: since the fixed auth_key the board no longer reboots after a backend restart,
        # so no OTA comes in; the page used to forget it and showed it only while connected
        status.note_ota("94:a9:90:2d:a3:70", "lichuang-dev", "2.5.2.9", "192.168.1.20")
        status.note_ota("02:00:00:00:00:04", "local-test", "2.5.2.9", "127.0.0.1")
        live = make_conn()
        status.connected(live)
        status.disconnected(live)
        status._boards.clear()  # what a restart does to memory
        status.load()
        self.assertEqual(list(status._boards), ["94:a9:90:2d:a3:70"])  # check scripts are not kept
        board = status.snapshot(CONFIG)["boards"][0]
        self.assertEqual((board["name"], board["online"], board["wake"]), ("立创实战派", False, "你好宗主"))
        # a board seen only over WebSocket (no OTA since the restart) is listed too
        status.connected(make_conn(device="aa:bb:cc:dd:ee:02"))
        self.assertIn("板子 ee:02", [b["name"] for b in status.snapshot(CONFIG)["boards"]])

    def test_xiaoai_speaker_is_named_and_not_read_over_mcp(self):
        # 2026-10-30: the Xiaomi speaker comes in through open-xiaoai-bridge on this Mac; it has no MCP,
        # so reading board info only waited and came back empty
        status.note_ota("4b:2b:ba:c4:eb:f9", "open-xiaoai-bridge", "1.6.0", "127.0.0.1")
        status.note_ota("94:a9:90:2d:a3:70", "lichuang-dev", "2.5.2.9", "192.168.1.20")
        with mock.patch("core.gateway.board_info.start") as start:
            status.connected(make_conn(device="4b:2b:ba:c4:eb:f9", client_ip="127.0.0.1"))
            start.assert_not_called()
            status.connected(make_conn())
            start.assert_called_once()
        boards = {b["name"]: b for b in status.snapshot(CONFIG)["boards"]}
        self.assertTrue(boards["小米音箱 Pro"]["bridge"])
        self.assertFalse(boards["立创实战派"]["bridge"])

    async def test_status_endpoint_is_json_and_holds_no_config_secrets(self):
        status.note_ota("94:a9:90:2d:a3:70", "lichuang-dev", "2.5.2.9", "192.168.1.20")
        status.connected(make_conn())
        response = await GatewayPageHandler(CONFIG).handle_status(None)
        body = json.loads(response.body)
        self.assertEqual(body["boards"][0]["name"], "立创实战派")
        self.assertNotIn("secret-webhook", response.body.decode())
        self.assertNotIn("94:a9:90", response.body.decode())  # only the last 5 characters
        page = await GatewayPageHandler(CONFIG).handle_page(None)
        self.assertIn("/gateway/api/status", page.text)


if __name__ == "__main__":
    unittest.main()
