#!/usr/bin/env python3
"""Assemble the web flasher site: web/ plus the firmware packages it flashes.

Each board in web/boards.json names a package under firmware/. Its files are
checked against SHA256SUMS, copied to <out>/firmware/<board id>/, and listed with
their flash offsets (from flash_args) in a manifest.json the page reads. The
site's boards.json also gets each package's app ELF SHA-256, so the page can tell
boards with the same chip apart when one already runs a release package.

Examples:
  tools/build_web.py                 # writes _site/
  tools/build_web.py --out /tmp/site
  python3 -m http.server -d _site    # then open http://localhost:8000 in Chrome
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "web"
# Development files that are not part of the site.
SKIP = shutil.ignore_patterns("test", "package.json", "node_modules", ".DS_Store")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_parts(package):
    sums = {}
    for line in (package / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        sums[name.lstrip("*")] = digest
    lines = (package / "flash_args").read_text().split("\n")
    parts = []
    for line in lines[1:]:
        if not line.strip():
            continue
        offset, name = line.split()
        path = package / name
        digest = sha256(path)
        if sums.get(name) != digest:
            sys.exit(f"{path}: SHA-256 does not match SHA256SUMS")
        parts.append({"file": name, "offset": int(offset, 16), "size": path.stat().st_size, "sha256": digest})
    return lines[0].strip(), sorted(parts, key=lambda p: p["offset"])


def app_elf_sha256(app):
    # esp_app_desc_t.app_elf_sha256, after the image header (24) and segment header (8).
    return app.read_bytes()[176:208].hex()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=REPO / "_site")
    args = parser.parse_args()

    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(WEB, out, ignore=SKIP)

    boards = json.loads((WEB / "boards.json").read_text(encoding="utf-8"))
    for board in boards:
        package = REPO / "firmware" / board["package"]
        flash_args, parts = package_parts(package)
        if board["assets"] not in {p["file"] for p in parts}:
            sys.exit(f"{package}: assets file {board['assets']} is not in flash_args")
        info = json.loads((package / "build-info.json").read_text(encoding="utf-8"))
        target = out / "firmware" / board["id"]
        target.mkdir(parents=True)
        for part in parts:
            shutil.copy2(package / part["file"], target / part["file"])
        board["appSha256"] = app_elf_sha256(package / "xiaozhi.bin")
        manifest = {"board": board["id"], "package": board["package"], "version": info["version"],
                    "flashArgs": flash_args, "parts": parts}
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"{board['id']}: {board['package']} ({len(parts)} parts, {sum(p['size'] for p in parts):,} bytes)")
    (out / "boards.json").write_text(json.dumps(boards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Site: {out}")


if __name__ == "__main__":
    main()
