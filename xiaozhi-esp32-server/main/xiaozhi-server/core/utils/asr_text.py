"""语音识别的文字处理：整理空格、识别后纠错、热词。

写法参考 justhalfbit/xiaozhi-hub-server 的 core/agent/asr_text.py（MIT），按本项目精简：
去掉管理后台和呼名相关部分，纠错允许中间夹逗号（"你好，中国"）。

纠错：有些词发音几乎一样，换模型、加热词都救不回来，只能在识别出文字后按替换表改正。
替换表是配置顶层的 asr_corrections，格式 {正确写法: [识别错的写法, ...]}，写了就整个覆盖默认表。
匹配时忽略大小写，词与词之间有没有空格、逗号都算；英文开头或结尾的写法要求整词匹配。

热词：配置顶层的 asr_hotwords（列表），写了就整个覆盖默认列表。只有支持热词的识别会用上，
目前是 sherpa-onnx 的 transducer 模型（X-ASR）：解码时给热词加分，只在候选里挑，不会凭空编出词。
"""

import re
import threading

# 默认替换表来自 2026-10-15 至 10-21 后端日志里实际出现的错认
DEFAULT_CORRECTIONS = {
    "你好宗主": ["你好中国", "你好中主", "你好钟主", "你好钟国", "你好宗猪", "你好中猪", "你好中猪公", "你好终主"],
    "宗主": ["中主", "钟主", "宗猪"],
    "Grok Bot": ["Grogbot", "Grokbot", "Grog Bot"],
    "Claude Code": ["cloud code", "clock code", "克劳德扣的", "克拉德扣的"],
}

DEFAULT_HOTWORDS = [
    "宗主", "你好宗主", "Grok", "Grok Bot", "MCP", "GitHub", "Claude", "Claude Code", "README", "JSON",
    "Python", "Docker", "VS Code", "Markdown", "ESP32", "OTA", "WebSocket", "commit", "push",
    "issue", "PR", "bug", "AI",
]

_ASCII = re.compile(r"[A-Za-z0-9]")
_TOKEN = re.compile(r"[A-Za-z0-9]+|\S")
_GAP = r"[\s,，、]*"


def _aliases(value) -> list:
    if isinstance(value, str):
        value = [value]
    return [str(a).strip() for a in (value or []) if str(a).strip()]


def _alias_regex(alias: str) -> str:
    tokens = _TOKEN.findall(alias)
    body = _GAP.join(re.escape(t) for t in tokens)
    if _ASCII.match(tokens[0]):
        body = r"(?<![A-Za-z0-9])" + body
    if _ASCII.match(tokens[-1]):
        body = body + r"(?![A-Za-z0-9])"
    return body


_cache = {"key": None, "rules": []}
_cache_lock = threading.Lock()


def _rules(corrections: dict) -> list:
    key = repr(sorted((str(k), tuple(_aliases(v))) for k, v in (corrections or {}).items()))
    with _cache_lock:
        if _cache["key"] == key:
            return _cache["rules"]
    pairs = [(alias, str(target).strip()) for target, value in (corrections or {}).items() if str(target).strip()
             for alias in _aliases(value)]
    # 长的写法先替换，避免 "中主" 抢在 "你好中主" 前面
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    rules = [(re.compile(_alias_regex(alias), re.IGNORECASE), target) for alias, target in pairs]
    with _cache_lock:
        _cache["key"], _cache["rules"] = key, rules
    return rules


_PUNCT_SPACE = re.compile(r"\s*([，。？！、；：])\s*")
_SPACED_LETTERS = re.compile(r"(?<![A-Za-z])[A-Z](?: [A-Z])+(?![A-Za-z])")


def tidy(text: str) -> str:
    """X-ASR 会在中文标点后加空格、把逐个念的字母拆开（"A C P"），整理成平常的写法。"""
    text = _PUNCT_SPACE.sub(r"\1", text)
    return _SPACED_LETTERS.sub(lambda m: m.group(0).replace(" ", ""), text).strip()


def corrections_of(config: dict) -> dict:
    value = (config or {}).get("asr_corrections")
    return DEFAULT_CORRECTIONS if value is None else (value or {})


def apply_corrections(text: str, corrections: dict) -> str:
    if not text:
        return text
    for pattern, target in _rules(corrections):
        # 用函数返回替换内容，正确写法里的反斜杠不会被当成正则转义
        text = pattern.sub(lambda _m, t=target: t, text)
    return text


def hotwords_of(config: dict) -> list:
    value = (config or {}).get("asr_hotwords")
    return DEFAULT_HOTWORDS[:] if value is None else _aliases(value)


def fix_asr_result(result, config: dict):
    """整理并纠错识别结果；FunASR 返回 dict（文字在 content），其他识别返回字符串。"""
    corrections = corrections_of(config)
    if isinstance(result, dict):
        if result.get("content"):
            result["content"] = apply_corrections(tidy(result["content"]), corrections)
        return result
    return apply_corrections(tidy(result), corrections) if result else result
