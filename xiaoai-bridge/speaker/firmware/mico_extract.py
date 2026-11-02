#!/usr/bin/env python3
"""解开小米 mico_all_*.bin：校验 CRC32 和文件名里的 MD5 片段，按段写出（boot.img、root.squashfs……）。

格式照 open-xiaoai client-patch/src/extract.py（源自 csftech/Xiaomi-OpenWrt-firmware-toolkit）。
用法：python3 -I mico_extract.py <固件.bin> <输出目录>
"""
import binascii
import ctypes
import hashlib
import os
import sys


class ImageHeader(ctypes.Structure):
    _fields_ = [("magic", ctypes.c_uint), ("signature_offset", ctypes.c_uint),
                ("crc32_checksum", ctypes.c_uint), ("file_type", ctypes.c_ushort),
                ("model", ctypes.c_ushort), ("segment_offsets", ctypes.c_uint * 8)]


class SegmentHeader(ctypes.Structure):
    _fields_ = [("magic", ctypes.c_uint), ("flash_address", ctypes.c_uint),
                ("length", ctypes.c_uint), ("partition", ctypes.c_uint),
                ("segment_name", ctypes.c_char * 32)]


def main(path, dest):
    data = open(path, "rb").read()
    h = ImageHeader.from_buffer_copy(data)
    assert h.magic in (0x31524448, 0x32524448), hex(h.magic)
    assert h.crc32_checksum == ~binascii.crc32(data[12:]) & 0xFFFFFFFF, "CRC32 不对"
    md5 = hashlib.md5(data).hexdigest()
    tag = os.path.basename(path).split("_")[-2]
    assert md5.endswith(tag), "MD5 和文件名不符"
    print(f"magic={hex(h.magic)} md5={md5} 校验通过")
    os.makedirs(dest, exist_ok=False)
    for off in h.segment_offsets:
        if not off:
            continue
        s = SegmentHeader.from_buffer_copy(data, off)
        name = s.segment_name.decode()
        start = off + ctypes.sizeof(SegmentHeader)
        with open(os.path.join(dest, name), "wb") as f:
            f.write(data[start:start + s.length])
        print(f"{name:20s} 长度={s.length:>10d} flash_address={hex(s.flash_address)} partition={s.partition}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
