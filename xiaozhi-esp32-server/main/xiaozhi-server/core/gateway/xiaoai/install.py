"""网关页面装 / 更新音箱上的 Client（G25 ①）：和 zongzhu-speaker/client/install_client.sh 做的一样，由后端经 SSH 做。

页面填音箱 IP 和 root 密码（刷补丁固件时设的），后端：
1. SSH 连上音箱（老 dropbear 要 ssh-rsa）。第一次连记下音箱的主机密钥（data/xiaoai_known_hosts.json），
   以后密钥变了就拒绝，和脚本里 StrictHostKeyChecking=accept-new 一样；重新刷过机要先在页面上"忘记旧密钥"。
2. 看型号和版本：只在 OH2P 上做过，别的型号不装。
3. 写入 /data/open-xiaoai/ 的 client、server.txt、token.txt 和开机脚本 /data/init.sh（先写临时文件再改名，
   Client 正在跑时直接覆盖会报 "Text file busy"）。
4. 核对 Client 的 SHA-256 和开机脚本的语法，再启动（开机脚本在跑就只停 Client，它 5 秒后用新的重启）。
密码只用这一次，不存、不写日志。
"""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[6]
CLIENT_SHA256 = "ec2a78a80d3ea71b8df584526a332b1872fc65aecd15f89aaee7b96ccb7101bd"  # build_client.sh 在 Mac 上编出来的
CLIENT_FILE = REPO / "zongzhu-speaker" / "client" / "bin" / "client"
INIT_FILE = REPO / "zongzhu-speaker" / "client" / "init.sh"
KNOWN_HOSTS = Path("data") / "xiaoai_known_hosts.json"  # 相对后端目录，和 gateway_settings.json 一样
MODELS = ("OH2P",)
WORK = "/data/open-xiaoai"
SSH_TIMEOUT = 15


class InstallError(Exception):
    pass


def client_bytes(path=None) -> bytes:
    """仓库里编好的 Client；SHA-256 不对就不用（被改过或没下完整）"""
    path = Path(path or CLIENT_FILE)
    try:
        data = path.read_bytes()
    except OSError:
        raise InstallError(f"找不到 Client 程序：{path}") from None
    if hashlib.sha256(data).hexdigest() != CLIENT_SHA256:
        raise InstallError(f"Client 程序的校验值不对：{path}")
    return data


def check_server_url(url: str) -> str:
    url = (url or "").strip()
    if not re.fullmatch(r"ws://[A-Za-z0-9.\-]+:\d{1,5}/?", url):
        raise InstallError(f"后端地址不对：{url}（要像 ws://192.168.1.10:4399）")
    return url


def parse_version(text: str) -> dict:
    """/usr/share/mico/version 里的 "\toption ROM '1.62.2'" -> {"rom": "1.62.2", ...}"""
    info = {}
    for key, value in re.findall(r"option\s+(ROM|HARDWARE|CHANNEL)\s+'([^']*)'", text or ""):
        info[key.lower()] = value
    return info


