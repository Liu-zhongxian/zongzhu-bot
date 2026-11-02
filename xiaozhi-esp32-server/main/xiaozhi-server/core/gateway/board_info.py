"""G18a：网关页面"设备"一页的板子信息，只读。

板子醒着、MCP 准备好以后读一次，之后连着时每 REFRESH 秒再读；结果存进 data/gateway_boards.json，
板子待机后页面显示上次读到的值和时间。来源（xiaozhi-esp32 固件）：
  - self.get_device_status（WifiBoard::GetDeviceStatusJson）：音量、亮度、主题、电量、WiFi 名和强弱、芯片温度；
  - self.get_system_info（Board::GetSystemInfoJson，[user] 工具）：flash 大小、开机以来最低剩余内存、芯片、
    固件版本和编译时间、正在跑的 OTA 分区、屏幕尺寸，以及 board 里的 WiFi 名、信号 dBm、信道、IP。
    固件不报 PSRAM 大小，也没有当前剩余内存，只有最低值；
  - tools/list（withUserTools）：板子上的全部 MCP 工具。
"""
import asyncio
import time

from core.gateway import board_tools, status

REFRESH = 60  # seconds between reads while the board stays connected
READY_WAIT = 20  # the board's hello and MCP set-up after connecting


def summarize(device: dict, system: dict, tools) -> dict:
    """Only the fields the page shows; missing ones are None."""
    device, system = device or {}, system or {}
    board, app = system.get("board") or {}, system.get("application") or {}
    network, screen = device.get("network") or {}, device.get("screen") or {}
    display = system.get("display") or {}
    try:
        heap_min = int(system.get("minimum_free_heap_size"))
    except (TypeError, ValueError):
        heap_min = None
    return {
        "wifi": {"ssid": board.get("ssid") or network.get("ssid"), "rssi": board.get("rssi"),
                 "signal": network.get("signal"), "channel": board.get("channel")},
        "ip": board.get("ip"),
        "firmware": {"version": app.get("version"), "built": app.get("compile_time"),
                     "partition": (system.get("ota") or {}).get("label"), "idf": app.get("idf_version")},
        "chip": system.get("chip_model_name"),
        "flash": system.get("flash_size"),
        "heap_min": heap_min,
        "display": [display["width"], display["height"]] if "width" in display and "height" in display else None,
        "volume": (device.get("audio_speaker") or {}).get("volume"),
        "brightness": screen.get("brightness"),
        "theme": screen.get("theme"),
        "battery": device.get("battery"),
        "temperature": (device.get("chip") or {}).get("temperature"),
        "tools": tools,
    }


async def read(conn) -> dict:
    """Ask the board; each part may fail on its own (older firmware, a busy board)."""
    async def part(coro):
        try:
            return await coro
        except RuntimeError:
            return None

    device = board_tools.tool_json(await part(board_tools.call_board_tool(conn, "self.get_device_status", {})))
    system = board_tools.tool_json(await part(board_tools.call_board_tool(conn, "self.get_system_info", {})))
    tools = await part(board_tools.list_board_tools(conn))
    if device is None and system is None and tools is None:
        raise RuntimeError("板子什么都没回")
    return summarize(device, system, tools) | {"read_at": time.time()}


async def watch(conn):
    if await board_tools.mcp_client_ready(conn, READY_WAIT) is None:
        return
    while status.is_live(conn):
        try:
            status.note_info(conn.device_id, await read(conn))
        except RuntimeError:
            pass  # keep the last values; try again next round
        await asyncio.sleep(REFRESH)


def start(conn):
    """Called when a board connects; does nothing outside an event loop (unit tests)."""
    try:
        asyncio.get_running_loop().create_task(watch(conn))
    except RuntimeError:
        pass
