#!/usr/bin/env python3
"""
Test Doubao TTS - supports compare mode and normal test mode (MP3 playback)

Usage:
  python test_tts.py              # Normal mode: synthesize MP3 and play
  python test_tts.py --compare    # Compare mode: compare ogg_opus vs mp3
  python test_tts.py --no-play    # Normal mode without playback
  python test_tts.py --save       # Save output audio as WAV file(s) to tests/
  python test_tts.py --text "你好世界"  # Override synthesis text
  python test_tts.py --format pcm  # Override audio format (pcm, mp3, ogg_opus)
  python test_tts.py --speed 1.5   # Override speech speed (default: 1.0)
  python test_tts.py --speaker-id zh_male_lengkugege_emo_v2_mars_bigtts  # Override speaker
  python test_tts.py --resource-id seed-tts-1.0  # Override resource_id
"""
import sys
import os
import wave
from pathlib import Path

# Add project root to path so imports work when running from any directory
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

import json
import time
import subprocess
import tempfile
import base64
import requests
import open_xiaoai_server
from core.utils.config_loader import ensure_config_module_loaded

ensure_config_module_loaded()
from config import APP_CONFIG
from core.services.tts.doubao import DoubaoTTS


SAMPLE_RATE = 24000


def save_wav(audio_data: bytes, path: str):
    """Save raw PCM audio data as a WAV file."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_data)
    print(f"  💾 Saved: {path}")


def play_audio(audio_data: bytes):
    """Play raw PCM audio data (16-bit signed, 24000Hz, mono) via WAV wrapper."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name
    try:
        # Wrap raw PCM in a WAV container so afplay/aplay can handle it
        with wave.open(tmp_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit = 2 bytes
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_data)

        if sys.platform == "darwin":
            subprocess.run(["afplay", tmp_path], check=True)
        else:
            subprocess.run(["aplay", tmp_path], check=True)
    except FileNotFoundError as e:
        print(f"  [!] Player not found: {e}")
    except subprocess.CalledProcessError as e:
        print(f"  [!] Playback failed: {e}")
    finally:
        os.unlink(tmp_path)


def get_tts():
    """Initialize TTS from config."""
    tts_config = APP_CONFIG.get("tts", {}).get("doubao", {})
    app_id = tts_config.get("app_id")
    access_key = tts_config.get("access_key")
    speaker = tts_config.get("default_speaker", "zh_female_cancan_mars_bigtts")

    if not app_id or not access_key:
        print("错误: 请先配置豆包 API 凭证")
        sys.exit(1)

    # Allow overriding speaker_id via --speaker-id <id> for debugging
    if "--speaker-id" in sys.argv:
        idx = sys.argv.index("--speaker-id")
        if idx + 1 < len(sys.argv):
            speaker = sys.argv[idx + 1]

    # Allow overriding resource_id via --resource-id <id> for debugging
    resource_id = None
    if "--resource-id" in sys.argv:
        idx = sys.argv.index("--resource-id")
        if idx + 1 < len(sys.argv):
            resource_id = sys.argv[idx + 1]

    return DoubaoTTS(app_id=app_id, access_key=access_key, speaker=speaker, resource_id=resource_id), tts_config


def fetch_encoded_audio(
    tts: DoubaoTTS,
    text: str,
    fmt: str = None,
    speed: float = 1.0,
    context_texts: list = None,
    emotion: str = None,
) -> bytes | None:
    """Fetch encoded audio from Doubao and let Rust handle decoding."""
    audio_format = fmt or tts.audio_format
    payload = tts._build_payload(
        text,
        format=audio_format,
        sample_rate=SAMPLE_RATE,
        speed=speed,
        context_texts=context_texts,
        emotion=emotion,
    )
    headers = {
        "X-Api-App-Id": tts.app_id,
        "X-Api-Access-Key": tts.access_key,
        "X-Api-Resource-Id": tts.resource_id,
        "Content-Type": "application/json",
        "Connection": "keep-alive",
    }

    response = requests.post(tts.api_url, headers=headers, json=payload, stream=True, timeout=60)
    if response.status_code >= 400:
        body = response.text[:500]
        raise RuntimeError(
            f"TTS request failed: HTTP {response.status_code}, resource_id={tts.resource_id}, "
            f"speaker={tts.speaker}, body={body}"
        )

    encoded_audio = bytearray()
    try:
        for chunk in response.iter_lines(decode_unicode=True):
            if not chunk:
                continue

            data = json.loads(chunk)
            if data.get("code", 0) == 0 and data.get("data"):
                encoded_audio.extend(base64.b64decode(data["data"]))
                continue
            if data.get("code", 0) == 20000000:
                break
            if data.get("code", 0) > 0:
                raise RuntimeError(f"TTS API Error {data.get('code')}: {data.get('message')}")
    finally:
        response.close()

    return bytes(encoded_audio) if encoded_audio else None


