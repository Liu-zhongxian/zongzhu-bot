"""G25 ① 第 2 步：网关页面打开音箱接入（token、后端地址、唤醒词模型后台下载）、在后台装 Client。"""
import asyncio
import io
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from core.gateway import settings as page_settings
from core.gateway.control import ControlError
from core.gateway.xiaoai import control as speaker_control, install, server, setup


class FakeServer:
    def __init__(self, ready=False):
        self.ready = asyncio.Event()
        if ready:
            self.ready.set()
        self.turned_on = 0
        self.reloaded = 0

    def turn_on(self):
        self.turned_on += 1

    async def reload(self):
        self.reloaded += 1


class FakeResponse:
    def __init__(self, body):
        self.body = body
        self.headers = {"content-length": str(len(body))}

    def raise_for_status(self):
        pass

    def iter_bytes(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def models_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name in setup.KWS_FILES:
            z.writestr(f"models/{name}", f"{name} data")
        z.writestr("models/other.onnx", "not kept")
    return buffer.getvalue()


class SetupTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.models = self.dir / "models" / "kws"
        self.config = {"gateway": {"xiaoai": {"port": 4399, "kws_model_dir": str(self.models)}}}
        self.server = FakeServer()
        for p in (mock.patch.object(page_settings, "PATH", self.dir / "gateway_settings.json"),
                  mock.patch.object(server, "DEFAULT_TOKEN_FILE", self.dir / "data" / "xiaoai_token.txt"),
                  mock.patch.object(install, "KNOWN_HOSTS", self.dir / "known_hosts.json"),
                  mock.patch.object(speaker_control, "server", self.server),
                  mock.patch.object(setup, "in_docker", lambda: False),
                  mock.patch.dict(setup.model_job, state="idle", done=0, total=0, error=""),
                  mock.patch.dict(setup.install_job, state="idle", host="", steps=[], error="", result=None)):
            p.start()
            self.addCleanup(p.stop)

    def model_files(self):
        self.models.mkdir(parents=True)
        for name in setup.KWS_FILES:
            (self.models / name).write_text("x")

    async def settle(self):
        await asyncio.gather(*list(setup._tasks))

    # token
    def test_a_new_token_is_made_once_and_kept_private(self):
        token = setup.ensure_token(self.config)
        path = self.dir / "data" / "xiaoai_token.txt"
        self.assertEqual(path.read_text().strip(), token)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertGreaterEqual(len(token), 40)
        self.assertEqual(setup.ensure_token(self.config), token)

    def test_the_configured_token_is_reused(self):
        path = self.dir / "mine.txt"
        path.write_text("old-token\n")
        self.config["gateway"]["xiaoai"]["token_file"] = str(path)
        self.assertEqual(setup.ensure_token(self.config), "old-token")
        self.assertFalse((self.dir / "data" / "xiaoai_token.txt").exists())

    def test_a_configured_but_missing_token_file_is_not_replaced(self):
        self.config["gateway"]["xiaoai"]["token_file"] = str(self.dir / "gone.txt")
        with self.assertRaisesRegex(ControlError, "token_file 读不到"):
            setup.ensure_token(self.config)

    # 后端地址
    def test_server_url_uses_the_interface_that_reaches_the_speaker(self):
        self.assertEqual(setup.server_url(self.config, "127.0.0.1"), "ws://127.0.0.1:4399")

    def test_server_url_in_docker_comes_from_the_config(self):
        with mock.patch.object(setup, "in_docker", lambda: True):
            self.assertEqual(setup.server_url(self.config, "127.0.0.1"), "")  # 容器自己的 IP 音箱连不到
            self.config["server"] = {"websocket": "ws://192.168.1.100:8000/xiaozhi/v1/"}  # 示例里的，不算
            self.assertEqual(setup.server_url(self.config), "")
            self.config["server"] = {"websocket": "ws://10.0.0.5:8000/xiaozhi/v1/"}
            self.assertEqual(setup.server_url(self.config), "ws://10.0.0.5:4399")

    # 打开
    async def test_enable_with_the_model_starts_listening_at_once(self):
        self.model_files()
        result = await setup.act(self.config, "speaker_enable", None)
        self.assertIn("在等音箱连接", result["message"])
        self.assertTrue(page_settings.get("speaker_enabled"))
        self.assertEqual(self.server.turned_on, 1)
        self.assertTrue(setup.view(self.config)["token"])

    async def test_enable_without_the_model_downloads_it_first(self):
        with mock.patch.object(setup, "KWS_MINIMUM", 0), \
                mock.patch("httpx.stream", return_value=FakeResponse(models_zip())) as stream:
            result = await setup.act(self.config, "speaker_enable", None)
            self.assertIn("正在下载唤醒词模型", result["message"])
            self.assertEqual(self.server.turned_on, 0)
            await self.settle()
        self.assertEqual(stream.call_args.args[1], setup.KWS_ZIP)
        self.assertEqual(sorted(os.listdir(self.models)), sorted(setup.KWS_FILES))
        self.assertEqual((self.models / "tokens.txt").read_text(), "tokens.txt data")
        self.assertFalse(list(self.models.parent.glob("*.part")))
        self.assertEqual(setup.view(self.config)["model"], "done")
        self.assertEqual(self.server.turned_on, 1)

    async def test_a_running_server_reloads_after_the_download(self):
        self.server.ready.set()
        with mock.patch.object(setup, "KWS_MINIMUM", 0), \
                mock.patch("httpx.stream", return_value=FakeResponse(models_zip())):
            await setup.act(self.config, "speaker_model_download", None)
            await self.settle()
        self.assertEqual(self.server.reloaded, 1)

    async def test_a_short_download_is_an_error_and_can_be_retried(self):
        with mock.patch("httpx.stream", return_value=FakeResponse(b"<html>error</html>")):
            await setup.act(self.config, "speaker_enable", None)
            await self.settle()
        self.assertEqual(setup.model_job["state"], "error")
        self.assertIn("只下到", setup.model_job["error"])
        self.assertFalse(self.models.exists() and any(self.models.iterdir()))
        self.assertEqual(self.server.turned_on, 0)
        with mock.patch.object(setup, "KWS_MINIMUM", 0), \
                mock.patch("httpx.stream", return_value=FakeResponse(models_zip())):
            self.assertIn("开始下载", (await setup.act(self.config, "speaker_model_download", None))["message"])
            await self.settle()
        self.assertEqual(setup.view(self.config)["model"], "done")
        self.assertEqual(self.server.turned_on, 1)

    # 装 Client
    async def test_install_runs_in_the_background_and_keeps_no_password(self):
        self.model_files()
        conn = mock.AsyncMock()

        async def fake_install(conn_, url, token, client, init_script, step):
            step("看音箱的型号和版本")
            self.seen = (url, token)
            return {"model": "OH2P", "rom": "1.62.2", "boot": "boot0", "restarted": True, "disabled": False}

        with mock.patch.object(install, "connect", mock.AsyncMock(return_value=conn)) as connect, \
                mock.patch.object(install, "install", fake_install), \
                mock.patch.object(install, "client_bytes", return_value=b"client"):
            result = await setup.act(self.config, "speaker_install",
                                     {"host": "10.0.0.9", "password": "pw-secret", "server": "ws://10.0.0.2:4399"})
            self.assertIn("开始给 10.0.0.9 装", result["message"])
            self.assertEqual(setup.install_job["state"], "running")
            await self.settle()
        connect.assert_awaited_once_with("10.0.0.9", "pw-secret")
        self.assertEqual(self.seen, ("ws://10.0.0.2:4399", server.read_token(server.settings(self.config))))
        shown = setup.view(self.config)
        self.assertEqual(shown["install"]["state"], "done")
        self.assertEqual(shown["install"]["steps"], ["连接音箱", "看音箱的型号和版本"])
        self.assertEqual(shown["install"]["result"]["model"], "OH2P")
        self.assertTrue(shown["enabled"])
        self.assertNotIn("pw-secret", repr(shown) + repr(setup.install_job))

    async def test_install_errors_are_shown(self):
        with mock.patch.object(install, "connect", mock.AsyncMock(side_effect=install.InstallError("root 密码不对"))), \
                mock.patch.object(install, "client_bytes", return_value=b"client"), \
                mock.patch.object(setup, "start_model_download"):
            await setup.act(self.config, "speaker_install", {"host": "10.0.0.9", "password": "x"})
            await self.settle()
        self.assertEqual(setup.install_job["state"], "error")
        self.assertEqual(setup.install_job["error"], "root 密码不对")

    async def test_install_checks_the_form(self):
        with self.assertRaisesRegex(ControlError, "IP 不对"):
            await setup.act(self.config, "speaker_install", {"host": "1.2.3.4; reboot", "password": "x"})
        with self.assertRaisesRegex(ControlError, "root 密码"):
            await setup.act(self.config, "speaker_install", {"host": "10.0.0.9"})
        with self.assertRaisesRegex(ControlError, "后端地址不对"):
            await setup.act(self.config, "speaker_install", {"host": "10.0.0.9", "password": "x", "server": "http://a"})
        setup.install_job["state"] = "running"
        with self.assertRaisesRegex(ControlError, "正在装"):
            await setup.act(self.config, "speaker_install", {"host": "10.0.0.9", "password": "x"})
        self.assertIsNone(page_settings.get("speaker_enabled"))

    async def test_forget_key(self):
        install._save_known({"10.0.0.9": "ssh-rsa AAAA"})
        self.assertIn("忘记了", (await setup.act(self.config, "speaker_forget_key", {"host": "10.0.0.9"}))["message"])
        self.assertIn("没记过", (await setup.act(self.config, "speaker_forget_key", {"host": "10.0.0.9"}))["message"])
        self.assertEqual(setup.view(self.config)["known_hosts"], [])
