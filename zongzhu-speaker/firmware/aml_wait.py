#!/usr/bin/env python3
"""在同一个进程里盯着 USB，晶晨刷机设备（1b8e:c003）一出现就发 identify，把音箱留在刷机模式。

identify 是晶晨 USB 协议里的读请求（控制传输 bmRequestType=0xC0、bRequest=0x20，读 8 字节固件版本），
和 `update identify` 发的是同一个请求，不写任何东西。（请求号参考 superna9999/pyamlboot 的 REQ_IDENTIFY_HOST。）

为什么需要它：OH2P 上电后刷机设备只出现约 0.9 秒，每次新起一个 `update` 进程来不及看到它。
用法：python3 -I aml_wait.py [等待秒数，默认 240]；连上返回 0，超时返回 1。
需要 pyusb 和 libusb（Homebrew：brew install libusb）；libusb 不在 Homebrew 默认位置时用环境变量 AML_LIBUSB 指定。
"""
import os
import sys
import time

import usb.backend.libusb1
import usb.core

VID, PID = 0x1B8E, 0xC003
REQ_IDENTIFY_HOST = 0x20

LIBUSB = os.environ.get("AML_LIBUSB", "/opt/homebrew/lib/libusb-1.0.dylib")
backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)


def main(wait):
    end = time.time() + wait
    seen = False
    known = None
    while time.time() < end:
        # 诊断：libusb 看到的设备一有变化就记下来
        ids = {f"{d.idVendor:04x}:{d.idProduct:04x}" for d in usb.core.find(find_all=True, backend=backend)}
        if ids != known:
            if known is not None:
                print(f"{time.strftime('%H:%M:%S')} libusb 设备变化 +{sorted(ids - known)} -{sorted(known - ids)}", flush=True)
            known = ids
        dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
        if dev is None:
            time.sleep(0.002)
            continue
        if not seen:
            print(f"{time.strftime('%H:%M:%S')} 看到刷机设备 1b8e:c003", flush=True)
            seen = True
        try:
            ver = dev.ctrl_transfer(0xC0, REQ_IDENTIFY_HOST, 0, 0, 8, timeout=200)
            print(f"identify 成功，固件版本 {'-'.join(str(b) for b in ver)}", flush=True)
            usb.util.dispose_resources(dev)
            return 0
        except usb.core.USBError as e:
            print(f"identify 失败：{e}，重试", flush=True)
            time.sleep(0.005)
    print("超时：没有连上刷机设备" + ("（看到过，但 identify 没成功）" if seen else ""), flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 240))
