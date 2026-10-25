"""GET /gateway (the page) and GET /gateway/api/status (read-only JSON); nothing can be changed."""
from pathlib import Path

from aiohttp import web

from core.gateway import status

PAGE = Path(__file__).with_name("page.html")
NO_STORE = {"Cache-Control": "no-store"}


class GatewayPageHandler:
    def __init__(self, config: dict):
        self.config = config

    async def handle_page(self, request):
        return web.Response(text=PAGE.read_text(encoding="utf-8"), content_type="text/html", headers=NO_STORE)

    async def handle_status(self, request):
        return web.json_response(status.snapshot(self.config), headers=NO_STORE)
