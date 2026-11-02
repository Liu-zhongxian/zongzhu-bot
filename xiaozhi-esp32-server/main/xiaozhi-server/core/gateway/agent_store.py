"""Which AI each board uses now, kept in data/agent_sessions.json across reconnects and restarts.

The file layout follows xiaozhi-hub-server `core/agent/session_store.py` (commit adb936d, MIT):
{namespace: {device: {..., "last_active": time}}}, written atomically. Only the part we need.
"""
import json
import os
import tempfile
import threading
import time
from pathlib import Path

PATH = Path("data") / "agent_sessions.json"  # relative to the server directory, like .config.yaml
NAMESPACE = "gateway_agent"

_lock = threading.Lock()


def _read_all() -> dict:
    try:
        with open(PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_all(data: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=PATH.parent, prefix=".agent_sessions.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PATH)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def get(device) -> str:
    """The AI this board last chose by name, or ''."""
    with _lock:
        record = _read_all().get(NAMESPACE, {}).get(device) or {}
    return record.get("agent", "") if isinstance(record, dict) else ""


def put(device, agent) -> None:
    with _lock:
        data = _read_all()
        data.setdefault(NAMESPACE, {})[device] = {"agent": agent, "last_active": time.time()}
        _write_all(data)
