"""网关页面接入小米音箱（G25 ① 第 2 步）：代替 GUIDE"接入小米智能音箱 Pro"的第 6–8 步。

页面上的操作（经 /gateway/api/control，和别的设置一样要口令）：
- speaker_enable：打开音箱接入。token 沿用配置里 token_file 的，没配就生成到 data/xiaoai_token.txt；
  唤醒词模型没有就在后台下载（约 490 MB，只留 5 个文件），下好再开 4399 端口，不用重启后端
- speaker_model_download：下载失败后重试
- speaker_install：{"host": 音箱 IP, "password": root 密码, "server": 后端地址（可不填）}，在后台经 SSH 装 Client
  （install.py），页面看进度；密码只用这一次，不存、不写日志
- speaker_forget_key：{"host": 音箱 IP}，重新刷过机后忘记旧的 SSH 主机密钥
view() 放进 /gateway/api/status 的 "speaker_setup"。
"""
import asyncio
import ipaddress
import os
import re
import secrets
import socket
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from config.logger import setup_logging
from core.gateway import settings as page_settings
from core.gateway.control import ControlError
from core.gateway.xiaoai import control as speaker_control, flash, flash_job, install, server as speaker_server, wake

TAG = __name__
logger = setup_logging()

ACTIONS = {"speaker_enable", "speaker_model_download", "speaker_install", "speaker_forget_key"}
# 和 deploy/docker/zongzhu_docker.py、docs/GUIDE.md 用的同一个压缩包
KWS_ZIP = "https://github.com/coderzc/open-xiaoai-bridge/releases/download/vad-kws-asr-models/models.zip"
KWS_FILES = ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt", "bpe.model")
KWS_MINIMUM = 100_000_000  # 小于它说明没下完或下到了错误页
_HOST = re.compile(r"^[A-Za-z0-9.\-]{1,253}$")

# 后台任务的进度（页面轮询 /gateway/api/status 看）
model_job = {"state": "idle", "done": 0, "total": 0, "error": ""}  # idle / downloading / extracting / done / error
install_job = {"state": "idle", "host": "", "steps": [], "error": "", "result": None}  # idle / running / done / error
_tasks = set()


def _spawn(coro):
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def model_dir(config) -> Path:
    # Docker 里 models/sherpa-onnx-kws-open-xiaoai 是指向 /zongzhu/models 的链接，目标可能还不存在：按目标建
    return Path(speaker_server.settings(config).get("kws_model_dir") or wake.DEFAULT_MODEL_DIR).resolve()


def model_ready(config) -> bool:
    return all((model_dir(config) / name).is_file() for name in KWS_FILES)


def ensure_token(config) -> str:
    """音箱和后端共用的 token：配置的 token_file 有就沿用；没配就生成一个放 data/xiaoai_token.txt（只本人可读）"""
    xiaoai = speaker_server.settings(config)
    token = speaker_server.read_token(xiaoai)
    if token:
        return token
    if str(xiaoai.get("token_file") or "").strip():
        raise ControlError(f"配置里的 token_file 读不到：{speaker_server.token_path(xiaoai)}")
    path = speaker_server.DEFAULT_TOKEN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    return token


def in_docker() -> bool:
    return Path("/.dockerenv").exists() or bool(os.environ.get("ZONGZHU_HOST_HOME"))


def _configured_host(config):
    """配置里板子连的地址（server.websocket）里的 IP：Docker 里只能靠它，容器自己的 IP 音箱连不到"""
    host = urlparse(str((config.get("server") or {}).get("websocket") or "")).hostname or ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    return None if ip.is_loopback or ip.is_unspecified or host == "192.168.1.100" else host  # 后者是示例里的


def _route_ip(target):
    """连 target 要走的那块网卡的 IP（UDP connect 不发包）"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((target, 9))
            return s.getsockname()[0]
    except OSError:
        return None


def server_url(config, speaker_host="") -> str:
    """音箱要连的后端地址 ws://<这台电脑的局域网 IP>:<端口>"""
    port = int(speaker_server.settings(config).get("port") or speaker_server.DEFAULT_PORT)
    host = None
    if not in_docker():
        host = _route_ip(speaker_host) if speaker_host else None
        host = host or _configured_host(config) or _route_ip("8.8.8.8")
    else:
        host = _configured_host(config)
    return f"ws://{host}:{port}" if host else ""


def view(config) -> dict:
    xiaoai = speaker_server.settings(config)
    return {
        "enabled": speaker_server.enabled(config),
        "token": bool(speaker_server.read_token(xiaoai)),
        "listening": bool(speaker_control.server and speaker_control.server.ready.is_set()),
        "model": "done" if model_ready(config) else model_job["state"], "model_job": dict(model_job),
        "server": server_url(config, install_job["host"]),
        "docker": in_docker(),
        "install": dict(install_job, steps=list(install_job["steps"])),
        "known_hosts": sorted(install._known()),
    }


