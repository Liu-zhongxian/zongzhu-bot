"""Grok Bot Webhook submission, plus the wake-phrase helpers the gateway uses (see core/gateway/agents/grok_webhook.py)."""
import json
import re
import secrets
import time
import uuid
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

import httpx
from core.handle.grokBotReply import prepare_reply


PREFIX = re.compile(r"^(?:请)?让\s*(?:grok\s*bot|bot|机器人|波特|博特)[\s，,:：]*", re.I)
_recent = OrderedDict()

# The firmware's default wake word; always matched besides the one the board reports.
DEFAULT_WAKE_WORD = "你好宗主"
_GREETINGS = ("你好", "您好")
# Near-sound chars pypinyin's main reading misses but ASR returned (属 is zhǔ in 属意).
_EXTRA_SIMILAR = {"主": "属"}
_FILLER = set("个啊呀嗯哦诶唉哎嘿那")
_PUNCT = re.compile(r"[\s，。！？、,.!?~～:：]+")


def _fold(syllable):
    """Pinyin without the distinctions ASR often loses: z/zh, c/ch, s/sh, n/l, en/eng, in/ing."""
    for retroflex in ("zh", "ch", "sh"):
        if syllable.startswith(retroflex):
            syllable = syllable[0] + syllable[2:]
            break
    if syllable.startswith("n") and syllable not in ("n", "ng"):
        syllable = "l" + syllable[1:]
    return syllable[:-1] if syllable.endswith(("eng", "ing")) else syllable


@lru_cache(maxsize=1)
def _chars_by_sound():
    """Every GB2312 hanzi grouped by its folded main reading (built once, ~30 ms)."""
    from pypinyin import Style, pinyin

    table = {}
    for high in range(0xB0, 0xF8):
        for low in range(0xA1, 0xFF):
            try:
                char = bytes([high, low]).decode("gb2312")
            except UnicodeDecodeError:
                continue
            table.setdefault(_fold(pinyin(char, style=Style.NORMAL)[0][0]), set()).add(char)
    return table


@lru_cache(maxsize=512)
def _similar(char, extra=""):
    """`char` and the chars ASR may write for it ("中猪" for "宗主"), plus configured `extra`."""
    from pypinyin import Style, pinyin

    table = _chars_by_sound()
    readings = pinyin(char, style=Style.NORMAL, heteronym=True)[0]
    return frozenset({char, *extra, *_EXTRA_SIMILAR.get(char, ""),
                      *(c for r in readings for c in table.get(_fold(r), ()))})


def _is_latin(char):
    return char.isascii() and char.isalnum()


def _match_word(raw, i, word):
    """End index of `word` at raw[i:], ignoring punctuation and letter case; None if absent.

    A Latin word must end on a word boundary ("hi esp" is not in "hi espresso").
    """
    word = _PUNCT.sub("", word).casefold()
    for char in word:
        while i < len(raw) and _PUNCT.match(raw[i]):
            i += 1
        if i >= len(raw) or raw[i].casefold() != char:
            return None
        i += 1
    if word and _is_latin(word[-1]) and i < len(raw) and _is_latin(raw[i]):
        return None
    return i


def _split_greeting(word):
    """("你好", "宗主") for "你好宗主"; None for a word without a greeting or name."""
    greeting = next((g for g in _GREETINGS if word.startswith(g)), None)
    return (greeting, word[len(greeting):]) if greeting and len(word) > len(greeting) else None


def _fuzzy_name_end(raw, j, name, similar):
    """End index of a misheard `name` at raw[j:] ("中猪" for "宗主"); None if absent.

    The first char must be at j; one stray char may sit between the others ("中x主").
    """
    if j >= len(raw) or raw[j] not in _similar(name[0], similar.get(name[0], "")):
        return None
    end, skipped = j + 1, False
    for char in name[1:]:
        chars = _similar(char, similar.get(char, ""))
        if end < len(raw) and raw[end] in chars:
            end += 1
        elif not skipped and end + 1 < len(raw) and raw[end + 1] in chars:
            end, skipped = end + 2, True
        else:
            return None
    # A trailing filler right after the name ("中猪公") belongs to the wake phrase.
    if not skipped and end < len(raw) and raw[end] in _FILLER | set("公"):
        end += 1
    return end


