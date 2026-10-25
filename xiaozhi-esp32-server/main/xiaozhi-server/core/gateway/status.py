"""What the gateway page shows: boards, live connections and the last sentences. Memory only.

Nothing here holds keys, tokens or request headers; the page is open to the whole LAN.
"""
import re
import time
from collections import deque

RECENT_MAX = 30
# Board types the firmware reports in OTA (board.type) -> the names used in our docs
BOARD_NAMES = (("lichuang", "立创实战派"), ("amoled-1.75", "微雪 1.75C"), ("stopwatch", "M5Stack StopWatch"))
# Types our check scripts use (tools/verify, probes): shown only while connected
SIMULATED_TYPES = {"local-test", "probe"}
AGENT_NAMES = {"grok_bot": "Grok Bot"}

_started = time.time()
_boards = {}  # device id -> what its last OTA request said
_conns = {}  # id(conn) -> conn, live WebSocket connections
_recent = deque(maxlen=RECENT_MAX)
_totals = {"sentences": 0, "local": 0}


def board_name(board_type):
    for key, name in BOARD_NAMES:
        if key in (board_type or ""):
            return name
    return board_type or "未知板子"


def note_ota(device_id, board_type, version, ip):
    _boards[device_id] = {"type": board_type, "version": version, "ip": ip, "seen": time.time()}


def connected(conn):
    _conns[id(conn)] = conn


def disconnected(conn):
    _conns.pop(id(conn), None)
    if conn.device_id in _boards:
        _boards[conn.device_id]["seen"] = time.time()


def note_asr(conn, before, after, started=None):
    """Recognised text before and after the correction table, for the sentence that follows.

    `started` (time.monotonic()) is when recognition began, i.e. when the speaker stopped;
    the time to sound is counted from there.
    """
    conn.gateway_asr = (before or "", after or "", started)


def classify(conn, text):
    """'wake' for the wake greeting, 'filter' for a repeated wake word only, else None."""
    from core.handle.grokBotHandle import extract_command, strip_wake_phrase

    command = extract_command(text) or ""
    wake = getattr(conn, "device_wake_word", None)
    if re.sub(r"[\W_]", "", command) in [*conn.config.get("wakeup_words", []), wake]:
        return "wake"
    had, rest = strip_wake_phrase(command, [wake] if wake else ())
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
        _totals["local"] += layer in ("skill", "filter")


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
            "wake": (getattr(conn, "device_wake_word", None) if conn else None) or "",
            "agent": AGENT_NAMES.get(agent, agent or "上游对话"),
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
