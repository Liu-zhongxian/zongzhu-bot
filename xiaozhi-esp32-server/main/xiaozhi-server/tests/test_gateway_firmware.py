"""G18c：网关页面上给板子更新固件（core/gateway/firmware.py）：上传时的校验最要紧。"""
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.gateway import firmware

REPO = Path(__file__).resolve().parents[4]


def image(version="2.5.3.0", project="xiaozhi", chip=9, board=b"lichuang-dev"):
    """A minimal ESP32 app image header, laid out like the real xiaozhi.bin."""
    data = bytearray(4096)
    data[0] = 0xE9
    struct.pack_into("<H", data, 12, chip)
    struct.pack_into("<I", data, 32, 0xABCD5432)
    data[48:48 + len(version)] = version.encode()
    data[80:80 + len(project)] = project.encode()
    data[112:120], data[128:139] = b"16:32:51", b"Oct 19 2026"
    data[1000:1000 + len(board)] = board
    return bytes(data)


BOARD = {"type": "lichuang-dev", "version": "2.5.2.9", "info": {"chip": "esp32s3"}}


class CheckTest(unittest.TestCase):
    def test_right_board_newer_version_passes(self):
        info = firmware.check(image(), BOARD)
        self.assertEqual((info["version"], info["newer"], info["board_version"]), ("2.5.3.0", True, "2.5.2.9"))
        self.assertEqual(info["built"], "Oct 19 2026 16:32:51")
        self.assertFalse(firmware.check(image("2.5.2.9"), BOARD)["newer"])  # 同版本要另外确认
        self.assertFalse(firmware.check(image("2.5.1.10"), BOARD)["newer"])

    def test_variant_is_checked_and_named_when_the_board_reports_it(self):
        board = dict(BOARD, name="lichuang-dev-zongzhu")
        self.assertEqual(firmware.check(image(board=b"lichuang-dev\0lichuang-dev-zongzhu\0"), board)["model"],
                         "lichuang-dev-zongzhu")
        with self.assertRaises(firmware.FirmwareError) as caught:
            firmware.check(image(board=b"lichuang-dev\0lichuang-dev\0"), board)  # 同型号的官方版本
        self.assertIn("lichuang-dev-zongzhu", str(caught.exception))
        self.assertEqual(firmware.check(image(), BOARD)["model"], "lichuang-dev")  # 没报变体：按型号

    def test_wrong_files_are_refused(self):
        for bad, why in ((b"not firmware" * 100, "不是 ESP32"),
                         (image(project="other"), "不是小智"),
                         (image(board=b"m5stack-stopwatch"), "型号"),
                         (image(chip=5), "芯片")):
            with self.assertRaises(firmware.FirmwareError) as caught:
                firmware.check(bad, BOARD)
            self.assertIn(why, str(caught.exception))
        with self.assertRaises(firmware.FirmwareError):
            firmware.check(image(), {"version": "2.5.2.9"})  # 还不知道型号

    @unittest.skipUnless((REPO / "firmware/zongzhu-szp-2.5.2.9/xiaozhi.bin").exists(), "仓库里没有编译好的固件")
    def test_real_firmware_only_fits_its_own_board(self):
        szp = (REPO / "firmware/zongzhu-szp-2.5.2.9/xiaozhi.bin").read_bytes()
        self.assertEqual(firmware.check(szp, BOARD)["version"], "2.5.2.9")
        self.assertEqual(firmware.check(szp, dict(BOARD, name="lichuang-dev-zongzhu"))["model"], "lichuang-dev-zongzhu")
        with self.assertRaises(firmware.FirmwareError):
            firmware.check(szp, {"type": "m5stack-stopwatch", "version": "2.5.2.9"})


class FilesTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = mock.patch.object(firmware, "BIN_DIR", Path(directory.name) / "bin")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_saved_under_the_name_the_boot_check_reads(self):
        name = firmware.save(image(), "lichuang-dev", "2.5.3.0")
        self.assertEqual(name, "lichuang-dev_2.5.3.0.bin")  # core/api/ota_handler.py: {model}_{version}.bin
        self.assertEqual([(f["type"], f["version"]) for f in firmware.listing()], [("lichuang-dev", "2.5.3.0")])
        with self.assertRaises(firmware.FirmwareError):
            firmware.delete("../.config.yaml")
        firmware.delete(name)
        self.assertEqual(firmware.listing(), [])
        with self.assertRaises(firmware.FirmwareError):
            firmware.save(image(), "../evil", "1")


if __name__ == "__main__":
    unittest.main()