def _wake_end(raw, wake_words, similar):
    """End index of one leading, possibly misheard wake phrase in `raw`; None if absent."""
    i = 0
    while i < len(raw) and (raw[i] in _FILLER or _PUNCT.match(raw[i])):
        i += 1
    for word in wake_words:
        end = _match_word(raw, i, word)
        if end is not None:
            return end
    split = [s for s in map(_split_greeting, wake_words) if s]
    # A bare name only counts on its own ("宗主。你好宗主"), not as the start of a sentence.
    for _, name in split:
        end = _match_word(raw, i, name)
        if end is not None and (end == len(raw) or _PUNCT.match(raw[end])):
            return end
    if not raw.startswith(_GREETINGS, i):
        return None
    j = i + 2
    while j < len(raw) and _PUNCT.match(raw[j]):
        j += 1
    for _, name in split:
        end = _fuzzy_name_end(raw, j, name, similar)
        if end is not None:
            return end
    return None


def wake_options(conn):
    """strip_wake_phrase keyword arguments for this connection: the board's wake word and the
    near-sound chars added in config (`gateway.similar_chars`, e.g. {"宗": "粽"})."""
    wake = getattr(conn, "device_wake_word", None)
    similar = ((getattr(conn, "config", None) or {}).get("gateway") or {}).get("similar_chars")
    return {"wake_words": [wake] if wake else (), "similar": similar or {}}


def strip_wake_phrase(text, wake_words=(), similar=None):
    """Return (had_wake_phrase, remainder) for leading, possibly misheard wake phrases.

    `wake_words` (e.g. the one the board reported) and DEFAULT_WAKE_WORD are matched
    exactly; "你好<name>" words also match a name ASR misheard as near-sound chars
    (pypinyin, plus `similar` {char: extra chars}). Repeats are all removed: a wake word
    said again while the board listens can come back as "宗主。你好宗主。" (2026-10-25).
    """
    words = list(dict.fromkeys(w.strip() for w in [*wake_words, DEFAULT_WAKE_WORD] if w and w.strip()))
    similar = {k: str(v) for k, v in (similar or {}).items()}
    rest = text.strip()
    had = False
    while (end := _wake_end(rest, words, similar)) is not None:
        had, rest = True, rest[end:].strip()
    return (True, _PUNCT.sub(" ", rest).strip()) if had else (False, text)


def extract_command(text):
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            text = value.get("content", text)
    except (ValueError, TypeError):
        pass
    if not isinstance(text, str):
        return None
    match = PREFIX.match(text.strip())
    return text.strip()[match.end():].strip() if match else text.strip()


class Submission:
    def __init__(self, url, token, payload, pending, key):
        self.url, self.token, self.payload, self.pending, self.key = url, token, payload, pending, key


