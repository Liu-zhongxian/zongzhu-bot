"""GET /gateway (the page) and GET /gateway/api/status (read-only JSON).

G8b adds GET /gateway/assets/<file> (the board downloads its new assets image) and
POST /gateway/api/wake_word (change a board's wake word). The POST only answers this Mac
(tools/wake_word.py) until the page gets a password (G18b).
"""
from pathlib import Path

from aiohttp import web

from core.gateway import status, wake_assets

PAGE = Path(__file__).with_name("page.html")
NO_STORE = {"Cache-Control": "no-store"}
LOCAL = {"127.0.0.1", "::1"}
MAX_ASSETS = 8 * 1024 * 1024  # the assets partition


def _board_conn(device):
    """The live connection of the board whose id is `device` or ends with it; error text otherwise."""
    device = (device or "").strip().lower()
    conns = [c for c in list(status._conns.values())
             if c.device_id and device and c.device_id.lower().endswith(device)]
    if len({c.device_id for c in conns}) > 1:
        return None, "有好几块板子对得上，请写完整的板子编号"
    if not conns:
        return None, "板子没连着：先喊唤醒词把它叫醒，再马上运行"
    return conns[-1], None


class GatewayPageHandler:
    def __init__(self, config: dict):
        self.config = config

    async def handle_page(self, request):
        return web.Response(text=PAGE.read_text(encoding="utf-8"), content_type="text/html", headers=NO_STORE)

    async def handle_status(self, request):
        return web.json_response(status.snapshot(self.config), headers=NO_STORE)

    async def handle_assets(self, request):
        path = wake_assets.path_of(request.match_info.get("filename", ""))
        if path is None:
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Content-Type": "application/octet-stream"})

    async def handle_wake_word(self, request):
        """Body: the board's current assets image; query: device, text, command, reboot=0|1."""
        if request.remote not in LOCAL:
            return web.json_response({"error": "只能在运行后端的这台电脑上改唤醒词"}, status=403)
        source = bytearray()
        async for chunk in request.content.iter_chunked(64 * 1024):
            source += chunk
            if len(source) > MAX_ASSETS:
                return web.json_response({"error": "资源包超过 8 MB"}, status=413)
        conn, reason = _board_conn(request.query.get("device"))
        if conn is None:
            return web.json_response({"error": reason}, status=409)
        try:
            result = await wake_assets.change_wake_word(
                conn, bytes(source), request.query.get("text", ""), request.query.get("command", ""),
                reboot=request.query.get("reboot", "1") != "0")
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except RuntimeError as e:
            return web.json_response({"error": str(e)}, status=502)
        info = status._boards.get(conn.device_id, {})
        return web.json_response(result | {"board": status.board_name(info.get("type")), "version": info.get("version", "")})
