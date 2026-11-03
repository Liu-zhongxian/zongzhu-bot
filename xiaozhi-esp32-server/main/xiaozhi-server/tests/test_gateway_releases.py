"""G18e：项目主人签名发布的固件（core/gateway/releases.py）。测试用临时生成的密钥，不碰真私钥。"""
import base64
import json
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.gateway import releases

ENTRY = {"type": "lichuang-dev", "file": "zongzhu-lichuang-dev-zongzhu-2.5.2.11.bin", "sha256": "a" * 64,
         "size": 2842864}


def keypair():
    key = Ed25519PrivateKey.generate()
    private = base64.b64encode(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                                 serialization.NoEncryption())).decode()
    public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,
                                                           serialization.PublicFormat.Raw)).decode()
    return private, public


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.private, self.public = keypair()
        self.manifest = releases.make_manifest("2.5.2.11", {"lichuang-dev-zongzhu": ENTRY}, 1_800_000_000)
        self.signature = releases.sign(self.manifest, self.private)

    def test_owner_signed_manifest_is_accepted(self):
        data = releases.verify(self.manifest, self.signature, self.public)
        self.assertEqual((data["version"], data["boards"]["lichuang-dev-zongzhu"]["type"]), ("2.5.2.11", "lichuang-dev"))

    def test_anything_changed_or_signed_by_someone_else_is_refused(self):
        tampered = self.manifest.replace(b"a" * 64, b"b" * 64)
        other_private, _ = keypair()
        for manifest, signature in ((tampered, self.signature),
                                    (self.manifest, releases.sign(self.manifest, other_private)),
                                    (self.manifest, b"not base64!!")):
            with self.assertRaises(releases.ReleaseError):
                releases.verify(manifest, signature, self.public)

    def test_well_signed_but_malformed_is_refused(self):
        for boards in ({"../evil": ENTRY}, {"lichuang-dev-zongzhu": dict(ENTRY, file="../x.bin")},
                       {"lichuang-dev-zongzhu": dict(ENTRY, sha256="short")}):
            manifest = releases.make_manifest("2.5.2.11", boards, 1)
            with self.assertRaises(releases.ReleaseError):
                releases.verify(manifest, releases.sign(manifest, self.private), self.public)

    def test_the_project_key_is_a_real_public_key(self):
        self.assertEqual(len(base64.b64decode(releases.PUBLIC_KEY)), 32)
        self.assertTrue(json.loads(self.manifest)["published"])



class CheckTest(unittest.IsolatedAsyncioTestCase):
    """每个后端查发布：用假的 GitHub（httpx.MockTransport）。"""

    def setUp(self):
        import hashlib
        import tempfile
        from pathlib import Path
        from unittest import mock

        from core.gateway import firmware, status
        from tests.test_gateway_firmware import image

        self.private, public = keypair()
        patcher = mock.patch.object(releases, "PUBLIC_KEY", public)  # 测试密钥，不碰真私钥
        patcher.start()
        self.addCleanup(patcher.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = mock.patch.object(firmware, "BIN_DIR", Path(directory.name) / "bin")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.firmware = firmware
        status._boards["aa:bb:cc:dd:ee:01"] = {"type": "lichuang-dev", "name": "lichuang-dev-zongzhu",
                                               "version": "2.5.2.10", "info": {"chip": "esp32s3"}}
        self.addCleanup(status._boards.pop, "aa:bb:cc:dd:ee:01", None)
        self.bin = image("2.5.2.11", board=b"lichuang-dev\0lichuang-dev-zongzhu\0")
        self.entry = {"type": "lichuang-dev", "file": "zongzhu-lichuang-dev-zongzhu-2.5.2.11.bin",
                      "sha256": hashlib.sha256(self.bin).hexdigest(), "size": len(self.bin)}
        self.files = {}

    def publish(self, entry=None, private=None, version="2.5.2.11"):
        manifest = releases.make_manifest(version, {"lichuang-dev-zongzhu": entry or self.entry}, 1)
        self.files = {"manifest.json": manifest, "manifest.sig": releases.sign(manifest, private or self.private),
                      self.entry["file"]: self.bin}

    async def check(self, config=None):
        import httpx

        def answer(request):
            name = request.url.path.rsplit("/", 1)[-1]
            if name == "releases":
                return httpx.Response(200, json=[{"tag_name": "v2.5.2.11", "assets": [
                    {"name": n, "browser_download_url": f"https://example.invalid/dl/{n}"} for n in self.files]}])
            return httpx.Response(200, content=self.files[name]) if name in self.files else httpx.Response(404)

        return await releases.check(config or {}, transport=httpx.MockTransport(answer))

    async def test_owner_release_newer_than_my_board_is_put_in_place(self):
        self.publish()
        result = await self.check()
        self.assertIn("放好了", result)
        self.assertEqual([(f["type"], f["version"]) for f in self.firmware.listing()],
                         [("lichuang-dev-zongzhu", "2.5.2.11")])  # core/api/ota_handler.py 按变体名找

    async def test_someone_elses_or_damaged_release_is_not_taken(self):
        other, _ = keypair()
        self.publish(private=other)
        self.assertEqual(await self.check(), "项目还没有发布过签名的固件")
        self.publish(entry=dict(self.entry, sha256="0" * 64))
        self.assertIn("对不上", await self.check())
        self.assertEqual(self.firmware.listing(), [])

    async def test_nothing_to_do_when_my_board_is_up_to_date_or_checks_are_off(self):
        self.publish(version="2.5.2.10", entry=dict(self.entry, file="x-2.5.2.10.bin"))
        self.assertIn("不用更新", await self.check())
        self.assertIn("没开", await self.check({"gateway": {"firmware_releases": False}}))
        self.assertEqual(self.firmware.listing(), [])


if __name__ == "__main__":
    unittest.main()
