"""G18a：网关页面"设备"一页读板子信息。回应的 JSON 照固件 WifiBoard::GetDeviceStatusJson、
Board::GetSystemInfoJson 和 McpServer::GetToolsList 的格式写。"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.gateway import board_info, board_tools, status
from core.providers.tools.device_mcp.mcp_handler import MCPClient

DEVICE_STATUS = {"audio_speaker": {"volume": 70}, "screen": {"brightness": 80, "theme": "dark"},
                 "network": {"type": "wifi", "ssid": "TP-LINK_BCD", "signal": "medium"}}
SYSTEM_INFO = {"version": 2, "language": "zh-CN", "flash_size": 16777216, "minimum_free_heap_size": "123456",
               "mac_address": "94:a9:90:2d:a3:70", "chip_model_name": "esp32s3",
               "application": {"name": "xiaozhi", "version": "2.5.2.9", "compile_time": "Oct 19 2026T16:30:00Z",
                               "idf_version": "v6.0.1"},
               "ota": {"label": "ota_0"}, "display": {"monochrome": False, "width": 320, "height": 240},
               "board": {"type": "lichuang-dev", "ssid": "TP-LINK_BCD", "rssi": -63, "channel": 6,
                         "ip": "192.168.124.241", "mac": "94:a9:90:2d:a3:70"}}
TOOLS = [{"name": "self.get_device_status", "description": "Provides the real-time information"},
         {"name": "self.audio_speaker.set_volume", "description": "Set the volume"},
         {"name": "self.get_system_info", "description": "Get the system information"},
         {"name": "self.reboot", "description": "Reboot the system"}]


class FakeBoard:
    """Answers tools/call and a two-page tools/list like the firmware."""

    def __init__(self, broken=()):
        self.device_id, self.features, self.config = "94:a9:90:2d:a3:70", {"mcp": True}, {}
        self.mcp_client, self.requests, self.broken = MCPClient(), [], set(broken)
        self.websocket = SimpleNamespace(send=self._send)

    async def _send(self, raw):
        request = json.loads(raw)["payload"]
        self.requests.append(request)
        params = request["params"]
        if request["method"] == "tools/list":
            result = ({"tools": TOOLS[:2], "nextCursor": TOOLS[2]["name"]} if "cursor" not in params
                      else {"tools": TOOLS[2:]})
        elif params["name"] in self.broken:
            return  # no answer
        else:
            body = {"self.get_device_status": DEVICE_STATUS, "self.get_system_info": SYSTEM_INFO}[params["name"]]
            result = {"content": [{"type": "text", "text": json.dumps(body)}], "isError": False}
        await self.mcp_client.resolve_call_result(request["id"], result)

    async def ready(self):
        # The server's own tools list (without [user] tools) is what the AI sees.
        for tool in (TOOLS[0], TOOLS[1]):
            await self.mcp_client.add_tool({**tool, "inputSchema": {}})
        await self.mcp_client.set_ready(True)


_wait_for = asyncio.wait_for


async def _short_wait(future, timeout):
    return await _wait_for(future, min(timeout, 0.1))


class BoardInfoTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for store in (status._boards, status._conns):
            store.clear()
        temp = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(status, "BOARDS_PATH", temp / "gateway_boards.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_all_tools_are_listed_with_user_only_marked(self):
        conn = FakeBoard()
        await conn.ready()
        tools = await board_tools.list_board_tools(conn)
        self.assertEqual([(t["name"], t["user_only"]) for t in tools], [
            ("self.get_device_status", False), ("self.audio_speaker.set_volume", False),
            ("self.get_system_info", True), ("self.reboot", True)])
        lists = [r["params"] for r in conn.requests]
        self.assertEqual(lists, [{"withUserTools": True}, {"withUserTools": True, "cursor": "self.get_system_info"}])

    async def test_read_summarizes_what_the_page_shows(self):
        conn = FakeBoard()
        await conn.ready()
        info = await board_info.read(conn)
        self.assertEqual(info["wifi"], {"ssid": "TP-LINK_BCD", "rssi": -63, "signal": "medium", "channel": 6})
        self.assertEqual(info["ip"], "192.168.124.241")
        self.assertEqual(info["firmware"], {"version": "2.5.2.9", "built": "Oct 19 2026T16:30:00Z",
                                            "partition": "ota_0", "idf": "v6.0.1"})
        self.assertEqual((info["chip"], info["flash"], info["heap_min"], info["display"]),
                         ("esp32s3", 16777216, 123456, [320, 240]))
        self.assertEqual((info["volume"], info["brightness"], info["theme"]), (70, 80, "dark"))
        self.assertIsNone(info["battery"])
        self.assertEqual(len(info["tools"]), 4)
        # Only reads: no tool that changes anything was called.
        self.assertEqual({r["params"].get("name") for r in conn.requests if r["method"] == "tools/call"},
                         {"self.get_device_status", "self.get_system_info"})

    async def test_a_part_the_board_does_not_answer_is_left_empty(self):
        conn = FakeBoard(broken={"self.get_system_info"})
        await conn.ready()
        with mock.patch.object(asyncio, "wait_for", side_effect=_short_wait):
            info = await board_info.read(conn)
        self.assertEqual(info["volume"], 70)
        self.assertEqual(info["wifi"]["ssid"], "TP-LINK_BCD")
        self.assertIsNone(info["firmware"]["version"])

    async def test_watch_stores_info_and_the_page_shows_it_after_disconnect(self):
        conn = FakeBoard()
        conn.client_ip = "192.168.124.241"
        status._boards[conn.device_id] = {"type": "lichuang-dev", "version": "2.5.2.9"}
        with mock.patch.object(board_info, "start"):
            status.connected(conn)
        await conn.ready()
        with mock.patch.object(board_info, "REFRESH", 0.05):
            task = asyncio.create_task(board_info.watch(conn))
            await asyncio.sleep(0.2)
            status.disconnected(conn)
            await asyncio.wait_for(task, 1)
        board = status.snapshot({})["boards"][0]
        self.assertFalse(board["online"])
        self.assertEqual(board["info"]["volume"], 70)
        saved = json.loads(status.BOARDS_PATH.read_text())
        self.assertEqual(saved[conn.device_id]["info"]["wifi"]["rssi"], -63)

    async def test_boards_without_mcp_are_not_asked(self):
        conn = FakeBoard()
        conn.features = {}
        with mock.patch.object(board_info, "READY_WAIT", 0.2):
            await board_info.watch(conn)
        self.assertEqual(conn.requests, [])


if __name__ == "__main__":
    unittest.main()
