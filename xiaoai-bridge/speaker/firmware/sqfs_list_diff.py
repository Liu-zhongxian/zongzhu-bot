#!/usr/bin/env python3
"""比较两个 squashfs 镜像的 `unsquashfs -lls` 清单：权限、属主、大小（文件）、链接目标、设备号。
用法：python3 -I sqfs_list_diff.py <旧.squashfs> <新.squashfs>
"""
import re
import subprocess
import sys

LINE = re.compile(r"^(\S+) (\S+)\s+(\S+(?:,\s*\d+)?) \S+ \S+ squashfs-root(.*)$")


def listing(img):
    out = subprocess.run(["unsquashfs", "-lls", img], capture_output=True, text=True).stdout
    items = {}
    for line in out.splitlines():
        m = LINE.match(line)
        if not m:
            continue
        mode, owner, size, rest = m.groups()
        path, _, target = rest.partition(" -> ")
        if mode[0] == "d":
            size = ""  # 目录大小随打包方式变，不比
        items[path or "/"] = (mode, owner, size, target)
    return items


a, b = listing(sys.argv[1]), listing(sys.argv[2])
print(f"条目数 {len(a)} -> {len(b)}")
for p in sorted(set(a) | set(b)):
    if a.get(p) != b.get(p):
        print(p, a.get(p), "->", b.get(p))
