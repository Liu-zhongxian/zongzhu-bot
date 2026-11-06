"""GET /gateway (the page) and GET /gateway/api/status (JSON).

G8b: GET /gateway/assets/<file> (the board downloads its new assets image) and
POST /gateway/api/wake_word (change a board's wake word; this Mac, or the page's token).
G18b: POST /gateway/api/login (password -> token) and POST /gateway/api/control (board
settings, reboot, Wi-Fi set-up, music); changes need the token only when gateway.password is set (core/gateway/control.py).
"""
import asyncio
from pathlib import Path

from aiohttp import web

from core.gateway import control, firmware, flow, modules, status, tasks, wake_assets
from core.gateway.xiaoai import control as speaker_control, flash_job as speaker_flash, setup as speaker_setup

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
        music = await asyncio.to_thread(control.music_status)
        checked = await asyncio.to_thread(modules.cached, self.config)
        handed = await asyncio.to_thread(tasks.cached, self.config, status.names())
        return web.json_response(status.snapshot(self.config) | {"music": music,
                                 "password": control.password_required(self.config),
                                 "settings": control.settings_view(self.config), "modules": checked,
                                 "tasks": handed, "flow": flow.view(self.config),
                                 "firmware": await asyncio.to_thread(firmware.listing),
                                 "speaker_setup": await asyncio.to_thread(speaker_setup.view, self.config),
                                 "speaker_flash": await asyncio.to_thread(speaker_flash.view)},
                                 headers=NO_STORE)

    def _token_ok(self, request):
        return control.allowed(self.config, request.headers.get("X-Gateway-Token", ""))

    async def handle_login(self, request):
        if not control.password_required(self.config):
            return web.json_response({"token": ""})  # no password set: everything is open
        try:
            password = str((await request.json()).get("password", ""))
        except ValueError:
            password = ""
        token = control.login(self.config, password)
        if token is None:
            await asyncio.sleep(1)  # slow down guessing
            return web.json_response({"error": "口令不对"}, status=403)
        return web.json_response({"token": token})

    async def handle_control(self, request):
        """Body: {"action": ..., "device": <board id>, "value": ...}."""
        if not self._token_ok(request):
            return web.json_response({"error": "要先输入口令"}, status=401)
        try:
            body = await request.json()
            action = body["action"]
        except (ValueError, KeyError, TypeError):
            return web.json_response({"error": "请求格式不对"}, status=400)
        try:
            if action in control.MUSIC_ACTIONS:
                return web.json_response(await control.music_action(action, body.get("value")))
            if action == "firmware_delete":
                await asyncio.to_thread(firmware.delete, str(body.get("value") or ""))
                return web.json_response({"message": "删掉了。"})
            if action == "firmware_now":
                name = str(body.get("value") or "")
                if firmware.path_of(name) is None:
                    return web.json_response({"error": "没有这个固件文件"}, status=400)
                conn, reason = _board_conn(body.get("device"))
                if conn is None:
                    return web.json_response({"error": reason.replace("再马上运行", "再点")}, status=409)
                await firmware.upgrade_now(conn, firmware.download_url(self.config, name))
                return web.json_response({"message": "板子开始下载固件（屏幕上有进度），装好会自己重启；"
                                                     "重启后几十秒内这里的版本号会变。下载时不要断电。"})
            if action == "board_wake_word":
                conn, reason = _board_conn(body.get("device"))
                if conn is None:
                    return web.json_response({"error": reason.replace("再马上运行", "再点")}, status=409)
                return web.json_response(await control.board_wake_word(self.config, conn, body.get("value")))
            if action in control.SETTING_ACTIONS:
                return web.json_response(await control.settings_action(self.config, action, body.get("value")))
            if action in speaker_flash.ACTIONS:
                return web.json_response(await speaker_flash.act(self.config, action, body.get("value")))
            if action in speaker_setup.ACTIONS:
                return web.json_response(await speaker_setup.act(self.config, action, body.get("value")))
            if action in speaker_control.ACTIONS:
                return web.json_response(await speaker_control.act(self.config, body.get("device"), action,
                                                                    body.get("value")))
            if action not in control.BOARD_ACTIONS:
                return web.json_response({"error": f"不认识的操作 {action}"}, status=400)
            conn, reason = _board_conn(body.get("device"))
            if conn is None:
                return web.json_response({"error": reason.replace("再马上运行", "再点")}, status=409)
            return web.json_response(await control.board_action(conn, action, body.get("value")))
        except (control.ControlError, firmware.FirmwareError) as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_firmware(self, request):
        """Body: a xiaozhi.bin; query: device (board id), force=1 for the same or an older version.
        Checked against the board (core/gateway/firmware.py), then kept in data/bin/."""
        if not self._token_ok(request):
            return web.json_response({"error": "要先输入口令"}, status=401)
        device = (request.query.get("device") or "").strip().lower()
        found = [k for k in list(status._boards) if device and k.lower().endswith(device)]
        if len(found) != 1:
            return web.json_response({"error": "找不到这块板子" if not found else "有好几块板子对得上"}, status=400)
        image = bytearray()
        async for chunk in request.content.iter_chunked(64 * 1024):
            image += chunk
            if len(image) > firmware.MAX_SIZE:
                return web.json_response({"error": "文件超过 8 MB，不像是固件"}, status=413)
        try:
            info = firmware.check(bytes(image), status._boards[found[0]])
            if not info["newer"] and request.query.get("force") != "1":
                return web.json_response({"confirm": f"这份固件是 {info['version']}，板子上是 {info['board_version']}："
                                                     "不比板子上的新。还要传吗？", **info}, status=409)
            info["file"] = await asyncio.to_thread(firmware.save, bytes(image), info["model"], info["version"])
        except firmware.FirmwareError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response(info)

    async def handle_assets(self, request):
        path = wake_assets.path_of(request.match_info.get("filename", ""))
        if path is None:
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Content-Type": "application/octet-stream"})

    async def handle_wake_word(self, request):
        """Body: the board's current assets image; query: device, text, command, reboot=0|1."""
        if request.remote not in LOCAL and not (control.password_required(self.config) and self._token_ok(request)):
            return web.json_response({"error": "要在运行后端的这台电脑上改，或者先在网关页面输入口令"}, status=403)
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
