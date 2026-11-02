#!/usr/bin/env python3
"""
上传并播放本地音频文件
"""

import os
import sys
import argparse
import urllib.request
import urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import get_api_config


def play_file(file_path, blocking=False):
    """
    上传并播放本地音频文件
    
    Args:
        file_path: 本地音频文件路径
        blocking: 是否阻塞等待（默认 False）
    """
    if not os.path.exists(file_path):
        raise Exception(f"文件不存在: {file_path}")
    
    base_url = get_api_config()
    full_url = f"{base_url}/api/play/file?blocking={'true' if blocking else 'false'}"
    
    # 构建 multipart/form-data 请求
    boundary = "----FormBoundary"
    
    with open(file_path, "rb") as f:
        file_data = f.read()
    
    filename = os.path.basename(file_path)
    
    body = (
        f"------{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: audio/mpeg\r\n\r\n"
    ).encode("utf-8")
    body += file_data
    body += f"\r\n------{boundary}--\r\n".encode("utf-8")
    
    headers = {
        "Content-Type": f"multipart/form-data; boundary=----{boundary}"
    }
    
    req = urllib.request.Request(full_url, data=body, headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            import json
            result = json.loads(response.read().decode("utf-8"))
            
            mode = "阻塞模式" if blocking else "非阻塞模式"
            print(f"✅ 上传并播放 [{mode}]: {filename}")
            return result
    except urllib.error.HTTPError as e:
        error_msg = f"HTTP 错误: {e.code} - {e.reason}"
        raise Exception(error_msg)
    except Exception as e:
        raise Exception(f"请求失败: {e}")


def main():
    parser = argparse.ArgumentParser(description="上传并播放本地音频文件")
    parser.add_argument("file", help="本地音频文件路径")
    parser.add_argument("--blocking", action="store_true",
                        help="阻塞等待播放完成（默认非阻塞）")
    
    args = parser.parse_args()
    
    try:
        result = play_file(args.file, blocking=args.blocking)
        if result.get("success"):
            print(f"🎵 播放成功")
        else:
            print(f"⚠️ 播放可能失败: {result}")
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
