"""音箱刷机模式的工具层（G25 ③ 第 1 步）：网关页面刷补丁固件时，后端在这台电脑上操作 USB。

沿用 2026-10-30 实测刷成功的那套（zongzhu-speaker/README.md 第 4、5 步）：
- 抓刷机模式：音箱上电后晶晨刷机设备 1b8e:c003 只出现约 1–3 秒，而且没有序列号。另起一个进程跑
  zongzhu-speaker/firmware/aml_wait.py（pyusb + libusb，LIBUSB_DEBUG=4，和脚本一样），设备一出现就发只读的
  identify，音箱就一直停在刷机模式。
- 读写分区、改启动参数：晶晨的 `update` 工具（Amlogic 的程序，不进仓库）。没有就从 khadas/utils 固定的提交下载，
  SHA-256 不对就不用。它链接 Homebrew 的 libusb-compat。
- 每条命令成没成功按 `update` 的输出判断（10-30 的日志）：identify 有 "This firmware version is"，
  写分区有 "mwrite success"，bulkcmd 有 "bulkInReply success"，读分区看读出的文件是不是正好那么大。
只能写 boot0/1、system0/1，bulkcmd 只认改启动分区、bootdelay 和 saveenv：别的分区（bootloader、tpl、data）
写坏了没有退路，这里一律不让写。
只在 macOS 上做过；Docker 里摸不到 USB。
"""
import asyncio
import hashlib
import importlib.util
import os
import re
import shutil
import signal
import sys
from pathlib import Path

from core.gateway.xiaoai.install import REPO

UPDATE_URL = ("https://raw.githubusercontent.com/khadas/utils/0dee958a4c3c53c0546ef98758ed721183f11a5f/"
              "aml-flash-tool/tools/macos/update")
UPDATE_SHA256 = "19f37cc129d061512c24bffbbad3a51355d976c12d6091366fe7dfce3c949b30"  # v1.7.5，README 里的同一份
UPDATE_FILE = Path("data") / "tools" / "update"  # 相对后端目录
AML_WAIT = REPO / "zongzhu-speaker" / "firmware" / "aml_wait.py"
BREW = ("/opt/homebrew", "/usr/local")

# OH2P 实测（/proc/mtd，backup_readonly.sh）
PARTITIONS = {"system0": 0x2800000, "system1": 0x2800000, "boot0": 0x600000, "boot1": 0x600000,
              "bootloader": 0x200000, "tpl": 0x800000}
WRITABLE = {"boot0", "boot1", "system0", "system1"}
BULKCMDS = (re.compile(r"setenv boot_part boot[01]"), re.compile(r"setenv bootdelay \d{1,2}"), re.compile(r"saveenv"))
COMMAND_TIMEOUT = 300


class FlashError(Exception):
    pass


def _brew_file(relative):
    for prefix in BREW:
        path = Path(prefix) / relative
        if path.exists():
            return str(path)
    return None


def libusb() -> str | None:
    return os.environ.get("AML_LIBUSB") or _brew_file("lib/libusb-1.0.dylib")


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _kill(proc):
    """连它起的子进程一起停（各自一个进程组），不然留下的子进程占着输出管道"""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def update_ok(path=None) -> bool:
    path = Path(path or UPDATE_FILE)
    return path.is_file() and os.access(path, os.X_OK) and _sha256(path) == UPDATE_SHA256


def check() -> dict:
    """刷机要的东西齐不齐：{"ok": bool, "missing": [给人看的缺什么、怎么装], ...}"""
    missing = []
    in_docker = Path("/.dockerenv").exists() or bool(os.environ.get("ZONGZHU_HOST_HOME"))
    if sys.platform != "darwin" or in_docker:
        missing.append("刷机只在直接运行在 Mac 上的后端里能用（Docker 里摸不到 USB）")
    brew = []
    if not libusb():
        brew.append("libusb")
    if not _brew_file("opt/libusb-compat/lib/libusb-0.1.4.dylib"):
        brew.append("libusb-compat")
    if not all(shutil.which(c) or _brew_file(f"bin/{c}") for c in ("unsquashfs", "mksquashfs")):
        brew.append("squashfs")
    if brew:
        missing.append("缺 Homebrew 的 " + "、".join(brew) + f"：在终端运行 brew install {' '.join(brew)}")
    if importlib.util.find_spec("usb") is None:
        missing.append("后端的 Python 环境缺 pyusb：重新运行一键安装，或 .venv/bin/pip install pyusb==1.3.1")
    if not AML_WAIT.is_file():
        missing.append(f"找不到 {AML_WAIT}")
    return {"ok": not missing, "missing": missing, "update": update_ok()}


