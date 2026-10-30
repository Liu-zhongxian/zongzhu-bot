#!/usr/bin/env python3
"""
Doubao Voice Clone Script
Usage:
  python scripts/clone_voice.py --speaker-id S_xxx --audio sample.wav
  python scripts/clone_voice.py --speaker-id S_xxx --status

Credentials are read from config.py (tts.doubao.app_id / access_key).
"""

import argparse
import base64
import json
import sys
import uuid
from pathlib import Path

import urllib.request
import urllib.error

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _add_venv_site_packages() -> None:
    venv_lib = PROJECT_ROOT / ".venv" / "lib"
    if not venv_lib.exists():
        return
    for site_packages in sorted(venv_lib.glob("python*/site-packages"), reverse=True):
        site_path = str(site_packages)
        if site_path not in sys.path:
            sys.path.insert(0, site_path)
        break


_add_venv_site_packages()

from core.utils.config_loader import ensure_config_module_loaded

ensure_config_module_loaded()
from config import APP_CONFIG

BASE_URL = "https://openspeech.bytedance.com/api/v3/tts"

STATUS_MAP = {
    0: "NotFound",
    1: "Training",
    2: "Success",
    3: "Failed",
    4: "Active",
}

MODEL_TYPE_MAP = {
    1: "ICL 1.0",
    2: "DiT Standard (tone only)",
    3: "DiT Restore (tone + style)",
    4: "ICL 2.0",
}


def get_headers(app_key: str, access_key: str) -> dict:
    return {
        "Content-Type": "application/json",
        "X-Api-App-Key": app_key,
        "X-Api-Access-Key": access_key,
        "X-Api-Request-Id": str(uuid.uuid4()),
    }


def post_json(url: str, headers: dict, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            logid = resp.headers.get("X-Tt-Logid", "")
            return json.loads(body), logid
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        logid = e.headers.get("X-Tt-Logid", "")
        try:
            err = json.loads(raw)
            message = str(err.get('message', ''))[:200]
            msg = f"code={err.get('code')}, message={message}"
        except (json.JSONDecodeError, TypeError):
            msg = raw[:200]
        print(f"HTTP {e.code}: {msg}  (logid={logid})", file=sys.stderr)
        sys.exit(1)


def clone_voice(app_key: str, access_key: str, audio_path: str, speaker_id: str,
                language: int, model_types: list[int], denoise: bool) -> dict:
    audio_bytes = Path(audio_path).read_bytes()
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    suffix = Path(audio_path).suffix.lstrip(".")
    payload = {
        "speaker_id": speaker_id,
        "audio": {
            "data": audio_b64,
            "format": suffix or "wav",
        },
        "language": language,
        "extra_params": {
            "enable_audio_denoise": denoise,
        },
    }
    if model_types:
        payload["model_types"] = model_types

    headers = get_headers(app_key, access_key)
    result, logid = post_json(f"{BASE_URL}/voice_clone", headers, payload)
    print(f"[logid] {logid}")
    return result


def get_voice_status(app_key: str, access_key: str, speaker_id: str, print_logid: bool = False) -> dict:
    headers = get_headers(app_key, access_key)
    result, logid = post_json(
        f"{BASE_URL}/get_voice", headers, {"speaker_id": speaker_id}
    )
    if print_logid:
        print(f"[logid] {logid}")
    return result


def print_result(result: dict):
    status_code = result.get("status", -1)
    status_name = STATUS_MAP.get(status_code, f"Unknown({status_code})")
    print(f"status: {status_name}")

    speaker_id = result.get("speaker_id", "unknown")
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    for entry in result.get("speaker_status", []):
        mt = entry.get("model_type")
        label = MODEL_TYPE_MAP.get(mt, f"type {mt}")
        demo = entry.get("demo_audio", "")
        if not demo:
            continue
        if not demo.startswith("http"):
            out_path = output_dir / f"demo_{speaker_id}_model{mt}.mp3"
            out_path.write_bytes(base64.b64decode(demo))
            print(f"  model {mt} ({label}): {out_path}")
        else:
            print(f"  model {mt} ({label}): {demo}")


def main():
    parser = argparse.ArgumentParser(
        description="Doubao voice clone training and status query"
    )
    parser.add_argument("--speaker-id", required=True,
                        help="Speaker ID from Volcengine console (e.g. S_5Q4HPWVU1)")
    parser.add_argument("--audio", help="Path to audio file for cloning")
    parser.add_argument("--status", action="store_true", help="Query clone status only")
    parser.add_argument("--language", type=int, default=0,
                        help="Language: 0=zh, 1=en, 2=ja, 3=es, 4=id, 5=pt, 6=de, 7=fr (default: 0)")
    parser.add_argument("--model-types", type=int, nargs="*",
                        help="Model types to train: 1=ICL1.0 2=DiT-std 3=DiT-restore 4=ICL2.0")
    parser.add_argument("--no-denoise", action="store_true", help="Disable audio denoising")
    args = parser.parse_args()

    tts_config = APP_CONFIG.get("tts", {}).get("doubao", {})
    app_key = tts_config.get("app_id", "")
    access_key = tts_config.get("access_key", "")
    if not app_key or not access_key:
        print("Error: 请先在 config.py 中配置 tts.doubao.app_id / access_key", file=sys.stderr)
        sys.exit(1)

    if args.status:
        result = get_voice_status(app_key, access_key, args.speaker_id, print_logid=True)
        print_result(result)
        print(f"speaker_id: {args.speaker_id}")
        return

    if not args.audio:
        print("Error: --audio is required unless --status is specified", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    if not Path(args.audio).exists():
        print(f"Error: audio file not found: {args.audio}", file=sys.stderr)
        sys.exit(1)

    # Submit clone training
    print(f"Submitting ...", flush=True)
    result = clone_voice(
        app_key, access_key,
        args.audio, args.speaker_id,
        args.language,
        args.model_types or [],
        not args.no_denoise,
    )
    remaining = result.get("available_training_times", "?")
    print(f"remaining: {remaining}")
    print_result(result)
    print(f"speaker_id: {args.speaker_id}")


if __name__ == "__main__":
    main()
