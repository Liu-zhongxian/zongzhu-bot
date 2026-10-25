"""呼名：句首"嗨 / 嘿 + 称呼"（如"嗨 孙悟空"）指定交给哪个 AI。

匹配规则照搬 justhalfbit/xiaozhi-hub-server `core/agent/call_names.py`（commit adb936d，MIT）：
招呼语的写法来自它的真机实测（"嘿"常被识别成 he、h，后面偶尔带日文假名）；称呼后面紧跟英文字母
不算（"嗨 Grok Bot 怎么配置"里的 Grok 不是在叫人）；连说两遍一起去掉。hub 的录入别名、管理后台和
按模型切换的部分没有搬，切换和记住由网关做（core/gateway/__init__.py、agent_store.py）。

称呼来自每个 AI 模块的 `call_names`，配置 `gateway.call_names: {模块名: [称呼, ...]}` 可以整个替换。
"""
import re

# "嘿"常被识别成 he，有时后面还带一个日文假名，偶尔只剩一个 h（hub 实测 "He cloud."、"Heい cloud。"、"H, cloud."）
_PREFIXES = ["hiigh", "high", "hey", "hei", "hai", "hi", "he", "h", "嗨", "嘿"]
# 单个 h 后面必须是停顿，否则 "hello"、"haiku" 这类词开头的 h 会被当成招呼语
_PREFIX = "(?:" + "|".join(p if p != "h" else r"h(?=[\s,，.。!！?？、~～])" for p in _PREFIXES) + r")[぀-ヿ]*"
_SEP = r"[\s,，.。!！?？、~～]*"


def _alias_pattern(alias: str) -> str:
    # 称呼后面不能紧跟（或隔着空格跟）英文字母：避免"grokking"、"Grok Bot 怎么用"被当成称呼
    return re.escape(alias) + r"(?!\s*[a-z])"


def _aliases(value) -> list:
    """配置里的称呼应是列表；写成单个字符串时当作一个称呼，不能拆成单个字符。"""
    if isinstance(value, str):
        value = [value]
    return [str(a).strip().lower() for a in (value or []) if str(a).strip()]


def _build(names: dict) -> list:
    result = []
    for agent, value in names.items():
        aliases = _aliases(value)
        if aliases:
            alternatives = "|".join(_alias_pattern(a) for a in sorted(aliases, key=len, reverse=True))
            result.append((agent, re.compile(r"^" + _SEP + _PREFIX + _SEP + "(?:" + alternatives + ")" + _SEP,
                                             re.IGNORECASE)))
    return result


def match_call_name(text: str, names: dict):
    """句首是称呼时返回 (AI 模块名, 去掉称呼后的文字)，文字为空表示整句话只有称呼；不是称呼返回 None。

    `names` 是 {模块名: [称呼, ...]}。连说两遍称呼（hub 实测出现过 "Hi, cloud. Hi, cloud."）也一并去掉。
    """
    patterns = _build(names)
    found = None
    rest = text or ""
    while True:
        for agent, pattern in patterns:
            m = pattern.match(rest)
            if m:
                found, rest = agent, rest[m.end():]
                break
        else:
            break
    if found is None:
        return None
    return found, rest.strip()
