"""直接调板子上的 MCP 工具（G8b 改唤醒词、G18 设备管理）。

core/providers/tools/device_mcp 的 call_mcp_tool 只认工具列表里的工具；后端要工具列表时没带
withUserTools，[user] 工具（self.get_system_info、self.reboot、self.assets.set_download_url……）
不在里面，而固件调用工具时不查这个标记（xiaozhi-esp32 main/mcp_server.cc 的 DoToolCall）。
所以这里自己发 tools/call、tools/list，回应照样由 mcp_handler 按编号交回来。
板子只有醒着、连着的时候能调；待机时连接是断的。
"""
import asyncio
import json


async def mcp_client_ready(conn, wait: float):
    """板子刚被唤醒连上时，hello、MCP 初始化和工具列表要几秒（实测 5 秒，2026-10-30），等它好；
    等不到（或板子不支持 MCP）时返回 None。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait
    while True:
        client = getattr(conn, "mcp_client", None)
        if (getattr(conn, "features", None) or {}).get("mcp") and client is not None and await client.is_ready():
            return client
        if loop.time() >= deadline:
            return None
        await asyncio.sleep(0.2)


async def _request(conn, method: str, params: dict, timeout: float, ready_wait: float):
    from core.providers.tools.device_mcp.mcp_handler import send_mcp_message

    client = await mcp_client_ready(conn, ready_wait)
    if client is None:
        raise RuntimeError(f"板子的 MCP 没准备好（连上后等了 {ready_wait:g} 秒），请重新唤醒板子再试")
    call_id = await client.get_next_id()
    future = asyncio.get_running_loop().create_future()
    await client.register_call_result_future(call_id, future)
    await send_mcp_message(conn, {"jsonrpc": "2.0", "id": call_id, "method": method, "params": params})
    try:
        return await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError:
        raise RuntimeError(f"板子没有回应 {params.get('name', method)}") from None
    except Exception as e:  # mcp_handler rejects with a plain Exception when the board answers an error
        raise RuntimeError(f"板子执行 {params.get('name', method)} 出错：{e}") from None
    finally:
        await client.cleanup_call_result(call_id)


async def call_board_tool(conn, name: str, arguments: dict, timeout: float = 10, ready_wait: float = 10):
    result = await _request(conn, "tools/call", {"name": name, "arguments": arguments}, timeout, ready_wait)
    if isinstance(result, dict) and result.get("isError"):
        raise RuntimeError(f"板子执行 {name} 出错：{result}")
    return result


def tool_json(result):
    """工具返回的 JSON（固件把它放在 content[0].text 里）；不是 JSON 时 None。"""
    try:
        return json.loads(result["content"][0]["text"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


async def list_board_tools(conn, timeout: float = 10, ready_wait: float = 10):
    """板子上所有工具，包括 [user] 工具：[{name, description, user_only}]。"""
    tools, cursor = [], ""
    for _ in range(20):  # the firmware pages at ~8 KB
        params = {"withUserTools": True} | ({"cursor": cursor} if cursor else {})
        result = await _request(conn, "tools/list", params, timeout, ready_wait)
        tools += [t for t in (result or {}).get("tools", []) if isinstance(t, dict) and t.get("name")]
        cursor = (result or {}).get("nextCursor", "")
        if not cursor:
            break
    # Tools the AI sees are the ones the server listed without withUserTools.
    client = getattr(conn, "mcp_client", None)
    listed = set(getattr(client, "name_mapping", {}).values())
    return [{"name": t["name"], "description": str(t.get("description", "")), "user_only": t["name"] not in listed}
            for t in tools]
