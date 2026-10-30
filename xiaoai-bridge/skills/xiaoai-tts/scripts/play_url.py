#!/usr/bin/env python3
"""
播放远程音频 URL
"""

import os
import sys
import argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import api_request


def play_url(url, blocking=False, timeout=60000):
    """
    播放远程音频 URL
    
    Args:
        url: 音频 URL
        blocking: 是否阻塞等待（默认 False）
        timeout: 超时时间（毫秒，默认 60000）
    """
    data = {
        "url": url,
        "blocking": blocking,
        "timeout": timeout
    }
    
    result = api_request("/api/play/url", method="POST", data=data)
    
    mode = "阻塞模式" if blocking else "非阻塞模式"
    print(f"✅ 播放远程音频 [{mode}]: {url}")
    return result


def main():
    parser = argparse.ArgumentParser(description="播放远程音频 URL")
    parser.add_argument("url", help="音频 URL")
    parser.add_argument("--blocking", action="store_true",
                        help="阻塞等待播放完成（默认非阻塞）")
    parser.add_argument("--timeout", type=int, default=60000,
                        help="超时时间（毫秒，默认 60000）")
    
    args = parser.parse_args()
    
    try:
        result = play_url(args.url, blocking=args.blocking, timeout=args.timeout)
        if result.get("success"):
            print(f"🎵 播放成功")
        else:
            print(f"⚠️ 播放可能失败: {result}")
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    import os
    main()