def prepare_submission(command, device, config_file):
    """Local checks before anything is sent: a str is the reason it will not be sent."""
    if not command.strip("，。！？,.!? "):
        return "请说出你要交给 Bot 的事情。"
    if len(command) > 2000:
        return "指令太长了，请分成短一点的任务。"
    try:
        config = json.loads(Path(config_file).read_text())
        url, token = config["url"], config["token"]
        if not url.startswith("https://") or not token:
            raise ValueError("Invalid webhook configuration")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return "Bot 连接配置不可用，任务未提交，请检查电脑上的配置文件。"

    now = time.monotonic()
    key = (device, re.sub(r"[\s，。！？,.!?]", "", command).casefold())
    if key in _recent and now - _recent[key] < 30:
        return "刚才已尝试提交同一条指令，已阻止重复发送。请在 Bot 对话里查看。"
    _recent[key] = now
    _recent.move_to_end(key)
    while len(_recent) > 128:
        _recent.popitem(last=False)

    request_id = "ESP32-" + uuid.uuid4().hex
    payload = {"command": command, "request_id": request_id,
               "device": device, "source": "zongzhu-voice"}
    pending = None
    reply_url = config.get("reply_url")
    if reply_url and not str(reply_url).startswith("https://"):
        _recent.pop(key, None)
        return "Bot 回传地址必须是 HTTPS，任务未提交，请检查电脑上的配置。"
    if config.get("reply_dir"):
        reply_token = secrets.token_urlsafe(24) if reply_url else None
        try:
            pending, target = prepare_reply(config["reply_dir"], request_id, device, reply_token)
        except (OSError, ValueError, TypeError):
            _recent.pop(key, None)
            return "Bot 回传目录不可用，任务未提交，请检查电脑上的配置。"
        payload["user_text"] = command
        intro = ("以下是用户对宗主板子说的对话，请处理并在当前硬件对话回复：\n"
                 + json.dumps(command, ensure_ascii=False))
    if pending and reply_url:
        payload["command"] = (
            intro
            + "\n完成后还需要把实际回复回传到板子屏幕：在你的执行环境里把下面的 JSON 写入文件 reply.json（UTF-8），"
            "把 text 换成给用户的实际回复：\n"
            + json.dumps({"request_id": request_id, "token": reply_token, "text": "这里填写给用户的实际回复"}, ensure_ascii=False)
            + "\n然后运行：curl -sS -X POST " + reply_url
            + " -H 'Content-Type: application/json' --data-binary @reply.json"
            + "\n返回 {\"ok\": true, ...} 表示成功；返回其他内容请在原对话说明，不要换别的方式回传。"
            "text 使用中文纯文本，保留回答的主要内容，不要只写已收到或已完成；"
            "较长结果请给出最多2000字的可读摘要，完整版保留在原对话。"
            "这个 token 只用于本次回传，不要在对话中展示。回传成功后正常回复用户。"
        )
    elif pending:
        payload["command"] = (
            intro
            + "\n完成后还需要把实际回复回传到板子屏幕。使用已有且获准的本机文件或本机终端能力，"
            "在用户 Mac 写入 UTF-8 JSON 文件（不能只写云端同名路径）：" + str(target)
            + "\nJSON 格式：" + json.dumps({"request_id": request_id, "text": "这里填写给用户的实际回复"}, ensure_ascii=False)
            + "\ntext 使用中文纯文本，保留回答的主要内容，不要只写已收到或已完成；"
            "较长结果请给出最多2000字的可读摘要，完整版保留在原对话。"
            "请先写同目录临时文件再重命名为目标文件，避免读取半写入内容。"
            "之后对这件事还有补充、更正或新结果（例如转给别的 Bot 后它回复了），再按同样格式写到同目录的 "
            + request_id + ".more-1.json，第二次写 .more-2.json，依此类推，板子会接着念出来。"
            "不要为回传修改任何权限设置；若本机能力不可用，请在原对话说明。"
            "回传成功后正常回复用户，不必在对话中展示文件路径。"
        )
    return Submission(url, token, payload, pending, key)


async def post_submission(submission, transport=None):
    """Send the Webhook; returns (status, message), status is accepted / rejected / unknown."""
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, transport=transport) as client:
            response = await client.post(submission.url, json=submission.payload,
                                         headers={"Authorization": "Bearer " + submission.token})
        if 400 <= response.status_code < 500:
            _recent.pop(submission.key, None)
            if submission.pending:
                submission.pending.unlink(missing_ok=True)
            return "rejected", "Bot 服务拒绝了请求，任务未提交，请检查连接配置或稍后再试。"
        data = response.json() if response.is_success else {}
        if data.get("success") is True and data.get("runUuid"):
            if submission.pending:
                return "accepted", "任务已提交，Bot 回复后会显示在屏幕上。"
            return "accepted", "任务已提交给 Bot，执行结果请在 Grok Bot 对话里查看。"
    except (httpx.HTTPError, OSError, ValueError, AttributeError):
        pass
    # A timeout or malformed reply cannot establish whether the Bot accepted it.
    return "unknown", "暂时无法确认任务是否提交，请先查看 Bot 对话，避免重复发送。"


async def submit_command(command, device, config_file, transport=None):
    submission = prepare_submission(command, device, config_file)
    if isinstance(submission, str):
        return submission
    return (await post_submission(submission, transport))[1]
