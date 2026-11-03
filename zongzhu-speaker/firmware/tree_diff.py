#!/usr/bin/env python3
"""比较两个解开的 rootfs，不跟随符号链接。输出：新增、删除、内容变了、链接目标变了。
用法：python3 -I tree_diff.py <旧目录> <新目录>
"""
import hashlib
import os
import stat
import sys


def scan(root):
    out = {}
    for d, dirs, files in os.walk(root, followlinks=False):
        for n in dirs + files:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, root)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                out[rel] = ("link", os.readlink(p))
            elif stat.S_ISREG(st.st_mode):
                out[rel] = ("file", hashlib.md5(open(p, "rb").read()).hexdigest(), st.st_size)
            elif stat.S_ISDIR(st.st_mode):
                out[rel] = ("dir",)
            else:
                out[rel] = ("other",)
    return out


a, b = scan(sys.argv[1]), scan(sys.argv[2])
for k in sorted(set(b) - set(a)):
    print("新增", k, b[k][0], b[k][-1] if b[k][0] != "dir" else "")
for k in sorted(set(a) - set(b)):
    print("删除", k, a[k][0])
for k in sorted(set(a) & set(b)):
    if a[k] != b[k]:
        if a[k][0] == "file" and b[k][0] == "file":
            print("改动", k, a[k][2], "->", b[k][2])
        else:
            print("改动", k, a[k], "->", b[k])