async def ensure_update() -> Path:
    """晶晨 update 工具：已有且校验对就用；没有就下载（约 210 KB），校验不对不用"""
    if await asyncio.to_thread(update_ok):
        return UPDATE_FILE
    import httpx

    UPDATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    part = UPDATE_FILE.with_name("update.part")
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            response = await client.get(UPDATE_URL)
            response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != UPDATE_SHA256:
            raise FlashError("下载的刷机工具 update 校验值不对，没有用它")
        part.write_bytes(response.content)
        part.chmod(0o755)
        part.replace(UPDATE_FILE)
    except httpx.HTTPError as e:
        raise FlashError(f"下载刷机工具 update 失败：{type(e).__name__} {e}"[:200]) from None
    finally:
        part.unlink(missing_ok=True)
    return UPDATE_FILE


async def wait_device(seconds: float, on_line=None) -> str:
    """等音箱进刷机模式并发 identify；返回固件版本（如 0-7-0-16-0-0-0-0）。被取消就停掉等待的进程"""
    env = dict(os.environ, LIBUSB_DEBUG="4")  # 10-30 第 5 次就是这样抓住的（第 3、4 次级别 3 没抓住，原因没查明）
    if libusb():
        env["AML_LIBUSB"] = libusb()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-I", str(AML_WAIT), str(int(seconds)), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
    version = None
    try:
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").strip()
            if on_line and line:
                on_line(line)
            found = re.search(r"identify 成功，固件版本 ([\d-]+)", line)
            if found:
                version = found.group(1)
        await proc.wait()
    finally:
        if proc.returncode is None:
            _kill(proc)
            await proc.wait()
    if not version:
        raise FlashError("没等到音箱的刷机模式：拔掉音箱电源，再点开始、插电")
    return version


class Update:
    """调用晶晨 update；每条命令按输出判断成没成功，不成功抛 FlashError（带输出最后几行）"""

    def __init__(self, path=None, log=None):
        self.path = str(path or UPDATE_FILE)
        self.log = log  # 收每条命令的完整输出（页面"详细记录"、出错时查）

    async def run(self, *args, timeout=COMMAND_TIMEOUT) -> str:
        proc = await asyncio.create_subprocess_exec(self.path, *args, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            _kill(proc)
            await proc.communicate()
            raise FlashError(f"update {args[0]} 超过 {timeout} 秒没结束") from None
        except asyncio.CancelledError:
            _kill(proc)
            raise
        text = out.decode(errors="replace")
        if self.log:
            self.log(f"$ update {' '.join(args)}\n{text}")
        return text

    @staticmethod
    def _fail(what, text):
        tail = " / ".join(line.strip() for line in text.strip().splitlines()[-3:])
        return FlashError(f"{what}没成功：{tail}"[:300])

    async def identify(self) -> str:
        text = await self.run("identify", "7", timeout=30)
        found = re.search(r"firmware version is ([\d-]+)", text)
        if not found:
            raise self._fail("identify ", text)
        return found.group(1)

    async def mread(self, partition, dest) -> Path:
        """读整个分区到 dest（只读）"""
        if partition not in PARTITIONS:
            raise FlashError(f"不认识的分区 {partition}")
        size = PARTITIONS[partition]
        dest = Path(dest)
        dest.unlink(missing_ok=True)
        text = await self.run("mread", "store", partition, "normal", hex(size), str(dest))
        if not dest.is_file() or dest.stat().st_size != size:
            raise self._fail(f"读 {partition} ", text)
        return dest

    async def partition(self, partition, image) -> None:
        if partition not in WRITABLE:
            raise FlashError(f"不能写 {partition}：只写 boot0/1、system0/1")
        image = Path(image)
        if image.stat().st_size > PARTITIONS[partition]:
            raise FlashError(f"{image.name} 比 {partition} 分区大")
        text = await self.run("partition", partition, str(image))
        if "mwrite success" not in text:
            raise self._fail(f"写 {partition} ", text)

    async def bulkcmd(self, command) -> None:
        if not any(p.fullmatch(command) for p in BULKCMDS):
            raise FlashError(f"不发这条命令：{command}")
        text = await self.run("bulkcmd", command, timeout=30)
        if "bulkInReply success" not in text:
            raise self._fail(f"{command} ", text)
