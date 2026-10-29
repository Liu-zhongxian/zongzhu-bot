"""What the gateway page shows: boards, live connections and the last sentences.

The board list is kept in data/gateway_boards.json, so a board stays on the page (as not
connected) across backend restarts: since the fixed auth_key a board no longer reboots, so it
sends no OTA request after a restart. Live connections and the last sentences are memory only.
Nothing here holds keys, tokens or request headers; the page is open to the whole LAN.
"""
import json
import os
import re
import tempfile
import time
from collections import deque
from pathlib import Path

RECENT_MAX = 30
# Board types the firmware reports in OTA (board.type) -> the names used in our docs
BOARD_NAMES = (("lichuang", "立创实战派"), ("amoled-1.75", "微雪 1.75C"), ("stopwatch", "M5Stack StopWatch"))
# Types our check scripts use (tools/verify, probes): shown only while connected
SIMULATED_TYPES = {"local-test", "probe"}

BOARDS_PATH = Path("data") / "gateway_boards.json"  # relative to the server directory

_started = time.time()
_boards = {}  # device id -> type, version (from OTA), ip, wake word, last seen
_conns = {}  # id(conn) -> conn, live WebSocket connections
_recent = deque(maxlen=RECENT_MAX)
_totals = {"sentences": 0, "local": 0}


def board_name(board_type):
    for key, name in BOARD_NAMES:
        if key in (board_type or ""):
            return name
    return board_type or "未知板子"


def load():
    try:
        data = json.loads(BOARDS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(data, dict):
        _boards.update({k: v for k, v in data.items() if isinstance(v, dict)})


def _save():
    real = {k: v for k, v in _boards.items() if v.get("type") not in SIMULATED_TYPES}
    try:
        BOARDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=BOARDS_PATH.parent, prefix=".gateway_boards.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(real, f, ensure_ascii=False, indent=2)
        os.replace(tmp, BOARDS_PATH)
    except OSError:
        pass  # the page is only a view; never let it break a connection


def note_ota(device_id, board_type, version, ip):
    _boards.setdefault(device_id, {}).update(type=board_type, version=version, ip=ip, seen=time.time())
    _save()


def connected(conn):
    _conns[id(conn)] = conn
    if conn.device_id:
        _boards.setdefault(conn.device_id, {}).update(ip=getattr(conn, "client_ip", "") or "", seen=time.time())
        _save()


def disconnected(conn):
    _conns.pop(id(conn), None)
    if conn.device_id in _boards:
        _boards[conn.device_id]["seen"] = time.time()
        wake = getattr(conn, "device_wake_word", None)
        if wake:
            _boards[conn.device_id]["wake"] = wake
        _save()


def note_asr(conn, before, after, started=None):
    """Recognised text before and after the correction table, for the sentence that follows.

    `started` (time.monotonic()) is when recognition began, i.e. when the speaker stopped;
    the time to sound is counted from there.
    """
    conn.gateway_asr = (before or "", after or "", started)


def classify(conn, text):
    """'wake' for the wake greeting, 'filter' for a repeated wake word only, else None."""
    from core.handle.grokBotHandle import extract_command, strip_wake_phrase, wake_options

    command = extract_command(text) or ""
    wake = getattr(conn, "device_wake_word", None)
    if re.sub(r"[\W_]", "", command) in [*conn.config.get("wakeup_words", []), wake]:
        return "wake"
    had, rest = strip_wake_phrase(command, **wake_options(conn))
    return "filter" if had and not rest.strip("，。！？,.!? ") else None


def not_sent_reason(message):
    """Short page label for an AI's reason not to submit (the full sentence was spoken)."""
    return "拦下重复" if message.startswith("刚才已尝试提交") else "没提交"


def begin(conn, text):
    raw, fixed, started = getattr(conn, "gateway_asr", ("", "", None))
    conn.gateway_asr = ("", "", None)
    plain = lambda s: re.sub(r"\s", "", s)
    changed = raw and plain(fixed) == plain(text) and plain(raw) != plain(fixed)
    record = {"time": time.time(), "device": getattr(conn, "device_id", None), "text": text,
              "raw": raw if changed else "",
              "layer": "upstream", "target": "上游对话", "first_audio": None, "_t": started or time.monotonic()}
    _recent.appendleft(record)
    conn.gateway_record = record
    return record


def finish(record, layer, target):
    record["layer"], record["target"] = layer, target
    if layer not in ("wake",):
        _totals["sentences"] += 1
        _totals["local"] += layer in ("skill", "filter", "call")


def note_audio(conn):
    """First audio packet after a sentence: how long the board waited for sound."""
    record = getattr(conn, "gateway_record", None)
    if record is not None and record["first_audio"] is None:
        record["first_audio"] = round(time.monotonic() - record["_t"], 2)


def _state(conn, now):
    if getattr(conn, "bot_ui_waiting", False):
        since = max(getattr(conn, "bot_ui_seen_at", 0) or 0, getattr(conn, "gateway_wait_since", 0) or 0)
        return {"kind": "waiting", "seconds": int(now - since) if since else None}
    if getattr(conn, "client_is_speaking", False):
        return {"kind": "speaking"}
    return {"kind": "listening"}


def _agent(conn, device_id, configured):
    """The board's AI: chosen by calling its name (this connection or saved), else the configured one."""
    from core.gateway import agent_store

    chosen = getattr(conn, "gateway_agent", None) if conn else None
    return chosen or agent_store.get(device_id) or configured


def _agent_label(name, config):
    from core.gateway import AGENTS

    agent = AGENTS.get(name)
    return agent.label(config) if agent else (name or "上游对话")


def snapshot(config):
    now = time.time()
    gateway = config.get("gateway") or {}
    agent = gateway.get("agent", "grok_bot") or None
    live = {}
    for conn in list(_conns.values()):
        if conn.device_id:
            live.setdefault(conn.device_id, []).append(conn)
    names = {}
    boards = []
    for device_id in {*_boards, *live}:
        info = _boards.get(device_id, {})
        conns = live.get(device_id, [])
        name = board_name(info["type"]) if info.get("type") else "板子 " + device_id[-5:]
        if info.get("type") in SIMULATED_TYPES:
            name = "模拟板子（检查脚本）"
        names[device_id] = name
        if not conns and info.get("type") in SIMULATED_TYPES:
            continue
        conn = conns[-1] if conns else None
        boards.append({
            "id": device_id[-5:], "name": name, "type": info.get("type", ""), "version": info.get("version", ""),
            "ip": (conn.client_ip if conn else None) or info.get("ip", ""), "online": bool(conns),
            "wake": (getattr(conn, "device_wake_word", None) if conn else None) or info.get("wake", ""),
            "agent": _agent_label(_agent(conn, device_id, agent), config),
            "state": _state(conn, now) if conn else {"kind": "offline"},
            "seen": info.get("seen"),
        })
    boards.sort(key=lambda b: (not b["online"], b["name"]))
    recent = [{k: v for k, v in r.items() if not k.startswith("_")} | {"board": names.get(r["device"], "")}
              for r in _recent]
    for r in recent:
        r.pop("device", None)
    return {"now": now, "uptime": int(now - _started), "port": int(config.get("server", {}).get("http_port", 8003)),
            "boards": boards, "recent": recent, "totals": dict(_totals)}


load()
