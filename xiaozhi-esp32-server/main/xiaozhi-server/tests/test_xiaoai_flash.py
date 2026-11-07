"""G25 ③ 第 1 步：刷机工具层。用假的 update 和假的 aml_wait.py，不碰 USB。"""
import asyncio
import hashlib
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from core.gateway.xiaoai import flash

# 假 update：输出照 10-30 的真实日志；FAKE_FAIL 里写哪条命令就让哪条失败；每次调用记进 calls.txt
FAKE_UPDATE = r"""#!/bin/sh
here=$(dirname "$0")
echo "$*" >> "$here/calls.txt"
grep -qx "$1" "$here/fail.txt" 2>/dev/null && { echo "[AmlUsbRom]Err:bulkInReply failed"; exit 0; }
case "$1" in
  identify) echo "AmlUsbIdentifyHost"; echo "This firmware version is 0-7-0-16-0-0-0" ;;
  mread) echo "AmlUsbBulkCmd[upload store $3 normal $5]"; head -c $(($5)) /dev/zero > "$6"; echo "[Uploading]OK" ;;
  partition) echo "file size is 0x10"; echo "[update]mwrite success" ;;
  bulkcmd) echo "AmlUsbBulkCmd[$2]"; echo "[AmlUsbRom]Inf:bulkInReply success" ;;
esac
"""


class FlashTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.update = self.dir / "update"
        self.update.write_text(FAKE_UPDATE)
        self.update.chmod(0o755)
        self.lines = []
        self.tool = flash.Update(self.update, log=self.lines.append)

    def calls(self):
        path = self.dir / "calls.txt"
        return path.read_text().splitlines() if path.exists() else []

    def fail(self, command):
        (self.dir / "fail.txt").write_text(command + "\n")

    # update 的命令
    async def test_identify_reads_the_version(self):
        self.assertEqual(await self.tool.identify(), "0-7-0-16-0-0-0")
        self.assertIn("This firmware version", self.lines[0])

    async def test_mread_checks_the_size(self):
        dest = await self.tool.mread("boot0", self.dir / "boot0.img")
        self.assertEqual(dest.stat().st_size, 0x600000)
        self.assertEqual(self.calls(), [f"mread store boot0 normal 0x600000 {self.dir / 'boot0.img'}"])
        self.fail("mread")
        with self.assertRaisesRegex(flash.FlashError, "读 boot1 没成功"):
            await self.tool.mread("boot1", self.dir / "boot1.img")
        with self.assertRaisesRegex(flash.FlashError, "不认识的分区"):
            await self.tool.mread("data", self.dir / "data.img")

    async def test_partition_writes_only_boot_and_system(self):
        image = self.dir / "img"
        image.write_bytes(b"x" * 16)
        await self.tool.partition("system0", image)
        self.assertEqual(self.calls(), [f"partition system0 {image}"])
        for name in ("bootloader", "tpl", "data"):
            with self.assertRaisesRegex(flash.FlashError, "不能写"):
                await self.tool.partition(name, image)
        self.assertEqual(len(self.calls()), 1)
        self.fail("partition")
        with self.assertRaisesRegex(flash.FlashError, "写 system1 没成功"):
            await self.tool.partition("system1", image)

    async def test_partition_refuses_an_image_bigger_than_the_partition(self):
        image = self.dir / "big"
        with image.open("wb") as f:
            f.truncate(0x600001)
        with self.assertRaisesRegex(flash.FlashError, "比 boot0 分区大"):
            await self.tool.partition("boot0", image)
        self.assertEqual(self.calls(), [])

    async def test_bulkcmd_only_sends_the_boot_settings(self):
        for command in ("setenv boot_part boot1", "setenv bootdelay 15", "saveenv"):
            await self.tool.bulkcmd(command)
        for command in ("setenv boot_part boot2", "saveenv; reset", "run update", "setenv bootcmd x"):
            with self.assertRaisesRegex(flash.FlashError, "不发这条命令"):
                await self.tool.bulkcmd(command)
        self.assertEqual(len(self.calls()), 3)
        self.fail("bulkcmd")
        with self.assertRaisesRegex(flash.FlashError, "saveenv 没成功"):
            await self.tool.bulkcmd("saveenv")

    async def test_a_hanging_command_is_stopped(self):
        self.update.write_text("#!/bin/sh\nsleep 30\n")
        with self.assertRaisesRegex(flash.FlashError, "超过 1 秒"):
            await self.tool.run("identify", timeout=1)

    # 等刷机模式
    def fake_wait(self, body):
        script = self.dir / "aml_wait.py"
        script.write_text(textwrap.dedent(body))
        return mock.patch.object(flash, "AML_WAIT", script)

    async def test_wait_device_returns_the_version(self):
        seen = []
        with self.fake_wait("""
                import sys
                print("20:49:35 看到刷机设备 1b8e:c003", flush=True)
                print("identify 成功，固件版本 0-7-0-16-0-0-0-0", flush=True)
                """):
            self.assertEqual(await flash.wait_device(5, seen.append), "0-7-0-16-0-0-0-0")
        self.assertEqual(len(seen), 2)

    async def test_wait_device_timeout(self):
        with self.fake_wait('print("超时：没有连上刷机设备", flush=True)\nraise SystemExit(1)\n'):
            with self.assertRaisesRegex(flash.FlashError, "没等到"):
                await flash.wait_device(5)

    async def test_cancelling_the_wait_stops_the_process(self):
        with self.fake_wait("""
                import os, time
                open(os.path.join(os.path.dirname(__file__), "pid"), "w").write(str(os.getpid()))
                time.sleep(60)
                """):
            task = asyncio.create_task(flash.wait_device(60))
            pid_file = self.dir / "pid"
            for _ in range(200):
                if pid_file.exists() and pid_file.read_text():
                    break
                await asyncio.sleep(0.02)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        pid = int(pid_file.read_text())
        with self.assertRaises(ProcessLookupError):
            import os
            os.kill(pid, 0)

    # 下载 update
    async def test_update_is_downloaded_and_checked(self):
        good = b"update binary"
        target = self.dir / "tools" / "update"

        class Response:
            def __init__(self, content):
                self.content = content

            def raise_for_status(self):
                pass

        with mock.patch.object(flash, "UPDATE_FILE", target), \
                mock.patch.object(flash, "UPDATE_SHA256", hashlib.sha256(good).hexdigest()), \
                mock.patch("httpx.AsyncClient.get", mock.AsyncMock(return_value=Response(b"evil"))):
            with self.assertRaisesRegex(flash.FlashError, "校验值不对"):
                await flash.ensure_update()
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.iterdir()), [])
        with mock.patch.object(flash, "UPDATE_FILE", target), \
                mock.patch.object(flash, "UPDATE_SHA256", hashlib.sha256(good).hexdigest()), \
                mock.patch("httpx.AsyncClient.get", mock.AsyncMock(return_value=Response(good))) as get:
            self.assertEqual(await flash.ensure_update(), target)
            self.assertEqual(target.read_bytes(), good)
            self.assertTrue(flash.update_ok(target))
            await flash.ensure_update()  # 已经有了就不再下载
            self.assertEqual(get.await_count, 1)

    def test_check_lists_what_is_missing(self):
        with mock.patch.object(flash, "_brew_file", lambda _: None), \
                mock.patch.object(flash, "libusb", lambda: None), \
                mock.patch("shutil.which", lambda _: None):
            result = flash.check()
        self.assertFalse(result["ok"])
        self.assertTrue(any("brew install libusb libusb-compat squashfs" in m for m in result["missing"]))


class BurnModeTest(unittest.TestCase):
    def test_burn_mode_is_looked_up_by_id_and_never_fails(self):
        import usb.core

        with mock.patch.object(flash, "libusb", return_value=None):
            self.assertFalse(flash.in_burn_mode())
        with mock.patch.object(flash, "libusb", return_value="/x/libusb.dylib"), \
                mock.patch("usb.backend.libusb1.get_backend", return_value=object()):
            with mock.patch.object(usb.core, "find", return_value=object()) as find:
                self.assertTrue(flash.in_burn_mode())
            self.assertEqual((find.call_args.kwargs["idVendor"], find.call_args.kwargs["idProduct"]), (0x1B8E, 0xC003))
            with mock.patch.object(usb.core, "find", return_value=None):
                self.assertFalse(flash.in_burn_mode())
            with mock.patch.object(usb.core, "find", side_effect=usb.core.NoBackendError("x")):
                self.assertFalse(flash.in_burn_mode())
