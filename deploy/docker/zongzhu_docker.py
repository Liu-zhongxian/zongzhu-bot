"""宗主后端容器的入口（G21b）：`serve` 运行后端（默认），`setup` 第一次设置。

电脑上的一个文件夹（.env 里的 ZONGZHU_HOME）挂到容器的 /zongzhu，里面三个目录：
    data/      后端配置 .config.yaml，网关页面的设置、固件、唤醒词资源包
    models/    语音识别模型（X-ASR），接音箱时还有唤醒词模型
    private/   Bot Webhook 配置、Bot 写回复的 bot-replies/、音箱 token
镜像里后端的 data/ 和这两个模型目录是指向 /zongzhu 的链接（见 Dockerfile），所以配置里的路径和在 Mac 上一样。

Bot 在电脑上写回复，后端在容器里读：Webhook 配置的 reply_dir 是容器里的路径，bot_reply_dir 是
同一个目录在电脑上的路径（compose 把 ZONGZHU_HOME 原样传进来，Windows 的 C:\\... 也照原样），
后端交给 Bot 的是后者（core/handle/grokBotHandle.py path_for_bot）。

用纯 Python 写（不用 shell 脚本）：Windows 上 git 把换行改成 CRLF 时也能跑。
"""
import argparse
import getpass
import ipaddress
import json
import os
import re
import secrets
import sys
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

HOME = Path("/zongzhu")
REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "xiaozhi-esp32-server" / "main" / "xiaozhi-server"
CONFIG = HOME / "data" / ".config.yaml"
WEBHOOK = HOME / "private" / "grok-bot-webhook.json"
REPLIES = HOME / "private" / "bot-replies"
SPEAKER_TOKEN = HOME / "private" / "open-xiaoai-token.txt"

# 和 web/install-mac.sh 下的同一个模型；文件名和最小字节数（小于它说明没下完或下到错误页）
XASR = "sherpa-onnx-x-asr-zipformer-transducer-zh-en-punct-int8-2026-06-03"
XASR_FILES = {"encoder-epoch-99-avg-1.int8.onnx": 150_000_000, "decoder-epoch-99-avg-1.onnx": 10_000_000,
              "joiner-epoch-99-avg-1.int8.onnx": 2_000_000, "tokens.txt": 50_000, "bpe.model": 100_000}
HF_HOSTS = (os.environ.get("HF_ENDPOINT") or "https://huggingface.co", "https://hf-mirror.com")
# 音箱唤醒词模型：docs/GUIDE.md 的同一个压缩包（约 490 MB），只取 5 个文件（约 120 MB）
KWS = "sherpa-onnx-kws-open-xiaoai"
KWS_ZIP = "https://github.com/coderzc/open-xiaoai-bridge/releases/download/vad-kws-asr-models/models.zip"
KWS_FILES = ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt", "bpe.model")


def say(text):
    print(f"\n\033[1m==> {text}\033[0m", flush=True)


def host_path(*parts) -> str:
    """/zongzhu 下的东西在电脑上的路径（Windows 用反斜杠）"""
    base = os.environ.get("ZONGZHU_HOST_HOME", "").strip()
    if not base:
        sys.exit("没有 ZONGZHU_HOST_HOME：请用 docker compose 运行（它会把 .env 里的 ZONGZHU_HOME 传进来）")
    windows = re.match(r"^[A-Za-z]:[\\/]|^\\\\", base)
    return str((PureWindowsPath if windows else PurePosixPath)(base, *parts))


