"""G18c：网关页面上给板子更新固件（OTA），不改固件。

固件文件存进 data/bin/<型号>_<版本>.bin：后端原有的开机检查（core/api/ota_handler.py）看到比板子新的
版本就让板子下载（"下次开机更新"，这个型号的板子都会更新）；板子醒着时也可以用 MCP 工具
self.upgrade_firmware 把下载地址发过去，马上下载、写进另一个 OTA 分区、重启（"立即更新"）。
固件开了 CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE，新固件起不来会退回旧版，但刷错型号也可能救不回来，
所以上传时先校验（2026-11-03 读了三块板子 2.5.2.9 的 xiaozhi.bin 定的）：
- ESP32 应用镜像：第 0 字节 0xE9，第 12–13 字节是芯片（9 = ESP32-S3）；第 32 字节起是应用描述
  （0xABCD5432，版本在 +16、项目名在 +48、编译时间 +80、日期 +96、IDF 版本 +112）；
- 项目名是 xiaozhi；
- 板子上报的型号（OTA 的 board.type，如 lichuang-dev）要出现在固件里：每份固件里只有它自己的型号名；
- 芯片和板子报的一样（板子报过芯片时）；
- 版本比板子上的新；同版本、降级要另外确认（force）。
"""
import re
import struct
import time
from pathlib import Path

BIN_DIR = Path("data") / "bin"  # relative to the server directory; core/api/ota_handler.py reads the same
MAX_SIZE = 8 * 1024 * 1024
CHIPS = {"esp32": 0, "esp32s2": 2, "esp32c3": 5, "esp32s3": 9, "esp32c2": 12, "esp32c6": 13, "esp32p4": 18}
_FILE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]{0,63})_([0-9][A-Za-z0-9._-]{0,31})\.bin$")


class FirmwareError(Exception):
    pass


def _text(image, offset, length):
    return image[offset:offset + length].split(b"\0")[0].decode("utf-8", "replace")


def describe(image: bytes) -> dict:
    """What the image says about itself; FirmwareError when it is not an ESP32 app image."""
    if len(image) < 256 or image[0] != 0xE9:
        raise FirmwareError("不是 ESP32 的固件文件（要选编译出来的 xiaozhi.bin，不是合并好的整片镜像）")
    if struct.unpack_from("<I", image, 32)[0] != 0xABCD5432:
        raise FirmwareError("固件里没有应用描述，读不到版本号")
    return {"chip": struct.unpack_from("<H", image, 12)[0], "version": _text(image, 48, 32),
            "project": _text(image, 80, 32), "built": f"{_text(image, 128, 16)} {_text(image, 112, 16)}",
            "idf": _text(image, 144, 32), "size": len(image)}


def _version(text):
    return tuple(int(n) for n in re.findall(r"\d+", text or ""))


def check(image: bytes, board: dict) -> dict:
    """describe() plus whether it fits this board; FirmwareError when it must not go on it.
    board: what the page knows (type and version from OTA, info.chip from MCP)."""
    if len(image) > MAX_SIZE:
        raise FirmwareError("文件超过 8 MB，不像是固件")
    info = describe(image)
    if info["project"] != "xiaozhi":
        raise FirmwareError(f"项目名是 {info['project'] or '空'}，不是小智固件")
    board_type = board.get("type") or ""
    if not board_type:
        raise FirmwareError("还不知道这块板子的型号：等它开机连一次后端再传")
    if board_type.encode() not in image:
        raise FirmwareError(f"固件里没有这块板子的型号 {board_type}：多半是别的板子的固件，不能刷")
    # The variant (board.name) too, as a whole string: lichuang-dev-zongzhu, esp32-s3-touch-amoled-1.75c.
    # (A 1.75C firmware also holds "esp32-s3-touch-amoled-1.75" as its type, so 1.75 vs 1.75C is not
    # fully told apart here; G18e publishes by the variant written at build time.)
    variant = board.get("name") or ""
    if variant and (variant.encode() + b"\0") not in image:
        raise FirmwareError(f"固件不是给 {variant} 编的（同型号的另一个版本？），不能刷")
    chip = ((board.get("info") or {}).get("chip") or "").lower().replace("-", "")
    if chip in CHIPS and CHIPS[chip] != info["chip"]:
        raise FirmwareError(f"芯片对不上：板子是 {chip}，固件是给芯片 {info['chip']} 的")
    current = board.get("version") or ""
    info["board_type"], info["board_version"] = board_type, current
    info["model"] = variant or board_type  # the file is saved and offered under this name
    info["newer"] = _version(info["version"]) > _version(current)
    return info


def save(image: bytes, board_type: str, version: str) -> str:
    """Into data/bin/ under the name the OTA check looks for; returns the file name."""
    name = f"{board_type}_{version}.bin"
    if not _FILE.fullmatch(name):
        raise FirmwareError("型号或版本号里有不能用在文件名里的字")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BIN_DIR / f".{name}.{int(time.time() * 1000)}.tmp"
    tmp.write_bytes(image)
    tmp.replace(BIN_DIR / name)
    return name


def listing() -> list:
    """The firmware files the boards may get, newest first."""
    files = []
    for path in BIN_DIR.glob("*.bin") if BIN_DIR.is_dir() else ():
        match = _FILE.fullmatch(path.name)
        if match and path.is_file() and not path.is_symlink():
            stat = path.stat()
            files.append({"file": path.name, "type": match.group(1), "version": match.group(2),
                          "size": stat.st_size, "time": stat.st_mtime})
    return sorted(files, key=lambda f: f["time"], reverse=True)


def path_of(name: str):
    path = BIN_DIR / name
    return path if _FILE.fullmatch(name or "") and path.is_file() and not path.is_symlink() else None


def delete(name: str) -> None:
    path = path_of(name)
    if path is None:
        raise FirmwareError("没有这个固件文件")
    path.unlink()


def download_url(config: dict, name: str) -> str:
    """Where the board downloads it: the OTA download endpoint, on the address the boards already use."""
    from core.utils.util import get_vision_url

    return get_vision_url(config).replace("/mcp/vision/explain", f"/xiaozhi/ota/download/{name}")


async def upgrade_now(conn, url: str) -> None:
    """The board answers at once, then downloads, writes the other OTA partition and reboots
    (the firmware schedules the upgrade after replying, mcp_server.cc)."""
    from core.gateway.board_tools import call_board_tool

    try:
        await call_board_tool(conn, "self.upgrade_firmware", {"url": url}, timeout=10)
    except (RuntimeError, TimeoutError) as e:
        raise FirmwareError(f"板子没接下更新：{e}") from None
