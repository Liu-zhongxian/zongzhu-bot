"""G17：网关页面"转交任务"：交给 Bot 的话、它的回复、念了没有。只读 Bot 的回传目录，不改文件。

回传目录里每个请求一个记录（core/handle/grokBotReply.py）：提交时 `<id>.pending.json`
（设备、时间、问的话），Bot 写回 `<id>.json`（回复），念给板子后 pending 改名 `<id>.sent.json`；
Bot 的补充是 `<id>.more-<n>.json`。由此分四种：
- running  已提交、还没回复、还在等待时限内（reply_wait_seconds，板子显示等待也用它）
- report   回复到了还没念（板子在说话、待机，或者在等你说新问题）
- done     念过了
- timeout  过了等待时限还没回复（一天内晚到的回复照样念）
只看最近 24 小时，每种最多 MAX_ITEMS 条；结果存 CACHE_SECONDS 秒。
"""
import json
import re
import time
from pathlib import Path

WINDOW_SECONDS = 24 * 3600
MAX_ITEMS = 30
TEXT_MAX = 300
CACHE_SECONDS = 2
_cache = {"at": 0.0, "tasks": None}
_ID = re.compile(r"(ESP32-[0-9a-f]{32})\.(pending|sent)\.json")


def _read(path, limit=65536):
    if path.is_symlink() or path.stat().st_size > limit:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _reply(directory, request_id):
    """(回复文字, 什么时候到的) 或 (None, None)；Bot 的补充接在后面"""
    texts, at = [], None
    for path in [directory / f"{request_id}.json",
                 *sorted(directory.glob(f"{request_id}.more-*.json"), key=lambda p: p.stat().st_mtime)]:
        try:
            data = _read(path)
        except (OSError, ValueError):
            continue
        if data and data.get("request_id") == request_id and isinstance(data.get("text"), str):
            texts.append(data["text"].strip())
            at = at or path.stat().st_mtime
    return ("\n".join(texts), at) if texts else (None, None)


def collect(config, names, now=None) -> dict:
    """{"running": [...], "report": [...], "done": [...], "timeout": [...]}，没开 Bot 或没配回传目录时 None。
    names：设备 ID → 板子名字（网关页面上的）。"""
    now = time.time() if now is None else now
    bot = config.get("grok_bot") or {}
    if not bot.get("enabled"):
        return None
    try:
        webhook = json.loads(Path(bot.get("config_file", "")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not webhook.get("reply_dir"):
        return None
    from core.handle.grokBotReply import REPLY_WAIT_SECONDS

    directory = Path(webhook["reply_dir"])
    wait = webhook.get("reply_wait_seconds", REPLY_WAIT_SECONDS)
    groups = {"running": [], "report": [], "done": [], "timeout": []}
    for path in directory.glob("ESP32-*.json"):
        match = _ID.fullmatch(path.name)
        if not match:
            continue
        try:
            record = _read(path, 4096)
            created = float(record["created"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not 0 <= now - created < WINDOW_SECONDS:
            continue
        request_id, kind = match.groups()
        text, replied_at = _reply(directory, request_id)
        if kind == "sent":
            state = "done"
        elif text is not None:
            state = "report"
        else:
            state = "running" if now - created < wait else "timeout"
        question = record.get("question")
        groups[state].append({
            "id": request_id[-6:], "board": names.get(record.get("device"), "") or "未知设备",
            "question": question if isinstance(question, str) else "",
            "created": created, "replied": replied_at,
            "reply": text[:TEXT_MAX] + ("……" if len(text) > TEXT_MAX else "") if text else "",
        })
    for items in groups.values():
        items.sort(key=lambda t: t["created"], reverse=True)
        del items[MAX_ITEMS:]
    return groups


def cached(config, names) -> dict:
    if time.monotonic() - _cache["at"] > CACHE_SECONDS:
        _cache["tasks"], _cache["at"] = collect(config, names), time.monotonic()
    return _cache["tasks"]
