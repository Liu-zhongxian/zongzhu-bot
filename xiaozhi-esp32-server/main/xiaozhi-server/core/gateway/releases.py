"""G18e：项目主人发布的固件，用这个项目的每个后端都能拿到（2026-11-03 你定）。

只有项目主人能发布：tools/publish_firmware.py 用主人本机的私钥（不在仓库里）给发布清单签名，
发布到 GitHub Releases；每个后端用下面写死的公钥验签，验不过的一律不收。清单里每份固件写明
给哪个变体（板子上报的 board.name，如 lichuang-dev-zongzhu，能分清 1.75 和 1.75C）、SHA-256 和大小。

清单（manifest.json，签名就是对这个文件的原始字节签的，manifest.sig 是 base64 的 Ed25519 签名）：
    {"format": 1, "project": "zongzhu", "version": "2.5.2.11", "published": <秒>,
     "boards": {"lichuang-dev-zongzhu": {"type": "lichuang-dev", "file": "<资源名>.bin",
                                          "sha256": "...", "size": 2842864}, ...}}

发布的固件内置的后端地址是 PLACEHOLDER_OTA：板子都把自己后端的地址存在板子里（刷机网页、配网页面
都会存），更新以后照旧连自己的后端；万一有板子没存，也只会连不上，不会去连主人的后端。
"""
import base64
import json
import re

# 项目主人的发布公钥（私钥在主人电脑的 小志/private/zongzhu-firmware-signing.key，2026-11-03 生成）
PUBLIC_KEY = "4vAEzoa6O9/07qNCej7FDRhEendm0ENj5yHsbyK9RvA="
PLACEHOLDER_OTA = "http://set-your-backend.invalid/xiaozhi/ota/"
MANIFEST, SIGNATURE = "manifest.json", "manifest.sig"
_VARIANT = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}$")
_VERSION = re.compile(r"^\d+(\.\d+){1,3}$")
_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.bin$")


class ReleaseError(Exception):
    pass


def make_manifest(version, boards, published) -> bytes:
    """boards: {variant: {"type", "file", "sha256", "size"}}"""
    return json.dumps({"format": 1, "project": "zongzhu", "version": version, "published": int(published),
                       "boards": boards}, ensure_ascii=False, indent=2, sort_keys=True).encode()


def sign(manifest: bytes, private_key_b64: str) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64.strip()))
    return base64.b64encode(key.sign(manifest)) + b"\n"


