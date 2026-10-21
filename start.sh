#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
export PATH="/opt/homebrew/bin:$PATH"
# ffmpeg-full is keg-only: it is not in /opt/homebrew/bin unless linked.
if ! command -v ffmpeg >/dev/null 2>&1 && [ -x /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg ]; then
  export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
fi
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:${DYLD_FALLBACK_LIBRARY_PATH:-}"
cd "$ROOT/xiaozhi-esp32-server/main/xiaozhi-server"
exec "$ROOT/.venv/bin/python" app.py
