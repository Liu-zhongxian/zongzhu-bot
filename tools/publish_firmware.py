#!/usr/bin/env python3
"""G18e：项目主人发布固件，用这个项目的每个后端都会拿到（验签后放进 data/bin，板子开机自己更新）。

只有有私钥的人能发布。先编译（内置的后端地址必须是占位地址，不能是你自己的）：

    tools/build_firmware.py szp --version 2.5.2.11 --ota-url http://set-your-backend.invalid/xiaozhi/ota/ --idf ...
    tools/publish_firmware.py 2.5.2.11 build-output/zongzhu-szp-2.5.2.11 [更多板子的包]          # 只生成，检查
    tools/publish_firmware.py 2.5.2.11 build-output/zongzhu-szp-2.5.2.11 --publish                # 发布到 GitHub

生成的东西在 build-output/release-<版本>/：每块板子一个 .bin、manifest.json、manifest.sig。
--publish 会先列出要发的内容，等你输入 publish 才用 gh 发布（tag v<版本>）。发布以后，所有开着自动更新的
后端都会在一小时内拿到它，对应变体的板子下次开机就更新，所以先在自己的板子上试过再发。
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "xiaozhi-esp32-server/main/xiaozhi-server"))
from core.gateway import firmware, releases  # noqa: E402

GITHUB_REPO = "Liu-zhongxian/zongzhu-bot"
DEFAULT_KEY = REPO.parent.parent / "private" / "zongzhu-firmware-signing.key"


def board_entry(package: Path, version: str):
    """(variant, entry, bin path) for one build-output package; exits on anything wrong."""
    info = json.loads((package / "build-info.json").read_text(encoding="utf-8"))
    variant = info.get("variant", "")
    if info.get("ota_url") != releases.PLACEHOLDER_OTA:
        sys.exit(f"{package.name}：内置后端地址是 {info.get('ota_url')}，发布的固件必须用占位地址 "
                 f"{releases.PLACEHOLDER_OTA} 编（--ota-url），不然别人的板子可能连到这个地址")
    if info.get("version") != version:
        sys.exit(f"{package.name}：版本是 {info.get('version')}，不是 {version}")
    binary = package / "xiaozhi.bin"
    image = binary.read_bytes()
    desc = firmware.describe(image)
    board_type = next((t for t in ("lichuang-dev", "esp32-s3-touch-amoled-1.75", "m5stack-stopwatch")
                       if variant.startswith(t)), "")
    if desc["version"] != version or desc["project"] != "xiaozhi" or not board_type:
        sys.exit(f"{package.name}：固件读出来是 {desc['project']} {desc['version']}，变体 {variant}，对不上")
    if (variant.encode() + b"\0") not in image:
        sys.exit(f"{package.name}：固件里没有变体名 {variant}")
    name = f"zongzhu-{variant}-{version}.bin"
    return variant, {"type": board_type, "file": name, "sha256": hashlib.sha256(image).hexdigest(),
                     "size": len(image)}, binary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version")
    parser.add_argument("packages", nargs="+", type=Path, help="build-output/zongzhu-<板子>-<版本> 目录")
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY, help=f"私钥（默认 {DEFAULT_KEY}）")
    parser.add_argument("--notes", default="", help="发布说明（这一版改了什么）")
    parser.add_argument("--publish", action="store_true", help="生成后发布到 GitHub（会先让你确认）")
    args = parser.parse_args()

    boards, binaries = {}, {}
    for package in args.packages:
        variant, entry, binary = board_entry(package, args.version)
        if variant in boards:
            sys.exit(f"{variant} 给了两个包")
        boards[variant], binaries[variant] = entry, binary
    manifest = releases.make_manifest(args.version, boards, time.time())
    signature = releases.sign(manifest, args.key.read_text(encoding="utf-8"))
    releases.verify(manifest, signature)  # 私钥和代码里的公钥是一对，不然发出去谁都不收

    out = REPO / "build-output" / f"release-{args.version}"
    out.mkdir(parents=True, exist_ok=True)
    for variant, entry in boards.items():
        (out / entry["file"]).write_bytes(binaries[variant].read_bytes())
    (out / releases.MANIFEST).write_bytes(manifest)
    (out / releases.SIGNATURE).write_bytes(signature)
    print(f"生成好了：{out}")
    for variant, entry in boards.items():
        print(f"  {variant}：{entry['file']}（{entry['size'] / 1024 / 1024:.1f} MB）")
    if not args.publish:
        print("没有发布（加 --publish 才发布）。")
        return

    print(f"\n要发布到 {GITHUB_REPO}，tag v{args.version}。发布以后，所有开着自动更新的后端都会在一小时内拿到，"
          "这些变体的板子下次开机就更新。")
    if input("确定发布就输入 publish：").strip() != "publish":
        sys.exit("没有发布")
    notes = (args.notes or f"宗主固件 {args.version}") + "\n\n后端会自动验签后更新对应的板子（G18e）。"
    files = [str(out / e["file"]) for e in boards.values()] + [str(out / releases.MANIFEST), str(out / releases.SIGNATURE)]
    subprocess.run(["gh", "release", "create", f"v{args.version}", *files, "--repo", GITHUB_REPO,
                    "--title", f"宗主固件 {args.version}", "--notes", notes], check=True)
    print("发布了。")


if __name__ == "__main__":
    main()
