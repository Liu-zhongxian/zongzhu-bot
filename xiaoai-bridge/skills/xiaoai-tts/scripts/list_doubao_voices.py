#!/usr/bin/env python3
"""
获取豆包 TTS 可用音色列表
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import api_request


def list_voices(version=None):
    """
    获取豆包 TTS 可用音色列表
    
    Args:
        version: 版本筛选 "1.0", "2.0", "all"
    """
    path = "/api/tts/doubao_voices"
    if version:
        path += f"?version={version}"
    
    return api_request(path)


def main():
    parser = argparse.ArgumentParser(description="获取豆包 TTS 音色列表")
    parser.add_argument("--version", choices=["1.0", "2.0", "all"],
                        help="版本筛选: 1.0, 2.0, all")
    
    args = parser.parse_args()
    
    try:
        version = args.version if args.version else "all"        
        result = list_voices(version=version)
        
        if not result.get("success"):
            print(f"❌ 获取失败: {result}")
            sys.exit(1)
        
        data = result.get("data", {})

        # version=all: returns versions with full voice dicts
        if "versions" in data:
            versions = data["versions"]
            for ver in ["2.0", "1.0"]:
                if ver not in versions:
                    continue
                v = versions[ver]
                print(f"\n🎙️  {ver} 音色 - {v.get('description', '')} (共 {v.get('count', 0)} 个)")
                print("-" * 70)
                for voice_type, name in v.get("voices", {}).items():
                    emotion = "✨多情感" if "emo" in voice_type else ""
                    print(f"  {name:16} | {voice_type} {emotion}")
            print(f"\n共 {data.get('total_voices', 0)} 个音色")

        # version=1.0 or 2.0: returns full voices dict
        elif "voices" in data:
            ver = data.get("version", "")
            voices = data["voices"]
            print(f"\n🎙️  {ver} 音色 (共 {data.get('count', 0)} 个)")
            print("-" * 70)
            for voice_type, name in voices.items():
                emotion = "✨多情感" if "emo" in voice_type else ""
                print(f"  {name:16} | {voice_type} {emotion}")
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    import os
    main()