def write_private(path: Path, text: str):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def download(url, dest: Path, minimum=0):
    import httpx

    part = dest.with_name(dest.name + ".part")
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            done = 0
            with part.open("wb") as f:
                for chunk in response.iter_bytes(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        print(f"\r  {done / 1e6:.0f} / {total / 1e6:.0f} MB", end="", flush=True)
        print()
        if part.stat().st_size < minimum:
            raise OSError(f"只下到 {part.stat().st_size} 字节")
        part.replace(dest)
        return True
    except (OSError, httpx.HTTPError) as e:
        print(f"\n  没下成：{e}")
        part.unlink(missing_ok=True)
        return False


def models(speaker: bool):
    say("下载语音识别模型 X-ASR（约 174 MB，已下载的会跳过）")
    directory = HOME / "models" / XASR
    directory.mkdir(parents=True, exist_ok=True)
    for name, minimum in XASR_FILES.items():
        dest = directory / name
        if dest.is_file() and dest.stat().st_size >= minimum:
            print(f"{name}：已有，跳过")
            continue
        for host in HF_HOSTS:
            print(f"{name} ← {host}")
            if download(f"{host}/csukuangfj2/{XASR}/resolve/main/{name}", dest, minimum):
                break
        else:
            sys.exit(f"模型 {name} 下载失败：检查网络后重新运行 setup（已下载的会跳过）")
    if not speaker:
        return
    directory = HOME / "models" / KWS
    if all((directory / n).is_file() for n in KWS_FILES):
        print("音箱唤醒词模型：已有，跳过")
        return
    say("下载音箱唤醒词模型（压缩包约 490 MB，只留 5 个文件）")
    directory.mkdir(parents=True, exist_ok=True)
    archive = HOME / "models" / "xiaoai-models.zip"
    if not download(KWS_ZIP, archive, 100_000_000):
        sys.exit("唤醒词模型下载失败：检查网络后重新运行 setup")
    with zipfile.ZipFile(archive) as z:
        for name in KWS_FILES:
            (directory / name).write_bytes(z.read(f"models/{name}"))
    archive.unlink()


def webhook(url, token):
    say("设置 Bot Webhook")
    REPLIES.mkdir(parents=True, exist_ok=True)
    if WEBHOOK.exists():
        data = json.loads(WEBHOOK.read_text(encoding="utf-8"))
        print(f"已有 {host_path('private', WEBHOOK.name)}，只更新回复目录")
    else:
        data = json.loads((REPO / "examples" / "grok-bot-webhook.example.json").read_text(encoding="utf-8"))
        if url is None:
            print("后端会把识别出的文字 POST 到你的 Bot。现在不知道可以直接回车，以后再改这个文件。")
            url = input("Bot Webhook 地址（https://…）：").strip()
        if url:
            data["url"] = url
            data["token"] = token if token is not None else getpass.getpass("Bot Webhook token（输入时不显示）：")
    data["reply_dir"] = str(REPLIES)
    data["bot_reply_dir"] = host_path("private", "bot-replies")
    write_private(WEBHOOK, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    if "YOUR_BOT_WEBHOOK_URL" in data.get("url", ""):
        print("还没填 Bot 地址：后端能启动，但说话不会转给 Bot。")


def config(ip, speaker):
    say("生成后端配置")
    if CONFIG.exists():
        print(f"已有 {host_path('data', '.config.yaml')}，保留不变（里面的 IP 有变化请手动改）。")
        return
    text = (REPO / "examples" / "backend.config.yaml").read_text(encoding="utf-8")
    text = (text.replace("//192.168.1.100:", f"//{ip}:")
            .replace("REPLACE_WITH_RANDOM_STRING", secrets.token_hex(32))  # 板子连接用的令牌靠它签名，每台各不相同
            .replace("config_file: ../../../private/grok-bot-webhook.json", f"config_file: {WEBHOOK}"))
    if speaker:
        if not SPEAKER_TOKEN.exists():
            write_private(SPEAKER_TOKEN, secrets.token_urlsafe(32) + "\n")
        text += ("\n# 小米音箱（docker setup 写的）\ngateway:\n  xiaoai:\n    enabled: true\n    port: 4399\n"
                 f"    token_file: {SPEAKER_TOKEN}\n")
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    write_private(CONFIG, text)


def setup(argv):
    parser = argparse.ArgumentParser(prog="setup", description="第一次设置：配置、模型、Bot Webhook")
    parser.add_argument("--ip", help="这台电脑的局域网 IP（板子和音箱连它）")
    parser.add_argument("--webhook-url", help="Bot Webhook 地址；token 用环境变量 ZONGZHU_WEBHOOK_TOKEN 给")
    parser.add_argument("--speaker", choices=("yes", "no"), help="接不接小米音箱")
    args = parser.parse_args(argv)
    host_path()  # 先确认是用 compose 运行的
    for name in ("data", "models", "private"):
        (HOME / name).mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(HOME / "private", 0o700)
    except OSError:
        pass  # Windows 的挂载目录改不了权限

    ip = args.ip
    while not ip:
        print("板子和音箱要连这台电脑的局域网 IP。查法：Windows 运行 ipconfig 看 IPv4 地址；"
              "Linux 运行 hostname -I；Mac 运行 ipconfig getifaddr en0")
        ip = input("这台电脑的局域网 IP：").strip()
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        sys.exit(f"{ip} 不是 IP 地址")
    speaker = args.speaker == "yes" if args.speaker else input("接小米智能音箱 Pro 吗？[y/N] ").strip().lower() == "y"

    webhook(args.webhook_url, os.environ.get("ZONGZHU_WEBHOOK_TOKEN"))
    config(ip, speaker)
    models(speaker)

    say("设置好了")
    print(f"文件都在电脑上的 {host_path()}")
    print("启动：docker compose -f deploy/docker/compose.yaml up -d")
    print(f"网页刷机第 4 步「电脑的地址」填：{ip}（OTA 地址 http://{ip}:8003/xiaozhi/ota/）")
    print(f"网关页面：http://{ip}:8003/gateway")
    if speaker:
        print(f"装音箱 Client 时用这个 token 文件：{host_path('private', SPEAKER_TOKEN.name)}，地址 ws://{ip}:4399")
    print("电脑的 IP 写进了板子和音箱：在路由器里给这台电脑固定一个 IP。")


def serve():
    if not CONFIG.exists():
        print("还没设置：先运行 docker compose -f deploy/docker/compose.yaml run --rm zongzhu setup", flush=True)
        import time
        time.sleep(60)  # 别让 restart: unless-stopped 一直快速重启
        sys.exit(1)
    os.chdir(SERVER)
    os.execvp(sys.executable, [sys.executable, "app.py"])


if __name__ == "__main__":
    command, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("serve", [])
    if command == "setup":
        setup(rest)
    elif command == "serve":
        serve()
    else:
        os.execvp(command, [command, *rest])  # 别的命令照常运行（比如跑测试）