async def _download_model(config):
    import httpx

    directory = model_dir(config)
    archive = directory.parent / "xiaoai-models.zip.part"
    model_job.update(state="downloading", done=0, total=0, error="")
    try:
        directory.mkdir(parents=True, exist_ok=True)

        def fetch():
            with httpx.stream("GET", KWS_ZIP, follow_redirects=True, timeout=60) as response:
                response.raise_for_status()
                model_job["total"] = int(response.headers.get("content-length") or 0)
                with archive.open("wb") as f:
                    for chunk in response.iter_bytes(1 << 20):
                        f.write(chunk)
                        model_job["done"] += len(chunk)
            if archive.stat().st_size < KWS_MINIMUM:
                raise OSError(f"只下到 {archive.stat().st_size} 字节")

        def extract():
            with zipfile.ZipFile(archive) as z:
                for name in KWS_FILES:
                    part = directory / (name + ".part")
                    part.write_bytes(z.read(f"models/{name}"))
                    part.replace(directory / name)

        await asyncio.to_thread(fetch)
        model_job["state"] = "extracting"
        await asyncio.to_thread(extract)
        model_job["state"] = "done"
        logger.bind(tag=TAG).info(f"音箱唤醒词模型下好了：{directory}")
    except Exception as e:
        model_job.update(state="error", error=f"{type(e).__name__} {e}"[:200])
        logger.bind(tag=TAG).error(f"音箱唤醒词模型下载失败：{model_job['error']}")
        return
    finally:
        archive.unlink(missing_ok=True)
    server = speaker_control.server
    if server and server.ready.is_set():
        await server.reload()  # 端口早开了（配置里开的）、当时没模型：现在认唤醒词
    elif server and speaker_server.enabled(config):
        server.turn_on()


def start_model_download(config) -> bool:
    if model_ready(config) or model_job["state"] in ("downloading", "extracting"):
        return False
    _spawn(_download_model(config))
    return True


def enable(config) -> dict:
    ensure_token(config)
    page_settings.put("speaker_enabled", True)
    if not model_ready(config):
        start_model_download(config)
        return {"message": "音箱接入打开了。正在下载唤醒词模型（约 490 MB），下好就开始等音箱连接。"}
    if speaker_control.server:
        speaker_control.server.turn_on()
    return {"message": "音箱接入打开了，在等音箱连接。"}


async def _install(config, host, password, url):
    steps = install_job["steps"]
    install_job.update(state="running", host=host, error="", result=None)
    steps.clear()
    try:
        client = await asyncio.to_thread(install.client_bytes)
        init_script = await asyncio.to_thread(install.init_script)
        steps.append("连接音箱")
        conn = await install.connect(host, password)
        async with conn:
            install_job["result"] = await install.install(conn, url, ensure_token(config), client, init_script,
                                                          steps.append)
        install_job["state"] = "done"
        logger.bind(tag=TAG).info(f"网关页面给音箱装好了 Client：{host} {install_job['result']}")
    except (install.InstallError, ControlError) as e:
        install_job.update(state="error", error=str(e))
        logger.bind(tag=TAG).warning(f"网关页面装音箱 Client 没成：{host} {e}")
    except Exception as e:
        install_job.update(state="error", error=f"出错了：{type(e).__name__} {e}"[:200])
        logger.bind(tag=TAG).error(f"网关页面装音箱 Client 出错：{host} {type(e).__name__} {e}")


def _host(value) -> str:
    host = str((value or {}).get("host") or "").strip() if isinstance(value, dict) else ""
    if not _HOST.match(host):
        raise ControlError("音箱 IP 不对")
    return host


async def act(config, action, value) -> dict:
    if action == "speaker_enable":
        return enable(config)
    if action == "speaker_model_download":
        if model_ready(config):
            return {"message": "唤醒词模型已经有了。"}
        if not start_model_download(config):
            return {"message": "唤醒词模型正在下载。"}
        return {"message": "开始下载唤醒词模型（约 490 MB）。"}
    host = _host(value)
    if action == "speaker_forget_key":
        if not install.forget_host(host):
            return {"message": f"没记过 {host} 的密钥。"}
        return {"message": f"忘记了 {host} 的旧密钥，下次连接时记下新的。"}
    if install_job["state"] == "running":
        raise ControlError("正在装，等这次装完")
    password = str(value.get("password") or "")
    if not password:
        raise ControlError("先填音箱的 root 密码（刷补丁固件时设的）")
    url = str(value.get("server") or "").strip() or server_url(config, host)
    if not url:
        raise ControlError("算不出后端地址：请填 ws://<这台电脑的局域网 IP>:4399")
    try:
        install.check_server_url(url)
    except install.InstallError as e:
        raise ControlError(str(e)) from None
    if flash_job.job["state"] == "running":
        raise ControlError("上面正在刷补丁固件：等它做完，拔掉音箱电源再插上、等小爱开机出声后再装")
    if await asyncio.to_thread(flash.in_burn_mode):
        raise ControlError("音箱还停在刷机模式（这台电脑的 USB 上能看到它），连不上：拔掉音箱电源，等 3 秒再插上，"
                           "等小爱开机出声（约 1 分钟）后再点「装到音箱上」")
    enable(config)  # 装完音箱就来连，先把接入打开
    install_job.update(state="running", host=host, error="", result=None, steps=[])
    _spawn(_install(config, host, password, url))
    return {"message": f"开始给 {host} 装 Client，后端地址 {url}。"}
