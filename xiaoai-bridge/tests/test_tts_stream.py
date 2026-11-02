#!/usr/bin/env python3
"""
Smoke test Doubao streaming TTS without XiaoAI speaker playback.

Usage:
  python3 tests/test_tts_stream.py
  python3 tests/test_tts_stream.py --speaker-id S_xxx --resource-id seed-icl-2.0
  python3 tests/test_tts_stream.py --format mp3
"""

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def add_local_venv_site_packages() -> None:
    """Allow running this script with system python3 by reusing the project's .venv."""
    venv_lib = PROJECT_ROOT / ".venv" / "lib"
    if not venv_lib.exists():
        return

    for site_packages in sorted(venv_lib.glob("python*/site-packages"), reverse=True):
        site_path = str(site_packages)
        if site_path not in sys.path:
            sys.path.insert(0, site_path)
        break


add_local_venv_site_packages()

import open_xiaoai_server
from core.utils.config_loader import ensure_config_module_loaded

ensure_config_module_loaded()
from config import APP_CONFIG
from core.services.tts.doubao import DoubaoTTS


TEXT = "这是一段用于测试豆包流式 TTS 是否能够在不依赖音箱的情况下跑通的语音内容。"


def get_arg(name: str, default=None):
    if name in sys.argv:
        index = sys.argv.index(name)
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return default


def build_tts() -> DoubaoTTS:
    tts_config = APP_CONFIG.get("tts", {}).get("doubao", {})
    app_id = tts_config.get("app_id")
    access_key = tts_config.get("access_key")
    speaker = get_arg("--speaker-id", tts_config.get("default_speaker", "zh_female_vv_uranus_bigtts"))
    resource_id = get_arg("--resource-id")
    audio_format = get_arg("--format", tts_config.get("audio_format", "mp3"))

    if not app_id or not access_key:
        raise RuntimeError("请先在 config.py 中配置豆包 app_id / access_key")

    return DoubaoTTS(
        app_id=app_id,
        access_key=access_key,
        speaker=speaker,
        resource_id=resource_id,
        audio_format=audio_format,
    )


async def main() -> None:
    tts = build_tts()

    print("=" * 60)
    print("Doubao TTS Stream Smoke Test")
    print("=" * 60)
    print(f"Speaker      : {tts.speaker}")
    print(f"Resource ID  : {tts.resource_id}")
    print(f"Audio Format : {tts.audio_format}")
    print(f"Text         : {TEXT}")

    result = await open_xiaoai_server.tts_stream_collect(
        TEXT,
        app_id=tts.app_id,
        access_key=tts.access_key,
        resource_id=tts.resource_id,
        speaker=tts.speaker,
        format=tts.audio_format,
        sample_rate=24000,
    )

    stats = json.loads(result)
    print("\nResult:")
    print(json.dumps(stats, ensure_ascii=False, indent=2))

    if stats.get("encoded_chunks", 0) <= 0:
        raise RuntimeError("流式请求未收到任何编码音频块")
    if stats.get("pcm_chunks", 0) <= 0:
        raise RuntimeError("流式解码未产出任何 PCM 数据块")

    print("\n✅ Stream smoke test passed")


if __name__ == "__main__":
    asyncio.run(main())
