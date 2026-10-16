#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
export PATH="/opt/homebrew/bin:$PATH"
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:${DYLD_FALLBACK_LIBRARY_PATH:-}"
cd "$ROOT/xiaozhi-esp32-server/main/xiaozhi-server"
exec "$ROOT/.venv/bin/python" app.py