def verify(manifest: bytes, signature: bytes, public_key: str = None) -> dict:
    """The manifest when the owner's key signed exactly these bytes and it is well formed; ReleaseError otherwise."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key or PUBLIC_KEY))
        key.verify(base64.b64decode(signature.strip(), validate=True), manifest)
    except (InvalidSignature, ValueError) as e:
        raise ReleaseError("签名不对：不是项目主人发布的，不收") from e
    try:
        data = json.loads(manifest)
    except ValueError as e:
        raise ReleaseError("发布清单格式不对") from e
    if data.get("format") != 1 or data.get("project") != "zongzhu" or not _VERSION.match(str(data.get("version"))):
        raise ReleaseError("发布清单格式不对")
    boards = data.get("boards")
    if not isinstance(boards, dict):
        raise ReleaseError("发布清单格式不对")
    for variant, entry in boards.items():
        if (not _VARIANT.match(variant) or not isinstance(entry, dict) or not _FILE.match(str(entry.get("file")))
                or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))) or not isinstance(entry.get("size"), int)
                or not _VARIANT.match(str(entry.get("type")))):
            raise ReleaseError(f"发布清单里 {variant} 那一项格式不对")
    return data


# ---- 每个后端：查项目主人发布的固件，验过的放进 data/bin（板子开机自己更新）----

DEFAULT_REPO = "Liu-zhongxian/zongzhu-bot"
CHECK_SECONDS = 3600
FIRST_CHECK_SECONDS = 60
MANIFEST_MAX = 64 * 1024
state = {"checked_at": None, "result": "还没查过", "version": None}


def source(config):
    """GitHub Releases 的地址；gateway.firmware_releases: false 时不查（自己改了固件、不想要主人发布的）。"""
    gateway = config.get("gateway") or {}
    repo = gateway.get("firmware_releases", DEFAULT_REPO)
    if repo is False or repo == "":
        return None
    return gateway.get("firmware_releases_api") or f"https://api.github.com/repos/{repo}/releases?per_page=10"


def auto_update() -> bool:
    from core.gateway import settings

    return settings.get("auto_firmware", True) is not False


async def _get(client, url, limit):
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data += chunk
            if len(data) > limit:
                raise ReleaseError("下载的文件比清单里写的大")
        return bytes(data)


async def check(config, transport=None) -> str:
    """查一次：最新的签名发布里有没有比这台后端的板子新的固件，有就验过放进 data/bin。返回说明。"""
    import hashlib

    import httpx

    from core.gateway import firmware, status

    url = source(config)
    if url is None:
        return "没开（gateway.firmware_releases: false）"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "zongzhu-backend"}
    async with httpx.AsyncClient(timeout=60, follow_redirects=True, transport=transport, headers=headers) as client:
        listing = json.loads(await _get(client, url, 1024 * 1024))
        best = None
        for release in listing if isinstance(listing, list) else []:
            if not isinstance(release, dict) or release.get("draft"):
                continue
            assets = {a.get("name"): a.get("browser_download_url") for a in release.get("assets") or []
                      if isinstance(a, dict)}
            if MANIFEST not in assets or SIGNATURE not in assets:
                continue
            try:
                data = verify(await _get(client, assets[MANIFEST], MANIFEST_MAX),
                              await _get(client, assets[SIGNATURE], 1024))
            except ReleaseError:
                continue  # 签名不对的发布（不是主人发的）跳过，看下一个
            if best is None or firmware._version(data["version"]) > firmware._version(best[0]["version"]):
                best = (data, assets)
        if best is None:
            return "项目还没有发布过签名的固件"
        data, assets = best
        version, got, skipped = data["version"], [], []
        for variant, entry in data["boards"].items():
            mine = [b for b in list(status._boards.values()) if b.get("name") == variant]
            if not mine or not any(firmware._version(version) > firmware._version(b.get("version")) for b in mine):
                continue
            if (firmware.BIN_DIR / f"{variant}_{version}.bin").exists():
                got.append(variant)
                continue
            if entry["file"] not in assets:
                skipped.append(f"{variant}（发布里少了文件）")
                continue
            image = await _get(client, assets[entry["file"]], entry["size"])
            if len(image) != entry["size"] or hashlib.sha256(image).hexdigest() != entry["sha256"]:
                skipped.append(f"{variant}（下载的文件和清单对不上）")
                continue
            try:
                info = firmware.check(image, mine[0])
                if info["version"] != version:
                    raise firmware.FirmwareError(f"固件里的版本是 {info['version']}")
            except firmware.FirmwareError as e:
                skipped.append(f"{variant}（{e}）")
                continue
            firmware.save(image, variant, version)
            got.append(variant)
    if not got and not skipped:
        return f"项目最新发布 {version}，这里的板子不用更新"
    return (f"项目发布 {version}：" + (f"{'、'.join(got)} 放好了，板子下次开机更新" if got else "")
            + ("；" if got and skipped else "") + (f"没收：{'、'.join(skipped)}" if skipped else ""))


async def run_check(config) -> str:
    import time

    try:
        result = await check(config)
    except ReleaseError as e:
        result = f"没收：{e}"
    except Exception as e:  # 网络不通、GitHub 限流这些：下次再查
        result = f"查不了：{type(e).__name__}"
    state.update(checked_at=time.time(), result=result)
    return result


async def watch(config):
    """后端启动后一分钟查一次，之后每小时一次；关了自动更新就不查。"""
    import asyncio

    await asyncio.sleep(FIRST_CHECK_SECONDS)
    while True:
        if source(config) is not None and auto_update():
            await run_check(config)
        await asyncio.sleep(CHECK_SECONDS)
