"""G8b：资源包里的唤醒词。真实资源包和刷机网页逐字节对比过（2026-10-30，三块板子都一样）。"""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.gateway import wake_assets
from core.gateway.wake_assets import (AssetFile, check_wake_word, pack_assets, pinyin_command,
                                      read_assets, set_wake_word, wake_word_of)
from core.providers.tools.device_mcp.mcp_handler import MCPClient


def _image(index=None):
    index = index if index is not None else {
        "version": 1, "multinet_model": {"language": "cn", "duration": 3000, "threshold": 0.2,
                                         "commands": [{"command": "ni hao zong zhu", "text": "你好宗主",
                                                       "action": "wake"}]}}
    return pack_assets([AssetFile("srmodels.bin", 0, 0, b"\x01\x02model"),
                        AssetFile("index.json", 0, 0, json.dumps(index).encode()),
                        AssetFile("happy.gif", 64, 48, bytes(range(256)))])


class WakeAssetsTest(unittest.TestCase):
    def test_pack_layout(self):
        image = _image()
        self.assertEqual(int.from_bytes(image[0:4], "little"), 3)
        self.assertEqual(int.from_bytes(image[4:8], "little"), sum(image[12:]) & 0xFFFF)
        self.assertEqual(int.from_bytes(image[8:12], "little"), len(image) - 12)
        self.assertEqual(pack_assets(read_assets(image)), image)

    def test_set_wake_word_keeps_other_files(self):
        image = _image()
        new = set_wake_word(image, "你好小雨", "ni hao xiao yu")
        self.assertEqual(wake_word_of(image)["text"], "你好宗主")
        self.assertEqual(wake_word_of(new), {"command": "ni hao xiao yu", "text": "你好小雨", "action": "wake"})
        old, changed = read_assets(image), read_assets(new)
        self.assertEqual([(f.name, f.width, f.height) for f in old], [(f.name, f.width, f.height) for f in changed])
        self.assertEqual([f.data for f in old if f.name != "index.json"],
                         [f.data for f in changed if f.name != "index.json"])
        index = json.loads(next(f for f in changed if f.name == "index.json").data)
        self.assertEqual(index["multinet_model"]["threshold"], 0.2)
        self.assertNotEqual(set_wake_word(image, "你好小雨", "ni hao xiao yu", threshold=0.3), new)

    def test_pinyin_command(self):
        self.assertEqual(pinyin_command("你好小雨"), "ni hao xiao yu")
        self.assertEqual(pinyin_command("绿色女孩"), "lv se nv hai")

    def test_bad_wake_words_are_refused(self):
        self.assertIsNone(check_wake_word("你好小雨", "ni hao xiao yu"))
        for text, command in [("hi esp", "hi esp"), ("雨", "yu"), ("你好小雨", "ni hao xiao"),
                              ("你好小雨", "Ni Hao Xiao Yu"), ("你好小雨", "ni hǎo xiǎo yǔ")]:
            self.assertIsNotNone(check_wake_word(text, command), (text, command))
        with self.assertRaises(ValueError):
            set_wake_word(_image(), "雨", "yu")

    def test_bad_images_are_refused(self):
        for image in [b"", b"\0" * 12, _image()[:40], _image({"version": 1})]:
            with self.assertRaises(ValueError):
                set_wake_word(image, "你好小雨", "ni hao xiao yu")


_wait_for = asyncio.wait_for


async def _short_wait(future, timeout):
    return await _wait_for(future, min(timeout, 0.1))


class FakeBoard:
    """A connection whose board answers every tools/call like the firmware ([user] tools are unlisted)."""

    def __init__(self, error=False, silent=False):
        self.device_id, self.features = "94:a9:90:2d:a3:70", {"mcp": True}
        self.config = {"server": {"vision_explain": "http://192.168.1.5:8003/mcp/vision/explain"}}
        self.mcp_client, self.sent = MCPClient(), []
        self.error, self.silent = error, silent
        self.websocket = SimpleNamespace(send=self._send)

    async def _send(self, raw):
        payload = json.loads(raw)["payload"]
        self.sent.append(payload["params"])
        if not self.silent:
            await self.mcp_client.resolve_call_result(
                payload["id"], {"content": [{"type": "text", "text": "true"}], "isError": self.error})


class WakeWordChangeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(wake_assets, "ASSETS_DIR", Path(self.tmp.name) / "wake_assets")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    async def test_change_sends_url_then_reboots(self):
        conn = FakeBoard()
        await conn.mcp_client.set_ready(True)
        result = await wake_assets.change_wake_word(conn, _image(), "你好小雨", "ni hao xiao yu")
        self.assertEqual([c["name"] for c in conn.sent], ["self.assets.set_download_url", "self.reboot"])
        url = conn.sent[0]["arguments"]["url"]
        self.assertEqual(result["url"], url)
        self.assertRegex(url, r"^http://192\.168\.1\.5:8003/gateway/assets/94a9902da370-[0-9a-f]{12}\.bin$")
        served = wake_assets.path_of(url.rsplit("/", 1)[1])
        self.assertEqual(wake_word_of(served.read_bytes())["text"], "你好小雨")
        # A second change replaces the first file; no reboot when asked not to.
        conn.sent.clear()
        second = await wake_assets.change_wake_word(conn, _image(), "你好小智", "ni hao xiao zhi", reboot=False)
        self.assertEqual([c["name"] for c in conn.sent], ["self.assets.set_download_url"])
        self.assertEqual(os.listdir(wake_assets.ASSETS_DIR), [second["url"].rsplit("/", 1)[1]])

    async def test_nothing_is_sent_for_a_bad_wake_word_or_unready_board(self):
        conn = FakeBoard()
        with self.assertRaises(RuntimeError):  # MCP never gets ready
            await wake_assets.call_board_tool(conn, "self.reboot", {}, ready_wait=0.3)
        await conn.mcp_client.set_ready(True)
        with self.assertRaises(ValueError):
            await wake_assets.change_wake_word(conn, _image(), "雨", "yu")
        self.assertEqual(conn.sent, [])

    async def test_waits_for_mcp_of_a_board_that_just_woke(self):
        conn = FakeBoard()
        asyncio.get_running_loop().call_later(0.5, lambda: asyncio.ensure_future(conn.mcp_client.set_ready(True)))
        await wake_assets.call_board_tool(conn, "self.reboot", {})
        self.assertEqual([c["name"] for c in conn.sent], ["self.reboot"])

    async def test_board_gone_before_answering_reboot_still_counts(self):
        conn = FakeBoard()
        await conn.mcp_client.set_ready(True)
        send = conn.websocket.send

        async def no_reply_to_reboot(raw):
            if json.loads(raw)["payload"]["params"]["name"] == "self.reboot":
                conn.sent.append({"name": "self.reboot"})
                return
            await send(raw)

        conn.websocket = SimpleNamespace(send=no_reply_to_reboot)
        with mock.patch.object(asyncio, "wait_for", side_effect=_short_wait):
            result = await wake_assets.change_wake_word(conn, _image(), "你好小雨", "ni hao xiao yu")
        self.assertEqual([c["name"] for c in conn.sent], ["self.assets.set_download_url", "self.reboot"])
        self.assertIn("多半已经在重启", result["note"])

    async def test_board_errors_and_silence_are_reported(self):
        for conn in (FakeBoard(error=True), FakeBoard(silent=True)):
            await conn.mcp_client.set_ready(True)
            with self.assertRaises(RuntimeError):
                await wake_assets.call_board_tool(conn, "self.reboot", {}, timeout=0.1)
            self.assertEqual(conn.mcp_client.call_results, {})

    def test_only_saved_files_are_served(self):
        name = wake_assets.save("94:a9:90:2d:a3:70", b"image")
        self.assertIsNotNone(wake_assets.path_of(name))
        for bad in ["../gateway_boards.json", "x.bin", name.replace(".bin", ".json"), ""]:
            self.assertIsNone(wake_assets.path_of(bad), bad)


if __name__ == "__main__":
    unittest.main()
