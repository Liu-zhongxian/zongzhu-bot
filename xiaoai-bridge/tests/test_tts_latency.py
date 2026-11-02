#!/usr/bin/env python3
"""
Compare end-to-end streaming latency between different Doubao audio formats.

Usage:
  python3 tests/test_tts_latency.py
  python3 tests/test_tts_latency.py --formats mp3,pcm --rounds 3 --repeat 6
  python3 tests/test_tts_latency.py --speaker-id S_xxx --resource-id seed-icl-2.0
"""

import asyncio
import json
import statistics
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


BASE_TEXT = (
    "央视财经频道《经济半小时》两会特别节目《中国经济向新行：智能经济活力奔涌》播出，"
    "聚焦我国人工智能大模型已进入全球第一梯队，而阿里千问APP作为AI助手的典型代表，"
    "正以AI办事的创新模式，深刻重塑大众的日常生活。"
)


def get_arg(name: str, default=None):
    if name in sys.argv:
        index = sys.argv.index(name)
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return default


def build_tts(audio_format: str) -> DoubaoTTS:
    tts_config = APP_CONFIG.get("tts", {}).get("doubao", {})
    app_id = tts_config.get("app_id")
    access_key = tts_config.get("access_key")
    speaker = get_arg("--speaker-id", tts_config.get("default_speaker", "zh_female_vv_uranus_bigtts"))
    resource_id = get_arg("--resource-id")

    if not app_id or not access_key:
        raise RuntimeError("请先在 config.py 中配置豆包 app_id / access_key")

    return DoubaoTTS(
        app_id=app_id,
        access_key=access_key,
        speaker=speaker,
        resource_id=resource_id,
        audio_format=audio_format,
    )


def build_text() -> str:
    repeat = int(get_arg("--repeat", "6"))
    return " ".join([BASE_TEXT] * max(1, repeat))


def avg(values: list[float | int | None]) -> float | None:
    filtered = [v for v in values if v is not None]
    if not filtered:
        return None
    return float(statistics.mean(filtered))


def estimate_pcm_duration_ms(pcm_bytes: int, sample_rate: int) -> float:
    bytes_per_second = sample_rate * 2
    return pcm_bytes * 1000.0 / bytes_per_second


async def run_once(audio_format: str, text: str) -> dict:
    tts = build_tts(audio_format)
    result = await open_xiaoai_server.tts_stream_collect(
        text,
        app_id=tts.app_id,
        access_key=tts.access_key,
        resource_id=tts.resource_id,
        speaker=tts.speaker,
        format=tts.audio_format,
        sample_rate=24000,
    )
    return json.loads(result)


async def main() -> None:
    formats = [item.strip() for item in get_arg("--formats", "mp3,pcm").split(",") if item.strip()]
    rounds = int(get_arg("--rounds", "3"))
    text = build_text()

    print("=" * 72)
    print("Doubao TTS Stream Latency Benchmark")
    print("=" * 72)
    print(f"Formats   : {', '.join(formats)}")
    print(f"Rounds    : {rounds}")
    print(f"Text chars: {len(text)}")
    print()

    summaries: dict[str, list[dict]] = {}

    for audio_format in formats:
        summaries[audio_format] = []
        print(f"[{audio_format}]")
        for round_index in range(1, rounds + 1):
            stats = await run_once(audio_format, text)
            summaries[audio_format].append(stats)
            print(
                f"  round {round_index}: first_encoded={stats.get('first_encoded_ms')} ms, "
                f"first_pcm={stats.get('first_pcm_ms')} ms, total={stats.get('total_ms')} ms, "
                f"encoded={stats.get('encoded_bytes')} B, pcm={stats.get('pcm_bytes')} B, "
                f"pcm_duration={estimate_pcm_duration_ms(stats.get('pcm_bytes', 0), stats.get('sample_rate', 24000)):.1f} ms"
            )
        print()

    print("-" * 72)
    print("Summary")
    print("-" * 72)
    print(
        f"{'format':<8} {'first_encoded_avg':>18} {'first_pcm_avg':>16} "
        f"{'total_avg':>12} {'encoded_avg':>14} {'pcm_avg':>12} "
        f"{'pcm_duration_avg':>18} {'speech_estimate':>18}"
    )
    for audio_format in formats:
        rows = summaries[audio_format]
        first_encoded_avg = avg([row.get("first_encoded_ms") for row in rows])
        first_pcm_avg = avg([row.get("first_pcm_ms") for row in rows])
        total_avg = avg([row.get("total_ms") for row in rows])
        encoded_avg = avg([row.get("encoded_bytes") for row in rows])
        pcm_avg = avg([row.get("pcm_bytes") for row in rows])
        pcm_duration_avg = avg(
            [
                estimate_pcm_duration_ms(
                    row.get("pcm_bytes", 0),
                    row.get("sample_rate", 24000),
                )
                for row in rows
            ]
        )
        speech_estimate = None
        if total_avg is not None and pcm_duration_avg is not None:
            speech_estimate = total_avg - pcm_duration_avg
        print(
            f"{audio_format:<8} "
            f"{first_encoded_avg:>18.1f} "
            f"{first_pcm_avg:>16.1f} "
            f"{total_avg:>12.1f} "
            f"{encoded_avg:>14.1f} "
            f"{pcm_avg:>12.1f} "
            f"{pcm_duration_avg:>18.1f} "
            f"{speech_estimate:>18.1f}"
        )

    if "mp3" in summaries and "pcm" in summaries:
        mp3_rows = summaries["mp3"]
        pcm_rows = summaries["pcm"]
        first_pcm_gap = avg([row.get("first_pcm_ms") for row in pcm_rows]) - avg([row.get("first_pcm_ms") for row in mp3_rows])
        total_gap = avg([row.get("total_ms") for row in pcm_rows]) - avg([row.get("total_ms") for row in mp3_rows])
        print()
        print(
            f"PCM vs MP3: first_pcm delta={first_pcm_gap:+.1f} ms, "
            f"total delta={total_gap:+.1f} ms"
        )


if __name__ == "__main__":
    asyncio.run(main())
