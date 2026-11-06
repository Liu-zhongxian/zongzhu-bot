"""G25 ③ 第 2 步：查官方包、下载、做镜像。假的小米接口、假的下载、假的 build_image.sh，不联网。"""
import hashlib
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.gateway.xiaoai import image

LINK = "https://cdn.cnbj1.fds.api.mi-img.com/xiaoqiang/rom/oh2p/mico_all_616cd9d93_1.62.2.bin"

# 假 build_image.sh：记下参数、环境里有没有密码、标准输入；FAIL 存在就像核对失败那样退出
FAKE_BUILD = r"""#!/usr/bin/env bash
here=$(dirname "$0")
echo "$*" > "$here/args.txt"
env | grep -c SPEAKER_ROOT_PASSWORD > "$here/env.txt"
read -rsp "音箱 root 密码（SSH 登录用）：" pw; echo
read -rsp "再输一次：" again; echo
printf '%s|%s' "$pw" "$again" > "$here/stdin.txt"
mkdir -p "$2"
echo "== 解开官方包（校验 CRC32 和 MD5）"
[ -e "$here/FAIL" ] && { echo "改动的文件和预期不一样，不要刷这个镜像"; exit 1; }
printf 'rootfs' > "$2/root-patched.squashfs"
printf 'kernel' > "$2/boot.img.encrypt"
echo "完成"
"""


class Response:
    def __init__(self, body=None, chunks=()):
        self.body, self.chunks = body, chunks

    def raise_for_status(self):
        pass

    def json(self):
        return self.body

    def iter_bytes(self, size):
        yield from self.chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ImageTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.script = self.dir / "build_image.sh"
        self.script.write_text(FAKE_BUILD)
        for p in (mock.patch.object(image, "WORK", self.dir / "work"),
                  mock.patch.object(image, "BUILD_SCRIPT", self.script)):
            p.start()
            self.addCleanup(p.stop)

    # 查官方包
    async def ota(self, current):
        with mock.patch("httpx.AsyncClient.get",
                        mock.AsyncMock(return_value=Response({"code": 0, "data": {"currentInfo": current}}))) as get:
            result = await image.query("1.62.2")
        return result, get

    async def test_query_returns_the_current_package(self):
        info, get = await self.ota({"link": LINK, "hash": "BC81F5B40F3DB5E9A9D5943616CD9D93", "size": 37822040})
        self.assertEqual(info, {"version": "1.62.2", "link": LINK, "hash": "bc81f5b40f3db5e9a9d5943616cd9d93",
                                "size": 37822040})
        params = get.call_args.kwargs["params"]
        self.assertEqual((params["version"], params["filterID"], params["model"]), ("1.62.2", "", "OH2P"))
        self.assertEqual(len(params["s"]), 32)

    async def test_an_unknown_version_or_odd_link_is_refused(self):
        with self.assertRaisesRegex(image.ImageError, "没有 1.62.2 的官方包"):
            await self.ota({})
        for link in ("http://cdn.cnbj1.fds.api.mi-img.com/xiaoqiang/rom/oh2p/mico_all_616cd9d93_1.62.2.bin",
                     "https://evil.example/mico_all_616cd9d93_1.62.2.bin",
                     "https://cdn.cnbj1.fds.api.mi-img.com/x/other.bin"):
            with self.assertRaisesRegex(image.ImageError, "不像预期"):
                await self.ota({"link": link, "hash": "0" * 32, "size": 1})
        with self.assertRaisesRegex(image.ImageError, "版本不对"):
            await image.query("1.62.2; rm")

    # 下载
    def test_download_checks_size_and_md5_and_reuses_a_good_copy(self):
        body = b"firmware" * 1000
        info = {"link": LINK, "hash": hashlib.md5(body).hexdigest(), "size": len(body)}
        with mock.patch("httpx.stream", return_value=Response(chunks=[b"wrong"])):
            with self.assertRaisesRegex(image.ImageError, "MD5"):
                image.download(info)
        self.assertEqual(list((self.dir / "work").iterdir()), [])
        seen = []
        with mock.patch("httpx.stream", return_value=Response(chunks=[body[:4000], body[4000:]])) as stream:
            path = image.download(info, lambda done, total: seen.append((done, total)))
            self.assertEqual(path.read_bytes(), body)
            self.assertEqual(seen, [(4000, len(body)), (len(body), len(body))])
            image.download(info)
            self.assertEqual(stream.call_count, 1)
        self.assertEqual(stat.S_IMODE((self.dir / "work").stat().st_mode), 0o700)

    # 做镜像
    async def test_build_passes_the_password_only_on_stdin(self):
        lines = []
        with mock.patch.dict("os.environ", SPEAKER_ROOT_PASSWORD="leak"):
            result = await image.build(self.dir / "fw.bin", "p@ss word", lines.append)
        self.assertEqual((self.dir / "stdin.txt").read_text(), "p@ss word|p@ss word")
        self.assertEqual((self.dir / "env.txt").read_text().strip(), "0")
        args = (self.dir / "args.txt").read_text()
        self.assertNotIn("p@ss", args)
        self.assertTrue(args.startswith(f"{self.dir / 'fw.bin'} {self.dir / 'work' / 'build-'}"))
        self.assertEqual(lines, ["== 解开官方包（校验 CRC32 和 MD5）", "完成"])
        self.assertEqual(result["rootfs"].read_text(), "rootfs")
        self.assertEqual(result["md5"]["kernel"], hashlib.md5(b"kernel").hexdigest())
        self.assertEqual(stat.S_IMODE(result["rootfs"].stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(result["dir"].stat().st_mode), 0o700)

    async def test_a_failed_build_leaves_nothing(self):
        (self.dir / "FAIL").touch()
        with self.assertRaisesRegex(image.ImageError, "不要刷这个镜像"):
            await image.build(self.dir / "fw.bin", "pw")
        self.assertEqual(list((self.dir / "work").iterdir()), [])

    async def test_bad_passwords(self):
        for password, reason in (("", "先填"), ("a\nb", "换行"), ("x" * 65, "64")):
            with self.assertRaisesRegex(image.ImageError, reason):
                await image.build(self.dir / "fw.bin", password)
        self.assertFalse((self.dir / "args.txt").exists())
