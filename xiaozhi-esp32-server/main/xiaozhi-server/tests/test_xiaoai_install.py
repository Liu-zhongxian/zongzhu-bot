"""G25 ①：网关页面装音箱 Client。假音箱是本机的一个 SSH 服务（asyncssh），收到的命令在临时目录里用 sh 真跑：
命令里的 /data/、/usr/share/mico/version 换成临时目录里的，fw_env、ps、killall 用假的。"""
import asyncio
import hashlib
import os
import socket
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import asyncssh

from core.gateway.xiaoai import install

PASSWORD = "speaker-root-password"
OH2P = "config version 'version'\n\toption ROM '1.62.2'\n\toption CHANNEL 'release'\n\toption HARDWARE 'OH2P'\n"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeSpeaker:
    """一台假音箱：root 密码登录，命令在 root 目录里跑"""

    def __init__(self, root: Path, version=OH2P, init_running=False):
        self.root = root
        self.key = asyncssh.generate_private_key("ssh-rsa")
        self.port = free_port()
        self.commands = []
        (root / "data").mkdir()
        (root / "version").write_text(version)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, body in {"fw_env": "echo boot0",
                           # 命令里的 /data/ 也会被换成临时目录里的，ps 里的也一样写
                           "ps": f"echo '{f'  123 root  sh {root}/data/init.sh' if init_running else '  1 root init'}'",
                           "killall": f'echo "$@" >> {root}/killed'}.items():
            (bin_dir / name).write_text("#!/bin/sh\n" + body + "\n")
            (bin_dir / name).chmod(0o755)
        self.server = None

    async def start(self):
        speaker = self

        class Server(asyncssh.SSHServer):
            def begin_auth(self, username):
                return True

            def password_auth_supported(self):
                return True

            def validate_password(self, username, password):
                return username == "root" and password == PASSWORD

        async def handle(process):
            command = process.command
            speaker.commands.append(command)
            command = (command.replace("/usr/share/mico/version", f"{speaker.root}/version")
                       .replace("/data/", f"{speaker.root}/data/"))
            env = dict(os.environ, PATH=f"{speaker.root}/bin:" + os.environ["PATH"])
            local = subprocess.Popen(command, shell=True, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            await process.redirect(stdin=local.stdin, stdout=local.stdout, stderr=local.stderr)
            await process.stdout.drain()
            process.exit(await asyncio.to_thread(local.wait))

        self.server = await asyncssh.create_server(Server, "127.0.0.1", self.port, server_host_keys=[self.key],
                                                   process_factory=handle, encoding=None)

    async def close(self):
        self.server.close()
        await self.server.wait_closed()


class InstallTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        patch = mock.patch.object(install, "KNOWN_HOSTS", self.root / "known_hosts.json")
        patch.start()
        self.addCleanup(patch.stop)
        self.client = b"\x7fELF fake client"

    async def asyncTearDown(self):
        self.dir.cleanup()

    async def speaker(self, name="speaker", **kw):
        root = self.root / name
        root.mkdir()
        speaker = FakeSpeaker(root, **kw)
        await speaker.start()
        self.addAsyncCleanup(speaker.close)
        return speaker

    async def test_first_install_writes_the_files_and_starts_the_boot_script(self):
        speaker = await self.speaker()
        steps = []
        conn = await install.connect("127.0.0.1", PASSWORD, port=speaker.port)
        async with conn:
            result = await install.install(conn, "ws://192.168.1.10:4399", "tok-123", self.client,
                                           "#!/bin/sh\necho boot\n", steps.append)
        data = speaker.root / "data"
        self.assertEqual((data / "open-xiaoai" / "client").read_bytes(), self.client)
        self.assertTrue(os.access(data / "open-xiaoai" / "client", os.X_OK))
        self.assertEqual((data / "open-xiaoai" / "server.txt").read_text(), "ws://192.168.1.10:4399\n")
        self.assertEqual((data / "open-xiaoai" / "token.txt").read_text(), "tok-123\n")
        self.assertEqual(stat.S_IMODE((data / "open-xiaoai" / "token.txt").stat().st_mode), 0o600)
        self.assertEqual((data / "init.sh").read_text(), "#!/bin/sh\necho boot\n")
        self.assertEqual(result, {"model": "OH2P", "rom": "1.62.2", "boot": "boot0", "restarted": False,
                                  "disabled": False})
        self.assertEqual(steps, ["看音箱的型号和版本", "写入 Client 和开机脚本", "核对", "启动"])
        self.assertFalse((speaker.root / "killed").exists())
        self.assertIn("127.0.0.1", install._known())
        # 密码和 token 不出现在命令行里（只经 stdin 传）
        self.assertFalse(any(PASSWORD in c or "tok-123" in c for c in speaker.commands))

    async def test_reinstall_restarts_only_the_client(self):
        speaker = await self.speaker(init_running=True)
        async with await install.connect("127.0.0.1", PASSWORD, port=speaker.port) as conn:
            result = await install.install(conn, "ws://10.0.0.2:4399", "tok", self.client, "#!/bin/sh\n")
        self.assertTrue(result["restarted"])
        self.assertEqual((speaker.root / "killed").read_text(), "client\n")

    async def test_a_paused_speaker_is_reported(self):
        speaker = await self.speaker()
        (speaker.root / "data" / "open-xiaoai").mkdir()
        (speaker.root / "data" / "open-xiaoai" / "disabled").touch()
        async with await install.connect("127.0.0.1", PASSWORD, port=speaker.port) as conn:
            result = await install.install(conn, "ws://10.0.0.2:4399", "tok", self.client, "#!/bin/sh\n")
        self.assertTrue(result["disabled"])

    async def test_wrong_password(self):
        speaker = await self.speaker()
        with self.assertRaisesRegex(install.InstallError, "root 密码不对"):
            await install.connect("127.0.0.1", "wrong", port=speaker.port)

    async def test_a_changed_host_key_is_refused_until_forgotten(self):
        first = await self.speaker("first")
        async with await install.connect("127.0.0.1", PASSWORD, port=first.port):
            pass
        second = await self.speaker("second")  # 同一个地址，换了密钥（像重新刷过机）
        with self.assertRaisesRegex(install.InstallError, "主机密钥和上次不一样"):
            await install.connect("127.0.0.1", PASSWORD, port=second.port)
        self.assertTrue(install.forget_host("127.0.0.1"))
        async with await install.connect("127.0.0.1", PASSWORD, port=second.port):
            pass
        self.assertEqual(install._known()["127.0.0.1"],
                         second.key.export_public_key("openssh").decode().strip())

    async def test_other_models_are_not_touched(self):
        speaker = await self.speaker(version=OH2P.replace("OH2P", "LX06"))
        async with await install.connect("127.0.0.1", PASSWORD, port=speaker.port) as conn:
            with self.assertRaisesRegex(install.InstallError, "LX06"):
                await install.install(conn, "ws://10.0.0.2:4399", "tok", self.client, "#!/bin/sh\n")
        self.assertEqual(list((speaker.root / "data").iterdir()), [])

    async def test_bad_server_address_or_token(self):
        speaker = await self.speaker()
        async with await install.connect("127.0.0.1", PASSWORD, port=speaker.port) as conn:
            with self.assertRaisesRegex(install.InstallError, "后端地址不对"):
                await install.install(conn, "ws://x:4399; reboot", "tok", self.client, "")
            with self.assertRaisesRegex(install.InstallError, "token 不对"):
                await install.install(conn, "ws://10.0.0.2:4399", "a b", self.client, "")
        self.assertEqual(speaker.commands, [])


class ClientFileTest(unittest.TestCase):
    def test_the_client_in_the_repo_is_the_known_build(self):
        if not install.CLIENT_FILE.exists():
            self.skipTest("不在仓库里运行")
        data = install.client_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), install.CLIENT_SHA256)
        self.assertTrue(data.startswith(b"\x7fELF"))
        self.assertIn("/data/open-xiaoai", install.init_script())

    def test_a_changed_client_is_refused(self):
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"not the client")
            f.flush()
            with self.assertRaisesRegex(install.InstallError, "校验值不对"):
                install.client_bytes(f.name)

    def test_version_file(self):
        self.assertEqual(install.parse_version(OH2P), {"rom": "1.62.2", "channel": "release", "hardware": "OH2P"})
