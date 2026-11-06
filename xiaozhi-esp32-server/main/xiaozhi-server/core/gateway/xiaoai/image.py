"""网关页面刷音箱之前做补丁镜像（G25 ③ 第 2 步）：zongzhu-speaker/README.md 第 2、3 步，由后端做，不碰音箱。

1. 查官方包：小米升级接口（https，照 firmware/ota_query.py，不用登录、不用 SN）按音箱现在的版本给出
   currentInfo 的下载地址、MD5、大小；没有这个版本就报错（先在米家 App 里升到最新）。
2. 下载到 data/xiaoai-flash/（只本人可读），核对大小和 MD5；已有且 MD5 对就不再下。
3. 运行仓库的 firmware/build_image.sh（10-30 刷成功的就是它做的镜像）：解包校验、打 4 个补丁、打包，
   核对只有补丁改的 8 个文件不同、条目数不变、shadow 里的密码串能用密码验证。root 密码经标准输入给它
   （不进命令行和环境变量），只用这一次，不存、不写日志；镜像里只有 md5crypt 密码串。
只在 OH2P 1.62.2 上做过；别的版本能做出镜像、过了全部检查也照做，页面提醒没试过。
"""
import asyncio
import base64
import hashlib
import os
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

from core.gateway.xiaoai.install import REPO

OTA_URL = "https://api.miwifi.com/rs/grayupgrade/v2/OH2P"
OTA_SALT = "8007236f-a2d6-4847-ac83-c49395ad6d65"  # open-xiaoai client-patch/src/ota.ts
MODEL = "OH2P"
TESTED = ("1.62.2",)
WORK = Path("data") / "xiaoai-flash"  # 相对后端目录
BUILD_SCRIPT = REPO / "zongzhu-speaker" / "firmware" / "build_image.sh"
FIRMWARE_HOST = "cdn.cnbj1.fds.api.mi-img.com"
_VERSION = re.compile(r"\d{1,3}(\.\d{1,3}){1,3}")
_FIRMWARE_NAME = re.compile(r"mico_all_[0-9a-f]{6,32}_[\d.]+\.bin")
PATH_EXTRA = "/opt/homebrew/bin:/usr/local/bin"  # 后端不是从终端起的时候 PATH 里可能没有 Homebrew


class ImageError(Exception):
    pass


def check_version(version) -> str:
    version = str(version or "").strip()
    if not _VERSION.fullmatch(version):
        raise ImageError("音箱版本不对（要像 1.62.2，在米家 App → 音箱 → 设置 → 检查更新里看）")
    return version


def check_password(password) -> str:
    password = str(password or "")
    if not password:
        raise ImageError("先填要设的 root 密码")
    if len(password) > 64 or any(c in password for c in "\r\n\0"):
        raise ImageError("root 密码不能超过 64 个字符，也不能有换行")
    return password


def work_dir() -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    WORK.chmod(0o700)
    return WORK


async def query(version) -> dict:
    """{"version", "link", "hash", "size"}：这个版本的官方包"""
    import httpx

    version = check_version(version)
    t = int(time.time() * 1000)
    info = f"channel=release&filterID=&locale=zh_CN&model={MODEL}&time={t}&version={version}&{OTA_SALT}"
    params = {"model": MODEL, "version": version, "channel": "release", "filterID": "", "locale": "zh_CN",
              "time": t, "s": hashlib.md5(base64.b64encode(info.encode())).hexdigest()}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(OTA_URL, params=params)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as e:
        raise ImageError(f"查小米升级接口失败：{type(e).__name__} {e}"[:200]) from None
    current = (body.get("data") or {}).get("currentInfo") or {}
    link, digest, size = current.get("link") or "", str(current.get("hash") or "").lower(), current.get("size")
    if not link:
        raise ImageError(f"小米没有 {version} 的官方包：先在米家 App 里把音箱升到最新，再填新的版本")
    url = urlparse(link)
    if url.scheme != "https" or url.hostname != FIRMWARE_HOST or not _FIRMWARE_NAME.fullmatch(Path(url.path).name) \
            or not re.fullmatch(r"[0-9a-f]{32}", digest) or not isinstance(size, int):
        raise ImageError(f"小米返回的官方包信息不像预期：{link}")
    return {"version": version, "link": link, "hash": digest, "size": size}


def _md5(path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(info, progress=None) -> Path:
    """下载官方包（阻塞，放线程里跑）；progress(已下, 总共)"""
    import httpx

    path = work_dir() / Path(urlparse(info["link"]).path).name
    if path.is_file() and path.stat().st_size == info["size"] and _md5(path) == info["hash"]:
        return path
    part = path.with_name(path.name + ".part")
    try:
        with httpx.stream("GET", info["link"], follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            done = 0
            with part.open("wb") as f:
                for chunk in response.iter_bytes(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, info["size"])
        if part.stat().st_size != info["size"] or _md5(part) != info["hash"]:
            raise ImageError("下载的官方包大小或 MD5 和小米给的不一样，没有用它")
        part.replace(path)
    except httpx.HTTPError as e:
        raise ImageError(f"下载官方包失败：{type(e).__name__} {e}"[:200]) from None
    finally:
        part.unlink(missing_ok=True)
    return path


async def build(firmware, password, on_line=None) -> dict:
    """运行 build_image.sh；成功返回 {"dir", "rootfs", "kernel", "size", "md5"}，失败删掉半成品"""
    password = check_password(password)
    out = work_dir() / time.strftime("build-%Y%m%d-%H%M%S")
    env = {k: v for k, v in os.environ.items() if k != "SPEAKER_ROOT_PASSWORD"}
    env["PATH"] = env.get("PATH", "/usr/bin:/bin") + ":" + PATH_EXTRA
    proc = await asyncio.create_subprocess_exec(
        "bash", str(BUILD_SCRIPT), str(firmware), str(out), env=env, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
    lines = []
    try:
        proc.stdin.write(f"{password}\n{password}\n".encode())  # 脚本问两次
        await proc.stdin.drain()
        proc.stdin.close()
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            if not line:  # 输密码的提示：标准输入不是终端时 bash 不显示，只剩 echo 的空行
                continue
            lines.append(line)
            if on_line:
                on_line(line)
        await proc.wait()
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    if proc.returncode != 0:
        shutil.rmtree(out, ignore_errors=True)
        raise ImageError("做镜像没成功：" + (" / ".join(lines[-3:]) or f"退出码 {proc.returncode}")[:300])
    rootfs, kernel = out / "root-patched.squashfs", out / "boot.img.encrypt"
    for path in out.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)  # 镜像里有密码串
    out.chmod(0o700)
    return {"dir": out, "rootfs": rootfs, "kernel": kernel, "size": rootfs.stat().st_size,
            "md5": {"rootfs": _md5(rootfs), "kernel": _md5(kernel)}}
