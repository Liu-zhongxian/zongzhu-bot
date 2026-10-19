import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.auth import AuthenticationError

# Importing the server pulls in modules that read data/.config.yaml at import time.
with patch("config.settings.check_config_file"), patch("config.logger.setup_logging", Mock()):
    from core.websocket_server import WebSocketServer


def server(allowlist_only, allowed=("02:00:00:00:00:aa",)):
    instance = object.__new__(WebSocketServer)
    instance.auth_enable = True
    instance.allowed_devices = set(allowed)
    instance.allowlist_only = allowlist_only
    instance.device_client_ids = {}
    instance.auth = Mock(verify_token=Mock(return_value=True))
    return instance


def socket(device_id, token="Bearer issued-by-ota"):
    headers = {"device-id": device_id, "client-id": "c", "authorization": token}
    return SimpleNamespace(request=SimpleNamespace(headers=headers))


class DeviceAllowlistTest(unittest.IsolatedAsyncioTestCase):
    async def test_listed_device_connects(self):
        await server(True)._handle_auth(socket("02:00:00:00:00:aa", token=""))

    async def test_unlisted_device_refused_even_with_valid_token(self):
        with self.assertRaises(AuthenticationError):
            await server(True)._handle_auth(socket("aa:bb:cc:dd:ee:ff"))

    async def test_paired_client_id_required(self):
        paired = server(True)
        paired.device_client_ids = {"02:00:00:00:00:aa": "board-uuid"}
        with self.assertRaises(AuthenticationError):
            await paired._handle_auth(socket("02:00:00:00:00:aa"))
        ok = socket("02:00:00:00:00:aa")
        ok.request.headers["client-id"] = "board-uuid"
        await paired._handle_auth(ok)

    async def test_default_still_accepts_token(self):
        await server(False)._handle_auth(socket("aa:bb:cc:dd:ee:ff"))


if __name__ == "__main__":
    unittest.main()
