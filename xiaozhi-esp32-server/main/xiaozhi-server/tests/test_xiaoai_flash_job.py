"""G25 ③ 第 3 步：刷机任务。假 update 用一个目录当音箱的分区（读、写、改启动参数都落在文件上），
做镜像、查官方包、等插电都换成假的，从头到尾跑一遍，不碰音箱、不联网。"""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.gateway.control import ControlError
from core.gateway.xiaoai import flash, flash_job, image

# 分区内容在 $FLASH_STATE/<分区>；读出来补 0xff 到分区大小；BAD 存在时写进去的内容会坏
FAKE_UPDATE = r"""#!/bin/bash
S=$FLASH_STATE
echo "$*" >> "$S/calls.txt"
case "$1" in
  identify) echo "This firmware version is 0-7-0-16-0-0-0" ;;
  mread) f="$S/$3"; [ -f "$f" ] || : > "$f"; n=$(wc -c < "$f")
         { cat "$f"; head -c $(( $5 - n )) /dev/zero | LC_ALL=C tr '\0' '\377'; } > "$6"; echo "[Uploading]OK" ;;
  partition) if [ -e "$S/BAD" ]; then printf 'broken' > "$S/$2"; else cp "$3" "$S/$2"; fi
             echo "[update]mwrite success" ;;
  bulkcmd) echo "$2" >> "$S/env.txt"; echo "[AmlUsbRom]Inf:bulkInReply success" ;;
esac
"""

KERNEL, SYSTEM = b"official-kernel" * 100, b"official-system" * 300
OLD_KERNEL, OLD_SYSTEM = b"older-kernel" * 100, b"older-system" * 300


class FlashJobTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.state = self.dir / "speaker"
        self.state.mkdir()
        update = self.dir / "update"
        update.write_text(FAKE_UPDATE)
        update.chmod(0o755)
        self.wait = asyncio.Event()
        self.wait.set()

        async def fake_wait(seconds, on_line=None):
            await self.wait.wait()
            return "0-7-0-16-0-0-0-0"

        async def fake_build(firmware, password, on_line=None):
            self.password = password
            out = self.dir / "work" / "build-1"
            (out / "extracted").mkdir(parents=True)
            (out / "extracted" / "boot.img.encrypt").write_bytes(KERNEL)
            (out / "extracted" / "root.squashfs").write_bytes(SYSTEM)
            (out / "boot.img.encrypt").write_bytes(KERNEL)
            (out / "root-patched.squashfs").write_bytes(b"patched-system" * 300)
            return {"dir": out, "rootfs": out / "root-patched.squashfs", "kernel": out / "boot.img.encrypt",
                    "size": 4200, "md5": {}}

        info = {"version": "1.62.2", "link": "x", "hash": "0" * 32, "size": 37822040}
        for p in (mock.patch.dict("os.environ", FLASH_STATE=str(self.state)),
                  mock.patch.dict(flash.PARTITIONS, {name: 0x10000 for name in flash.PARTITIONS}),  # 读得快些
                  mock.patch.object(image, "WORK", self.dir / "work"),
                  mock.patch.object(flash, "check", lambda: {"ok": True, "missing": [], "update": True}),
                  mock.patch.object(flash, "ensure_update", mock.AsyncMock(return_value=update)),
                  mock.patch.object(flash, "wait_device", fake_wait),
                  mock.patch.object(image, "query", mock.AsyncMock(return_value=info)),
                  mock.patch.object(image, "download", lambda info, progress=None: self.dir / "fw.bin"),
                  mock.patch.object(image, "build", fake_build),
                  mock.patch.dict(flash_job.job, state="idle", steps=[], error="", result=None, writing=False)):
            p.start()
            self.addCleanup(p.stop)

    def speaker(self, boot0, system0, boot1, system1):
        for name, data in (("boot0", boot0), ("system0", system0), ("boot1", boot1), ("system1", system1),
                           ("bootloader", b"bl"), ("tpl", b"tpl")):
            (self.state / name).write_bytes(data)

    def calls(self, command):
        return [c for c in (self.state / "calls.txt").read_text().splitlines() if c.startswith(command)]

    def env(self):
        path = self.state / "env.txt"
        return path.read_text().splitlines() if path.exists() else []

    async def start(self, **value):
        value = {"version": "1.62.2", "password": "pw", "confirm": True} | value
        await flash_job.act({}, "speaker_flash_start", value)
        await flash_job._task
        return flash_job.view()["job"]

    async def test_a_fresh_speaker_gets_the_other_side(self):
        self.speaker(OLD_KERNEL, OLD_SYSTEM, KERNEL, SYSTEM)  # 现在从 1 号启动官方的，0 号是旧版本
        job = await self.start()
        self.assertEqual(job["state"], "done", job["error"])
        self.assertEqual(self.password, "pw")
        self.assertEqual(job["result"]["slot"], 0)
        self.assertEqual((self.state / "boot0").read_bytes(), KERNEL)
        self.assertEqual((self.state / "system0").read_bytes(), b"patched-system" * 300)
        self.assertEqual((self.state / "system1").read_bytes(), SYSTEM)  # 退路没动
        self.assertEqual(self.env(), ["setenv boot_part boot0", "saveenv"])
        self.assertEqual([s["name"] for s in job["steps"]], list(flash_job.STEPS))
        self.assertTrue(all(s["state"] == "done" for s in job["steps"]))
        backup = Path(job["result"]["backup"])
        self.assertEqual(sorted(p.name for p in backup.iterdir()),
                         sorted([f"{n}.img" for n in flash_job.BACKUP] + ["md5.txt"]))
        self.assertTrue((backup / "system0.img").read_bytes().startswith(OLD_SYSTEM))
        self.assertFalse((self.dir / "work" / "build-1").exists())  # 镜像里有密码串，刷完删

    async def test_choosing_the_side(self):
        cases = ((KERNEL, b"patched", KERNEL, SYSTEM, 0),  # 已经刷过补丁的：重刷 0 号，1 号官方的不动
                 (KERNEL, SYSTEM, KERNEL, SYSTEM, 0),
                 (KERNEL, SYSTEM, OLD_KERNEL, OLD_SYSTEM, 1),
                 (KERNEL, SYSTEM, OLD_KERNEL, SYSTEM, 1))  # 1 号内核不是官方的也不算官方的一边
        for boot0, system0, boot1, system1, slot in cases:
            self.speaker(boot0, system0, boot1, system1)
            (self.state / "env.txt").unlink(missing_ok=True)
            job = await self.start()
            self.assertEqual(job["result"]["slot"], slot)
            self.assertEqual(self.env()[-2:], [f"setenv boot_part boot{slot}", "saveenv"])

    async def test_no_official_side_writes_nothing(self):
        self.speaker(OLD_KERNEL, OLD_SYSTEM, KERNEL, b"patched")
        job = await self.start()
        self.assertEqual(job["state"], "error")
        self.assertIn("两边都和官方包对不上", job["error"])
        self.assertEqual(self.calls("partition"), [])
        self.assertEqual(self.env(), [])
        self.assertEqual(job["steps"][-1], {"name": "选边", "state": "error", "detail": ""})

    async def test_a_bad_readback_stops_before_the_boot_settings(self):
        self.speaker(OLD_KERNEL, OLD_SYSTEM, KERNEL, SYSTEM)
        (self.state / "BAD").touch()
        job = await self.start()
        self.assertEqual(job["state"], "error")
        self.assertIn("boot0 写了两次", job["error"])
        self.assertEqual(len(self.calls("partition")), 2)
        self.assertEqual(self.env(), [])
        self.assertFalse((self.dir / "work" / "build-1").exists())

    async def test_bootdelay_is_set_first(self):
        self.speaker(OLD_KERNEL, OLD_SYSTEM, KERNEL, SYSTEM)
        await self.start(bootdelay=15)
        self.assertEqual(self.env(), ["setenv bootdelay 15", "setenv boot_part boot0", "saveenv"])

    async def test_cancel_while_waiting_for_the_speaker(self):
        self.speaker(OLD_KERNEL, OLD_SYSTEM, KERNEL, SYSTEM)
        self.wait.clear()
        await flash_job.act({}, "speaker_flash_start", {"version": "1.62.2", "password": "pw", "confirm": True})
        while not flash_job.job["steps"] or flash_job.job["steps"][-1]["name"] != "等音箱进刷机模式":
            await asyncio.sleep(0.01)
        with self.assertRaisesRegex(ControlError, "正在刷"):
            await flash_job.act({}, "speaker_flash_start", {"version": "1.62.2", "password": "pw", "confirm": True})
        self.assertIn("停下了", (await flash_job.act({}, "speaker_flash_cancel", None))["message"])
        with self.assertRaises(asyncio.CancelledError):
            await flash_job._task
        self.assertEqual(flash_job.job["state"], "cancelled")
        self.assertFalse((self.state / "calls.txt").exists())
        self.assertFalse((self.dir / "work" / "build-1").exists())

    async def test_a_dry_run_stops_after_choosing_and_writes_nothing(self):
        self.speaker(KERNEL, b"patched", KERNEL, SYSTEM)  # 你的音箱现在这样
        await flash_job.act({}, "speaker_flash_start", {"version": "1.62.2", "dry_run": True})  # 不用密码和确认
        await flash_job._task
        view = flash_job.view()
        job = view["job"]
        self.assertEqual(job["state"], "done", job["error"])
        self.assertTrue(job["dry_run"])
        self.assertEqual(job["result"]["slot"], 0)
        self.assertTrue(job["result"]["dry_run"])
        self.assertEqual([s["name"] for s in job["steps"]], view["dry_run_steps"])
        self.assertEqual(view["dry_run_steps"][-1], "选边")
        self.assertEqual(self.calls("partition"), [])
        self.assertEqual(self.env(), [])
        self.assertEqual((self.state / "system0").read_bytes(), b"patched")
        self.assertGreaterEqual(len(self.password), 20)  # 一次性的随机密码
        self.assertFalse((self.dir / "work" / "build-1").exists())
        self.assertEqual(len(list(Path(job["result"]["backup"]).glob("*.img"))), 6)

    async def test_no_cancel_once_writing(self):
        flash_job.job.update(state="running", writing=True)
        with self.assertRaisesRegex(ControlError, "不能停"):
            await flash_job.act({}, "speaker_flash_cancel", None)

    async def test_the_form_is_checked(self):
        for value, reason in (({"version": "1.62.2", "password": "pw"}, "确认"),
                              ({"version": "abc", "password": "pw", "confirm": True}, "版本不对"),
                              ({"version": "1.62.2", "password": "", "confirm": True}, "root 密码"),
                              ({"version": "1.62.2", "password": "pw", "confirm": True, "bootdelay": 99}, "bootdelay")):
            with self.assertRaisesRegex(ControlError, reason):
                await flash_job.act({}, "speaker_flash_start", value)
        self.assertEqual(flash_job.job["state"], "idle")

    async def test_missing_tools_stop_at_the_first_step(self):
        with mock.patch.object(flash, "check", lambda: {"ok": False, "missing": ["缺 Homebrew 的 libusb"], "update": False}):
            job = await self.start()
        self.assertEqual(job["state"], "error")
        self.assertIn("libusb", job["error"])
        self.assertEqual(len(job["steps"]), 1)

    def test_the_password_is_not_kept(self):
        self.assertNotIn("password", repr(flash_job.view()))
