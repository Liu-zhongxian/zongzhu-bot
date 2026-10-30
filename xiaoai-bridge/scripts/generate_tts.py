#!/usr/bin/env python3
"""
Generate a local audio file from Doubao TTS.

Usage:
  python3 scripts/generate_tts.py --speaker-id zh_female_vv_uranus_bigtts --text "你好世界"
  python3 scripts/generate_tts.py --speaker-id S_xxx --text-file ./demo.txt --output ./demo.wav
  python3 scripts/generate_tts.py --speaker-id zh_male_lengkugege_emo_v2_mars_bigtts --text "你好" --format mp3
  python3 scripts/generate_tts.py --speaker-id zh_male_lengkugege_emo_v2_mars_bigtts --text "你好" --emotion happy
"""

import argparse
import base64
import json
import sys
import wave
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

import requests
import open_xiaoai_server
from core.utils.config_loader import ensure_config_module_loaded

ensure_config_module_loaded()
from config import APP_CONFIG
from core.services.tts.doubao import DoubaoTTS


SAMPLE_RATE = 24000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an audio file from Doubao TTS"
    )
    parser.add_argument(
        "--speaker-id",
        required=True,
        help="Doubao speaker ID, for example zh_female_vv_uranus_bigtts or S_xxx",
    )
    parser.add_argument(
        "--text",
        help="Text to synthesize",
    )
    parser.add_argument(
        "--text-file",
        help="Read synthesis text from a local file",
    )
    parser.add_argument(
        "--output",
        help="Output file path. Default is auto-generated under ./output/",
    )
    parser.add_argument(
        "--format",
        choices=["auto", "pcm", "mp3", "ogg_opus"],
        help="Doubao output format. Defaults to config value.",
    )
    parser.add_argument(
        "--resource-id",
        help="Override resource_id, for example seed-tts-1.0 or seed-icl-2.0",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speech speed (default: 1.0)",
    )
    parser.add_argument(
        "--emotion",
        help="Emotion for multi-emotion speakers, for example happy",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=SAMPLE_RATE,
        help=f"Audio sample rate when decoding PCM/WAV (default: {SAMPLE_RATE})",
    )
    return parser.parse_args()


def read_text(args: argparse.Namespace) -> str:
    if bool(args.text) == bool(args.text_file):
        raise ValueError("必须且只能指定一个参数：--text 或 --text-file")

    if args.text:
        text = args.text.strip()
    else:
        text = Path(args.text_file).read_text(encoding="utf-8").strip()

    if not text:
        raise ValueError("输入文案不能为空")

    return text


def build_tts(args: argparse.Namespace) -> DoubaoTTS:
    tts_config = APP_CONFIG.get("tts", {}).get("doubao", {})
    app_id = tts_config.get("app_id")
    access_key = tts_config.get("access_key")

    if not app_id or not access_key:
        raise RuntimeError("请先在 config.py 中配置豆包 app_id / access_key")

    return DoubaoTTS(
        app_id=app_id,
        access_key=access_key,
        speaker=args.speaker_id,
        resource_id=args.resource_id,
        audio_format=args.format,
    )


def fetch_encoded_audio(
    tts: DoubaoTTS,
    text: str,
    audio_format: str,
    speed: float,
    emotion: str | None,
    sample_rate: int,
) -> bytes:
    payload = tts._build_payload(
        text,
        format=audio_format,
        sample_rate=sample_rate,
        speed=speed,
        emotion=emotion,
    )
    headers = {
        "X-Api-App-Id": tts.app_id,
        "X-Api-Access-Key": tts.access_key,
        "X-Api-Resource-Id": tts.resource_id,
        "Content-Type": "application/json",
        "Connection": "keep-alive",
    }

    response = requests.post(
        tts.api_url,
        headers=headers,
        json=payload,
        stream=True,
        timeout=60,
    )
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
                raise RuntimeError(
                    f"TTS API Error {data.get('code')}: {data.get('message')}"
                )
    finally:
        response.close()

    if not encoded_audio:
        raise RuntimeError("TTS API 未返回任何音频数据")

    return bytes(encoded_audio)


def build_default_output_path(text: str, audio_format: str) -> Path:
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    suffix = ".wav" if audio_format == "pcm" else ".mp3" if audio_format == "mp3" else ".ogg"
    text_hint = "".join(ch for ch in text[:24] if ch.isalnum()) or "tts"
    return output_dir / f"tts_{text_hint}{suffix}"


def resolve_output_path(args: argparse.Namespace, text: str, audio_format: str) -> Path:
    if args.output:
        return Path(args.output).expanduser().resolve()
    return build_default_output_path(text, audio_format)


def save_wav(audio_data: bytes, output_path: Path, sample_rate: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data)


def decode_pcm(encoded_audio: bytes, audio_format: str, sample_rate: int) -> bytes:
    return bytes(
        open_xiaoai_server.decode_audio(
            encoded_audio,
            format=audio_format,
            sample_rate=sample_rate,
        )
    )


def save_audio_file(
    encoded_audio: bytes,
    audio_format: str,
    output_path: Path,
    sample_rate: int,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if audio_format == "pcm":
        if output_path.suffix.lower() != ".wav":
            output_path = output_path.with_suffix(".wav")
        pcm_audio = decode_pcm(encoded_audio, audio_format, sample_rate)
        save_wav(pcm_audio, output_path, sample_rate)
        return output_path

    if audio_format == "mp3" and output_path.suffix.lower() != ".mp3":
        output_path = output_path.with_suffix(".mp3")
    if audio_format == "ogg_opus" and output_path.suffix.lower() not in {".ogg", ".opus"}:
        output_path = output_path.with_suffix(".ogg")

    output_path.write_bytes(encoded_audio)
    return output_path


def main() -> None:
    args = parse_args()
    text = read_text(args)
    tts = build_tts(args)
    audio_format = tts.resolve_audio_format(text)
    output_path = resolve_output_path(args, text, audio_format)

    print("=" * 60)
    print("Doubao TTS Audio Generator")
    print("=" * 60)
    print(f"Speaker     : {tts.speaker}")
    print(f"Resource ID : {tts.resource_id}")
    print(f"Format      : {audio_format}")
    print(f"Speed       : {args.speed}")
    print(f"Emotion     : {args.emotion or '-'}")
    print(f"Output      : {output_path}")
    print(f"Text Length : {len(text)}")

    encoded_audio = fetch_encoded_audio(
        tts=tts,
        text=text,
        audio_format=audio_format,
        speed=args.speed,
        emotion=args.emotion,
        sample_rate=args.sample_rate,
    )
    saved_path = save_audio_file(
        encoded_audio=encoded_audio,
        audio_format=audio_format,
        output_path=output_path,
        sample_rate=args.sample_rate,
    )

    print("\nDone")
    print(f"Saved file  : {saved_path}")
    print(f"Encoded Size: {len(encoded_audio):,} bytes")


if __name__ == "__main__":
    main()
