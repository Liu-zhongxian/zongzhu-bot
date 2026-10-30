#!/usr/bin/env python3
"""
OpenXiaoAI 控制命令
"""

import os
import sys
import argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import check_health, get_status, wakeup, interrupt


def main():
    parser = argparse.ArgumentParser(description="OpenXiaoAI 控制命令")
    parser.add_argument("command", 
                        choices=["health", "status", "wakeup", "interrupt"],
                        help="控制命令")
    parser.add_argument("--silent", action=argparse.BooleanOptionalAction, default=False,
                        help="静默唤醒（不播放提示音）；默认有声")
    
    args = parser.parse_args()
    
    try:
        if args.command == "health":
            result = check_health()
            if result.get("success"):
                data = result.get("data", {})
                status = data.get("status", "unknown")
                speaker_ready = data.get("speaker_ready", False)
                
                status_icon = "✅" if status == "healthy" else "❌"
                speaker_icon = "🎵" if speaker_ready else "🔇"
                
                print(f"{status_icon} 服务状态: {status}")
                print(f"{speaker_icon} 音箱就绪: {'是' if speaker_ready else '否'}")
            else:
                print(f"⚠️ 健康检查异常: {result}")
        
        elif args.command == "status":
            result = get_status()
            if result.get("success"):
                data = result.get("data", {})
                status = data.get("status", "unknown")
                
                status_map = {
                    "playing": "🎵 播放中",
                    "paused": "⏸️ 已暂停",
                    "idle": "💤 空闲"
                }
                print(status_map.get(status, f"❓ 未知状态: {status}"))
            else:
                print(f"⚠️ 获取状态失败: {result}")
        
        elif args.command == "wakeup":
            silent = args.silent
            result = wakeup(silent=silent)
            if result.get("success"):
                mode = "静默" if silent else "有声"
                print(f"✅ 已唤醒小爱 [{mode}模式]")
            else:
                print(f"⚠️ 唤醒失败: {result}")
        
        elif args.command == "interrupt":
            result = interrupt()
            if result.get("success"):
                print("✅ 已打断当前播放")
            else:
                print(f"⚠️ 打断失败: {result}")
    
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    import os
    main()