# 主机密钥：{ip: "ssh-rsa AAAA..."}
def _known() -> dict:
    try:
        data = json.loads(KNOWN_HOSTS.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_known(data: dict):
    KNOWN_HOSTS.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=KNOWN_HOSTS.parent, prefix=".xiaoai_known_hosts.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, KNOWN_HOSTS)


def forget_host(host: str) -> bool:
    data = _known()
    if data.pop(host, None) is None:
        return False
    _save_known(data)
    return True


async def connect(host: str, password: str, port: int = 22):
    """SSH 连上音箱（root + 密码）。第一次记下主机密钥，以后只认它"""
    import asyncssh

    known = _known()
    saved = known.get(host)
    seen = {}

    class Client(asyncssh.SSHClient):
        def validate_host_public_key(self, host_, addr, port, key):
            if saved:  # 记过的密钥在 known_hosts 里，走到这里说明密钥变了
                return False
            seen["key"] = key.export_public_key("openssh").decode().strip()
            return True

    trusted = [asyncssh.import_public_key(saved)] if saved else []
    try:
        conn, _ = await asyncssh.create_connection(
            Client, host, port, username="root", password=password, known_hosts=(trusted, [], []),
            server_host_key_algs=["ssh-rsa", "rsa-sha2-256", "rsa-sha2-512", "ssh-ed25519",
                                  "ecdsa-sha2-nistp256"],
            client_keys=None, agent_path=None, preferred_auth="password", connect_timeout=SSH_TIMEOUT)
    except asyncssh.PermissionDenied:
        raise InstallError("root 密码不对") from None
    except asyncssh.HostKeyNotVerifiable:
        raise InstallError("音箱的 SSH 主机密钥和上次不一样：重新刷过机的话，先点「忘记旧密钥」再装；"
                           "没刷过机就别继续，可能连到了别的设备") from None
    except (OSError, asyncssh.Error, TimeoutError) as e:
        raise InstallError(f"连不上音箱的 SSH（{host}:{port}）：{type(e).__name__} {e}") from None
    if "key" in seen:
        known[host] = seen["key"]
        _save_known(known)
    return conn


async def _run(conn, command, data=None, check=True):
    # 没有要传的也送一个空输入：stdin 关上，读 stdin 的命令不会一直等
    result = await conn.run(command, input=b"" if data is None else data, encoding=None, check=False, timeout=60)
    out = (result.stdout or b"").decode(errors="replace")
    err = (result.stderr or b"").decode(errors="replace")
    if check and result.exit_status != 0:
        raise InstallError(f"音箱上执行失败（{command.split()[0]}）：{(err or out).strip()[:120]}")
    return out


async def install(conn, server_url: str, token: str, client: bytes, init_script: str, step=lambda text: None) -> dict:
    """在连好的音箱上装 Client；step(文字) 报进度。返回 {"model", "rom", "boot", "restarted"}"""
    server_url = check_server_url(server_url)
    token = (token or "").strip()
    if not token or any(c.isspace() for c in token):
        raise InstallError("token 不对")
    step("看音箱的型号和版本")
    version = parse_version(await _run(conn, "cat /usr/share/mico/version"))
    model = version.get("hardware", "")
    if model not in MODELS:
        raise InstallError(f"这台音箱的型号是 {model or '读不到'}：只在小米智能音箱 Pro（OH2P）上做过，不装")
    boot = (await _run(conn, "fw_env -g boot_part", check=False)).strip()

    step("写入 Client 和开机脚本")
    await _run(conn, f"mkdir -p {WORK}")
    await _run(conn, f"cat > {WORK}/client.new && chmod 755 {WORK}/client.new && mv {WORK}/client.new {WORK}/client",
               client)
    await _run(conn, f"cat > {WORK}/server.txt", (server_url + "\n").encode())
    await _run(conn, f"umask 077; cat > {WORK}/token.txt; chmod 600 {WORK}/token.txt", (token + "\n").encode())
    await _run(conn, "cat > /data/init.sh.new && chmod 755 /data/init.sh.new && mv /data/init.sh.new /data/init.sh",
               init_script.encode())

    step("核对")
    remote = (await _run(conn, f"sha256sum {WORK}/client")).split()[:1]
    if remote != [hashlib.sha256(client).hexdigest()]:
        raise InstallError("传到音箱上的 Client 和电脑上的不一样，请重试")
    await _run(conn, "sh -n /data/init.sh")
    if (await _run(conn, f"cat {WORK}/server.txt")).strip() != server_url:
        raise InstallError("音箱上的后端地址没写对，请重试")

    step("启动")
    running = await _run(conn, "ps | grep -v grep | grep -c 'sh /data/init.sh'", check=False)
    restarted = running.strip() not in ("", "0")
    if restarted:
        await _run(conn, "killall client", check=False)  # 开机脚本 5 秒后用新的重启
    else:
        await _run(conn, "(sh /data/init.sh >/dev/null 2>&1 &)", check=False)  # 第一次装：约 20 秒后连后端
    # 页面上"暂停宗主"（G25 ②）留下的 disabled 不动：开机脚本看到它就不启动 Client，告诉页面
    disabled = (await _run(conn, f"test -f {WORK}/disabled && echo yes", check=False)).strip() == "yes"
    return {"model": model, "rom": version.get("rom", ""), "boot": boot, "restarted": restarted, "disabled": disabled}


def init_script(path=None) -> str:
    try:
        return Path(path or INIT_FILE).read_text(encoding="utf-8")
    except OSError:
        raise InstallError(f"找不到音箱的开机脚本：{path or INIT_FILE}") from None
