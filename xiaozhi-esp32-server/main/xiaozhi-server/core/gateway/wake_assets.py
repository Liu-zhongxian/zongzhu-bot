"""G8b：改资源分区里的唤醒词，板子下次开机下载后生效，不用重编固件。

固件开机时从资源分区（assets）的 index.json → multinet_model.commands 读唤醒词
（xiaozhi-esp32 main/audio/wake_words/custom_wake_word.cc）；后端用 MCP 工具
self.assets.set_download_url 把新资源包的地址存进板子，下次开机 Application::CheckAssetsVersion
下载整个分区并换上。下载地址只能在板子醒着、连着的时候发（待机时连接是断的）。

格式和改法照搬刷机网页 web/lib/assets.js（它又对应 scripts/build_default_assets.py 的
pack_assets_simple()），两边改出来的文件逐字节一样：
  u32 文件数 | u32 校验和 | u32 长度 | 文件表 | 数据
  表项：name[32] | u32 size | u32 offset | u16 width | u16 height
  数据里每个文件前面有 "ZZ"（0x5A5A），offset 从数据区开头算
  校验和 = (文件表 + 数据) 所有字节之和 & 0xFFFF
"""
import hashlib
import json
import os
import re
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.gateway.board_tools import call_board_tool

_NAME_LEN = 32
_TABLE_ENTRY = 44
# 中文 MultiNet 的命令词是不带声调的拼音，ü 写成 v
_COMMAND = re.compile(r"^[a-z]+(?: [a-z]+)*$")

ASSETS_DIR = Path("data") / "wake_assets"  # relative to the server directory
_FILE = re.compile(r"^([0-9a-z]{1,32})-[0-9a-f]{12}\.bin$")


@dataclass
class AssetFile:
    name: str
    width: int
    height: int
    data: bytes


def read_assets(image: bytes) -> list:
    if len(image) < 12:
        raise ValueError("不是有效的资源分区文件")
    count, _, length = struct.unpack_from("<III", image, 0)
    table_end = 12 + count * _TABLE_ENTRY
    if count == 0 or count > 1000 or 12 + length > len(image):
        raise ValueError("不是有效的资源分区文件")
    files = []
    for i in range(count):
        base = 12 + i * _TABLE_ENTRY
        name = image[base:base + _NAME_LEN].split(b"\0", 1)[0].decode()
        size, offset, width, height = struct.unpack_from("<IIHH", image, base + _NAME_LEN)
        start = table_end + offset
        if image[start:start + 2] != b"ZZ":
            raise ValueError(f"资源文件 {name} 格式不对")
        files.append(AssetFile(name, width, height, bytes(image[start + 2:start + 2 + size])))
    return files


def pack_assets(files) -> bytes:
    table, data = bytearray(), bytearray()
    for f in files:
        table += f.name.encode()[:_NAME_LEN].ljust(_NAME_LEN, b"\0")
        table += struct.pack("<IIHH", len(f.data), len(data), f.width, f.height)
        data += b"ZZ" + f.data
    body = bytes(table + data)
    return struct.pack("<III", len(files), sum(body) & 0xFFFF, len(body)) + body


def _index(files):
    index = next((f for f in files if f.name == "index.json"), None)
    if index is None:
        raise ValueError("资源分区里没有 index.json")
    return index, json.loads(index.data)


def wake_word_of(image: bytes):
    """资源包里的唤醒词，如 {"command": "ni hao zong zhu", "text": "你好宗主", "action": "wake"}。"""
    _, config = _index(read_assets(image))
    commands = (config.get("multinet_model") or {}).get("commands") or []
    return next((c for c in commands if c.get("action") == "wake"), None)


def pinyin_command(text: str) -> str:
    """唤醒词的拼音命令词：不带声调，ü 写成 v（"你好小雨" → "ni hao xiao yu"）。"""
    from pypinyin import Style, lazy_pinyin

    return " ".join(lazy_pinyin(text, style=Style.NORMAL, v_to_u=False)).lower()


def check_wake_word(text: str, command: str):
    """唤醒词不合适的原因；合适时返回 None。"""
    if not re.fullmatch(r"[一-鿿]+", text or ""):
        return "唤醒词只能是中文（英文唤醒词要英文模型，资源包里没有，见 G9）"
    if not 2 <= len(text) <= 8:
        return "唤醒词要 2–8 个字，4–6 个字最好，太短容易误唤醒"
    if not _COMMAND.fullmatch(command or ""):
        return "拼音只能是小写字母，每个字之间一个空格，ü 写成 v"
    if len(command.split()) != len(text):
        return "拼音的字数和唤醒词对不上"
    return None


def set_wake_word(image: bytes, text: str, command: str, threshold=None) -> bytes:
    """换掉资源包里的唤醒词，其他文件原样保留；和 web/lib/assets.js 的 setWakeWord 一样。"""
    reason = check_wake_word(text, command)
    if reason:
        raise ValueError(reason)
    files = read_assets(image)
    index, config = _index(files)
    if not config.get("multinet_model"):
        raise ValueError("这个固件的资源分区不支持自定义唤醒词")
    config["multinet_model"]["commands"] = [{"command": command, "text": text, "action": "wake"}]
    if threshold is not None:
        config["multinet_model"]["threshold"] = threshold
    # 和 JSON.stringify(json, null, 4) 一样的写法
    index.data = json.dumps(config, ensure_ascii=False, indent=4).encode()
    return pack_assets(files)


def save(device_id: str, image: bytes) -> str:
    """存下给这块板子的资源包，返回文件名；这块板子之前的资源包删掉。"""
    prefix = re.sub(r"[^0-9a-z]", "", device_id.lower())[:32] or "board"
    name = f"{prefix}-{hashlib.sha256(image).hexdigest()[:12]}.bin"
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for old in ASSETS_DIR.glob(f"{prefix}-*.bin"):
        if old.name != name:
            old.unlink(missing_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ASSETS_DIR, prefix=".wake.", suffix=".tmp")
    with os.fdopen(fd, "wb") as f:
        f.write(image)
    os.replace(tmp, ASSETS_DIR / name)
    return name


def path_of(filename: str):
    """GET /gateway/assets/<文件名> 能下载的文件；名字不对或不存在时 None。"""
    path = ASSETS_DIR / filename
    return path if _FILE.fullmatch(filename or "") and path.is_file() else None


def download_url(config: dict, filename: str) -> str:
    """板子能访问的下载地址：和 OTA 下发固件一样，用 server.vision_explain 的前缀（没填时是 Mac 的局域网 IP）。"""
    from core.utils.util import get_vision_url

    return get_vision_url(config).replace("/mcp/vision/explain", f"/gateway/assets/{filename}")


async def change_wake_word(conn, source: bytes, text: str, command: str, reboot: bool = True) -> dict:
    """生成新资源包、把地址发给板子；reboot=True 时让板子重启，开机下载后用新唤醒词。"""
    image = set_wake_word(source, text, command)
    url = download_url(conn.config, save(conn.device_id, image))
    await call_board_tool(conn, "self.assets.set_download_url", {"url": url})
    result = {"url": url, "size": len(image), "wake": {"text": text, "command": command}, "rebooting": reboot}
    if reboot:
        try:
            await call_board_tool(conn, "self.reboot", {}, timeout=5)
        except RuntimeError:
            # 实机：板子收到后立刻断开重启，来不及回应（2026-10-30）。地址已经存进板子，不算失败。
            result["note"] = "重启指令没收到回应：板子多半已经在重启；如果没有重启，请手动重启。"
    return result
