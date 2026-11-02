"""Settings changed on the gateway page (G8b step 5), kept in data/gateway_settings.json.

2026-11-02 你定：唤醒词、呼名在网关页面上改，不让人去手改 .config.yaml。页面上改过的值比配置文件优先；
没改过的照旧用配置文件（再没有就用代码里的默认值）。现在有：
- "speaker_wake_words": [词, ...]          小米音箱的唤醒词（gateway.xiaoai.wake_words）
- "call_names": {AI 模块名: [称呼, ...]}   每个 AI 的呼名（gateway.call_names）
Written atomically, like agent_store.py.
"""
import json
import os
import re
import tempfile
import threading
from pathlib import Path

PATH = Path("data") / "gateway_settings.json"  # relative to the server directory, like .config.yaml
MAX_WORDS = 10
MAX_LENGTH = 20
# A wake word or call name: Chinese characters, letters, digits and spaces
_WORD = re.compile(r"^[一-鿿A-Za-z0-9 ]+$")

_lock = threading.Lock()


class SettingError(Exception):
    pass


def _read_all() -> dict:
    try:
        with open(PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_all(data: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=PATH.parent, prefix=".gateway_settings.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PATH)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def get(key, default=None):
    with _lock:
        return _read_all().get(key, default)


def put(key, value) -> None:
    with _lock:
        data = _read_all()
        data[key] = value
        _write_all(data)


def words(value, allow_empty=False) -> list:
    """A list of words from the page ("宗主, bot" or a list): trimmed, duplicates dropped, checked."""
    if isinstance(value, str):
        value = re.split(r"[,，、;；\n]+", value)
    if not isinstance(value, list):
        raise SettingError("格式不对")
    result = []
    for word in value:
        word = re.sub(r"\s+", " ", str(word)).strip()
        if not word or word.lower() in (w.lower() for w in result):
            continue
        if len(word) > MAX_LENGTH or not _WORD.match(word):
            raise SettingError(f"「{word[:MAX_LENGTH]}」不行：只能用汉字、字母、数字，最多 {MAX_LENGTH} 个字")
        result.append(word)
    if not result and not allow_empty:
        raise SettingError("至少要留一个")
    if len(result) > MAX_WORDS:
        raise SettingError(f"最多 {MAX_WORDS} 个")
    return result