def synthesize_pcm(tts: DoubaoTTS, text: str, fmt: str = None, speed: float = 1.0) -> bytes | None:
    """Fetch encoded audio in Python and decode it in Rust."""
    audio_format = fmt or tts.audio_format
    encoded_audio = fetch_encoded_audio(tts, text, fmt=audio_format, speed=speed)
    if not encoded_audio:
        return None
    return bytes(
        open_xiaoai_server.decode_audio(
            encoded_audio,
            format=audio_format,
            sample_rate=SAMPLE_RATE,
        )
    )


DEFAULT_TEXT = '央视财经频道《经济半小时》两会特别节目《中国经济向新行：智能经济活力奔涌》播出，聚焦我国人工智能大模型已进入全球第一梯队，而阿里千问APP作为AI助手的典型代表，正以"AI办事"的创新模式，深刻重塑大众的日常生活。'

def run_normal(play: bool = True, save: bool = False, text: str = DEFAULT_TEXT, fmt: str = None, speed: float = 1.0):
    """Normal mode: synthesize and optionally play."""
    tts, tts_config = get_tts()
    audio_format = fmt or tts.audio_format

    print(f"\n{'='*60}")
    print("Doubao TTS - Normal Mode")
    print(f"{'='*60}")
    print(f"Speaker : {tts.speaker}")
    print(f"Format  : {audio_format}")
    print(f"Speed   : {speed}")
    print(f"Text    : {text[:60]}...")

    start = time.time()
    audio_data = synthesize_pcm(tts, text, fmt=audio_format, speed=speed)
    elapsed = time.time() - start

    if audio_data:
        print(f"\n✅ Success! Size: {len(audio_data):,} bytes, Time: {elapsed:.2f}s")
        if save:
            out_path = str(PROJECT_ROOT / "tests" / "tts_output.wav")
            save_wav(audio_data, out_path)
        if play:
            print("Playing audio...")
            play_audio(audio_data)
    else:
        print("\n❌ Failed!")

    print(f"\n{'='*60}")
    print("Done")
    print(f"{'='*60}")


def run_compare(play: bool = True, save: bool = False, text: str = DEFAULT_TEXT, speed: float = 1.0):
    """Compare mode: ogg_opus vs mp3, play both if requested."""
    tts, tts_config = get_tts()

    print(f"\n{'='*60}")
    print("Doubao TTS - Compare Mode (ogg_opus vs mp3)")
    print(f"{'='*60}")
    print(f"Speaker : {tts.speaker}")
    print(f"Speed   : {speed}")
    print(f"Text    : {text[:60]}...")

    results = {}
    for fmt in ("ogg_opus", "mp3"):
        print(f"\n--- {fmt} ---")
        start = time.time()
        data = synthesize_pcm(tts, text, fmt=fmt, speed=speed)
        elapsed = time.time() - start
        if data:
            print(f"✅ Size: {len(data):,} bytes, Time: {elapsed:.2f}s")
            results[fmt] = data
        else:
            print(f"❌ Failed!")
            results[fmt] = None

    print(f"\n--- Comparison ---")
    if results.get("ogg_opus") and results.get("mp3"):
        ogg_size = len(results["ogg_opus"])
        mp3_size = len(results["mp3"])
        ratio = mp3_size / ogg_size
        print(f"ogg_opus: {ogg_size:,} bytes")
        print(f"mp3     : {mp3_size:,} bytes")
        print(f"Ratio mp3/ogg_opus: {ratio:.2f}x", end="")
        if ratio > 1:
            print(f"  (ogg_opus saves {(1 - 1/ratio) * 100:.1f}%)")
        else:
            print(f"  (mp3 saves {(1 - ratio) * 100:.1f}%)")

    if play:
        for fmt, data in results.items():
            if data:
                print(f"\nPlaying {fmt}...")
                play_audio(data)

    if save:
        for fmt, data in results.items():
            if data:
                out_path = str(PROJECT_ROOT / "tests" / f"tts_output_{fmt}.wav")
                save_wav(data, out_path)

    print(f"\n{'='*60}")
    print("Done")
    print(f"{'='*60}")


if __name__ == "__main__":
    compare_mode = "--compare" in sys.argv
    no_play = "--no-play" in sys.argv
    save = "--save" in sys.argv

    text = DEFAULT_TEXT
    if "--text" in sys.argv:
        idx = sys.argv.index("--text")
        if idx + 1 < len(sys.argv):
            text = sys.argv[idx + 1]

    fmt = None
    if "--format" in sys.argv:
        idx = sys.argv.index("--format")
        if idx + 1 < len(sys.argv):
            fmt = sys.argv[idx + 1]

    speed = 1.0
    if "--speed" in sys.argv:
        idx = sys.argv.index("--speed")
        if idx + 1 < len(sys.argv):
            speed = float(sys.argv[idx + 1])

    if compare_mode:
        run_compare(play=not no_play, save=save, text=text, speed=speed)
    else:
        run_normal(play=not no_play, save=save, text=text, fmt=fmt, speed=speed)
