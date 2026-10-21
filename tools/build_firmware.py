#!/usr/bin/env python3
"""Build Zongzhu firmware with the OTA address built in, so Wi-Fi setup only needs Wi-Fi.

The OTA address is only a default: an address saved on the board (from the
config page) still wins. By default it points at this Mac by its Bonjour name
(<LocalHostName>.local), which keeps working when the Mac's LAN IP changes.

Examples:
  tools/build_firmware.py szp                      # OTA = http://<this Mac>.local:8003/xiaozhi/ota/
  tools/build_firmware.py szp --flash PORT --erase # first install: wipe, then write
  tools/build_firmware.py 1.75c --ota-url https://zongzhu.example.com/xiaozhi/ota/

ESP-IDF 6.0.1+ is required: pass --idf (and --idf-tools if the tools are not in
~/.espressif) or set IDF_PATH / IDF_TOOLS_PATH.
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "xiaozhi-esp32"

BOARDS = {
    "szp": ("lckfb/szpi-esp32s3", "lichuang-dev-zongzhu"),
    "1.75c": ("waveshare/esp32-s3-touch-amoled-1.75", "esp32-s3-touch-amoled-1.75c"),
    "stopwatch": ("m5stack/stopwatch", "m5stack-stopwatch-zongzhu"),  # not yet run on a board
}
TEMP_CONFIG = "config.zongzhu-ota.json"


def mac_ota_url():
    name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True,
                          check=True).stdout.strip()
    return f"http://{name}.local:8003/xiaozhi/ota/"


def check_url(url):
    if not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d+)?/[A-Za-z0-9._~/-]*", url):
        sys.exit(f"Unsupported OTA URL: {url!r}")
    return url


def sync_source(build_root):
    # ESP-IDF cannot build from a path containing non-ASCII characters.
    if not str(build_root).isascii():
        sys.exit(f"Build directory must be an ASCII path: {build_root}")
    build_root.mkdir(parents=True, exist_ok=True)
    if not (build_root / "CMakeLists.txt").exists():
        shutil.copytree(SOURCE, build_root, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("build", ".git"))
    for sub in ("main", "scripts"):
        subprocess.run(["rsync", "-a", "--delete", "--exclude", "assets/lang_config.h",
                        "--exclude", TEMP_CONFIG, f"{SOURCE / sub}/", f"{build_root / sub}/"], check=True)


def write_temp_config(build_root, board_dir, variant, url):
    board = build_root / "main" / "boards" / board_dir
    config = json.loads((board / "config.json").read_text(encoding="utf-8"))
    builds = [b for b in config["builds"] if b["name"] == variant]
    if len(builds) != 1:
        sys.exit(f"Variant {variant} not found in {board_dir}/config.json")
    config["builds"] = builds
    builds[0]["sdkconfig_append"] = builds[0].get("sdkconfig_append", []) + [f'CONFIG_OTA_URL="{url}"']
    (board / TEMP_CONFIG).write_text(json.dumps(config, ensure_ascii=False, indent=4), encoding="utf-8")


def build(build_root, board_dir, variant, idf, idf_tools):
    env = os.environ.copy()
    if idf_tools:
        env["IDF_TOOLS_PATH"] = str(idf_tools)
    command = (f". {shlex.quote(str(idf / 'export.sh'))} >/dev/null && "
               f"python3 scripts/build.py {shlex.quote(board_dir)} --name {shlex.quote(variant)} "
               f"-c {TEMP_CONFIG}")
    subprocess.run(["bash", "-c", command], cwd=build_root, env=env, check=True)


def check_ota(build_root, url):
    sdkconfig = (build_root / "sdkconfig").read_text(encoding="utf-8")
    if f'CONFIG_OTA_URL="{url}"' not in sdkconfig:
        sys.exit("Build did not pick up the OTA URL; refusing to package it")


def app_version(app):
    desc = app.read_bytes()[0x20:0x120]
    return desc[16:48].split(b"\0")[0].decode()


def package(build_root, out_root, key, variant, url):
    out_dir = build_root / "build"
    entries = []
    for line in (out_dir / "flash_args").read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].startswith("0x"):
            entries.append((parts[0], out_dir / parts[1]))
    app = next(path for _, path in entries if path.name == "xiaozhi.bin")
    version = app_version(app)
    dest = out_root / f"zongzhu-{key}-{version}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    lines = ["--flash-mode dio --flash-freq 80m --flash-size 16MB"]
    sums = []
    for offset, path in entries:
        shutil.copy2(path, dest / path.name)
        lines.append(f"{offset} {path.name}")
        sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (dest / "flash_args").write_text("\n".join(lines) + "\n")
    (dest / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    (dest / "build-info.json").write_text(json.dumps({
        "version": version, "variant": variant, "ota_url": url,
        "app_bytes": app.stat().st_size,
    }, ensure_ascii=False, indent=2) + "\n")
    return dest


def flash(dest, port, erase):
    if erase:
        subprocess.run(["esptool", "--chip", "esp32s3", "--port", port, "erase-flash"], check=True)
    subprocess.run(["esptool", "--chip", "esp32s3", "--port", port, "--baud", "921600",
                    "write-flash", "@flash_args"], cwd=dest, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("board", choices=sorted(BOARDS))
    parser.add_argument("--ota-url", help="default: this Mac by its .local name, port 8003")
    parser.add_argument("--idf", type=Path, default=os.environ.get("IDF_PATH"),
                        help="ESP-IDF directory (default: $IDF_PATH)")
    parser.add_argument("--idf-tools", type=Path, default=os.environ.get("IDF_TOOLS_PATH"),
                        help="ESP-IDF tools directory (default: $IDF_TOOLS_PATH)")
    parser.add_argument("--build-dir", type=Path, default=Path.home() / ".cache" / "xiaozhi-zongzhu-build",
                        help="ASCII-only build directory (default: ~/.cache/xiaozhi-zongzhu-build)")
    parser.add_argument("--out", type=Path, default=REPO / "build-output",
                        help="where packages go (default: build-output/, not committed)")
    parser.add_argument("--flash", metavar="PORT", help="write the package to this serial port")
    parser.add_argument("--erase", action="store_true",
                        help="erase the whole flash first (Wi-Fi settings are lost)")
    args = parser.parse_args()
    if not args.idf or not (args.idf / "export.sh").exists():
        sys.exit("Pass --idf pointing at ESP-IDF 6.0.1+, or set IDF_PATH")

    board_dir, variant = BOARDS[args.board]
    url = check_url(args.ota_url or mac_ota_url())
    print(f"Board {args.board} ({variant}), OTA {url}")
    sync_source(args.build_dir)
    write_temp_config(args.build_dir, board_dir, variant, url)
    build(args.build_dir, board_dir, variant, args.idf, args.idf_tools)
    check_ota(args.build_dir, url)
    dest = package(args.build_dir, args.out, args.board, variant, url)
    print(f"Package: {dest}")
    if args.flash:
        flash(dest, args.flash, args.erase)


if __name__ == "__main__":
    main()
