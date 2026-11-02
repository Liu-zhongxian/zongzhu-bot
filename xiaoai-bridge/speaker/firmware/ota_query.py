#!/usr/bin/env python3
"""向小米升级接口查询 OH2P 当前版本固件的下载信息（只查询，不下载）。

照 open-xiaoai packages/client-patch/src/ota.ts 的 getOTA() 重写，不需要登录。
用法：python3 ota_query.py <SN（音箱底部标签上）> <当前版本，如 1.62.2> [channel，默认 release]
"""
import base64
import hashlib
import json
import sys
import time
import urllib.request

MODEL = "OH2P"
SALT = "8007236f-a2d6-4847-ac83-c49395ad6d65"


def query(sn, version, channel):
    t = int(time.time() * 1000)
    info = (f"channel={channel}&filterID={sn}&locale=zh_CN&model={MODEL}"
            f"&time={t}&version={version}&{SALT}")
    s = hashlib.md5(base64.b64encode(info.encode())).hexdigest()
    url = (f"http://api.miwifi.com/rs/grayupgrade/v2/{MODEL}?model={MODEL}"
           f"&version={version}&channel={channel}&filterID={sn}"
           f"&locale=zh_CN&time={t}&s={s}")
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read())


if __name__ == "__main__":
    sn = sys.argv[1]
    version = sys.argv[2]
    channel = sys.argv[3] if len(sys.argv) > 3 else "release"
    print(json.dumps(query(sn, version, channel), ensure_ascii=False, indent=2))
