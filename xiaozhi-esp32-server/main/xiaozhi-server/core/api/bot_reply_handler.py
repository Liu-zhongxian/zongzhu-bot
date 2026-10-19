"""Receives Bot replies over HTTPS so the Bot no longer has to write files on this computer."""
import json
from pathlib import Path

from aiohttp import web
from config.logger import setup_logging
from core.handle.grokBotReply import accept_reply

TAG = __name__

# Replies are at most 8000 characters; leave room for JSON escaping.
MAX_BODY_BYTES = 64 * 1024

_MESSAGES = {
    200: "ok",
    400: "request_id, token and non-empty text (at most 8000 characters) are required",
    403: "token does not match this request",
    404: "unknown or expired request",
    409: "this request already has a reply",
    413: "body too large",
    500: "reply could not be stored",
    503: "reply endpoint is not configured",
}


class BotReplyHandler:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()

    def _reply_dir(self):
        config_file = self.config.get("grok_bot", {}).get("config_file", "")
        try:
            data = json.loads(Path(config_file).read_text(encoding="utf-8"))
            return data.get("reply_dir") if data.get("reply_url") else None
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    @staticmethod
    def _response(status):
        return web.json_response({"ok": status == 200, "message": _MESSAGES[status]}, status=status)

    async def handle_post(self, request):
        directory = self._reply_dir()
        if not directory:
            return self._response(503)
        if request.content_length is None or request.content_length > MAX_BODY_BYTES:
            return self._response(413)
        try:
            data = json.loads(await request.read())
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self._response(400)
        status = accept_reply(directory, data.get("request_id"), data.get("token"), data.get("text"))
        if status == 200:
            self.logger.bind(tag=TAG).info(f"Bot reply received over HTTP: {data['request_id']}")
        elif status != 400:
            self.logger.bind(tag=TAG).warning(f"Bot reply rejected ({status})")
        return self._response(status)
