"""G18b：网关页面上改东西。口令可选（默认不设，打开页面就能改）。"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.gateway import control, status
from core.providers.tools.device_mcp.mcp_handler import MCPClient

OPEN = {"server": {"auth_key": "k"}}
LOCKED = {"server": {"auth_key": "k"}, "gateway": {"password": "1234"}}


class FakeBoard:
    """Answers like the firmware; `silent` tools never answer (the board left to reboot)."""

    def __init__(self, silent=(), theme_ok=True):
        self.device_id, self.features, self.config = "94:a9:90:2d:a3:70", {"mcp": True}, {}
        self.mcp_client, self.calls = MCPClient(), []
        self.silent, self.theme_ok = set(silent), theme_ok
        self.websocket = SimpleNamespace(send=self._send)

    async def _send(self, raw):
        request = json.loads(raw)["payload"]
        params = request["params"]
        if request["method"] == "tools/list":
            result = {"tools": []}
        else:
            self.calls.append((params["name"], params.get("arguments")))
            if params["name"] in self.silent:
                return
            body = {"self.get_device_status": {"audio_speaker": {"volume": 40}},
                    "self.get_system_info": {}}.get(params["name"], self.theme_ok)
            result = {"content": [{"type": "text", "text": json.dumps(body)}], "isError": False}
        await self.mcp_client.resolve_call_result(request["id"], result)


_wait_for = asyncio.wait_for


async def _short_wait(future, timeout):
    return await _wait_for(future, min(timeout, 0.1))


class PasswordTest(unittest.TestCase):
    def test_no_password_means_open(self):
        self.assertFalse(control.password_required(OPEN))
        self.assertTrue(control.allowed(OPEN, ""))

    def test_password_gives_a_token_the_page_keeps(self):
        self.assertTrue(control.password_required(LOCKED))
        self.assertIsNone(control.login(LOCKED, "0000"))
        token = control.login(LOCKED, "1234")
        self.assertNotIn("1234", token)
        self.assertTrue(control.allowed(LOCKED, token))
        for bad in ("", "x", control.token_for(LOCKED | {"server": {"auth_key": "other"}}, "1234")):
            self.assertFalse(control.allowed(LOCKED, bad))


class BoardActionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        status._boards.clear()
        patcher = mock.patch.object(status, "BOARDS_PATH", Path(tempfile.mkdtemp()) / "gateway_boards.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    async def board(self, **kwargs):
        conn = FakeBoard(**kwargs)
        await conn.mcp_client.set_ready(True)
        return conn

    async def test_volume_is_set_and_read_back(self):
        conn = await self.board()
        result = await control.board_action(conn, "volume", "40")
        self.assertEqual(conn.calls[0], ("self.audio_speaker.set_volume", {"volume": 40}))
        self.assertEqual(result["message"], "已改好。")
        self.assertEqual(status._boards[conn.device_id]["info"]["volume"], 40)

    async def test_brightness_and_theme(self):
        conn = await self.board()
        await control.board_action(conn, "brightness", 75)
        await control.board_action(conn, "theme", "dark")
        self.assertIn(("self.screen.set_brightness", {"brightness": 75}), conn.calls)
        self.assertIn(("self.screen.set_theme", {"theme": "dark"}), conn.calls)
        with self.assertRaises(control.ControlError):
            await control.board_action(await self.board(theme_ok=False), "theme", "light")

    async def test_bad_values_are_refused_before_the_board_is_asked(self):
        conn = await self.board()
        for action, value in (("volume", 101), ("volume", "loud"), ("brightness", -1), ("theme", "blue")):
            with self.assertRaises(control.ControlError, msg=(action, value)):
                await control.board_action(conn, action, value)
        self.assertEqual(conn.calls, [])

    async def test_reboot_and_wifi_set_up_count_even_when_the_board_leaves_first(self):
        for action, tool in (("reboot", "self.reboot"), ("wifi_config", "self.system.reconfigure_wifi")):
            conn = await self.board(silent={tool})
            with mock.patch.object(asyncio, "wait_for", side_effect=_short_wait):
                result = await control.board_action(conn, action)
            self.assertEqual(conn.calls, [(tool, {})])
            self.assertEqual(result["message"], control.LEAVING[action])


class MusicActionTest(unittest.IsolatedAsyncioTestCase):
    async def test_nothing_playing(self):
        with mock.patch("core.gateway.skills.music.player.current_music", return_value=None):
            for action in ("music_pause", "music_next", "music_stop"):
                with self.assertRaises(control.ControlError):
                    await control.music_action(action)

    async def test_transport_and_mac_volume(self):
        song = SimpleNamespace(name="晴天", artist="周杰伦")
        music = mock.MagicMock(current=song)
        music.next.return_value = SimpleNamespace(name="青花瓷", artist="周杰伦")
        with mock.patch("core.gateway.skills.music.player.current_music", return_value=music), \
                mock.patch("core.gateway.skills.music.player.set_system_volume", side_effect=lambda v: v) as volume:
            self.assertEqual((await control.music_action("music_pause"))["message"], "已暂停。")
            self.assertEqual((await control.music_action("music_next"))["message"], "正在播放：周杰伦的青花瓷。")
            self.assertEqual((await control.music_action("mac_volume", "30"))["message"], "电脑音量调到 30。")
        music.pause.assert_called_once()
        volume.assert_called_once_with(30)


if __name__ == "__main__":
    unittest.main()
