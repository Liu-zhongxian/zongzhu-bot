"""Forward conversation to the user's existing Grok Bot without a chat model."""
import json
import re
import time
import uuid
from collections import OrderedDict
from pathlib import Path

import httpx
from core.handle.grokBotReply import prepare_reply


PREFIX = re.compile(r"^(?:请)?让\s*(?:grok\s*bot|bot|机器人|波特|博特)[\s，,:：]*", re.I)
_recent = OrderedDict()


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


async def submit_command(command, device, config_file, transport=None):
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
    if config.get("reply_dir"):
        try:
            pending, target = prepare_reply(config["reply_dir"], request_id, device)
        except (OSError, ValueError, TypeError):
            _recent.pop(key, None)
            return "Bot 回传目录不可用，任务未提交，请检查电脑上的配置。"
        payload["user_text"] = command
        payload["command"] = (
            "以下是用户对宗主板子说的对话，请处理并在当前硬件对话回复：\n"
            + json.dumps(command, ensure_ascii=False)
            + "\n完成后还需要把实际回复回传到板子屏幕。使用已有且获准的本机文件或本机终端能力，"
            "在用户 Mac 写入 UTF-8 JSON 文件（不能只写云端同名路径）：" + str(target)
            + "\nJSON 格式：" + json.dumps({"request_id": request_id, "text": "这里填写给用户的实际回复"}, ensure_ascii=False)
            + "\ntext 使用中文纯文本，保留回答的主要内容，不要只写已收到或已完成；"
            "较长结果请给出最多2000字的可读摘要，完整版保留在原对话。"
            "请先写同目录临时文件再重命名为目标文件，避免读取半写入内容。"
            "不要为回传修改任何权限设置；若本机能力不可用，请在原对话说明。"
            "回传成功后正常回复用户，不必在对话中展示文件路径。"
        )
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, transport=transport) as client:
            response = await client.post(url, headers={"Authorization": "Bearer " + token}, json=payload)
        if 400 <= response.status_code < 500:
            _recent.pop(key, None)
            if pending:
                pending.unlink(missing_ok=True)
            return "Bot 服务拒绝了请求，任务未提交，请检查连接配置或稍后再试。"
        data = response.json() if response.is_success else {}
        if data.get("success") is True and data.get("runUuid"):
            if pending:
                return "任务已提交，Bot 回复后会显示在屏幕上。"
            return "任务已提交给 Bot，执行结果请在 Grok Bot 对话里查看。"
    except (httpx.HTTPError, OSError, ValueError, AttributeError):
        pass
    # A timeout or malformed reply cannot establish whether the Bot accepted it.
    return "暂时无法确认任务是否提交，请先查看 Bot 对话，避免重复发送。"


async def handle_grok_bot(conn, text):
    config = conn.config.get("grok_bot", {})
    command = extract_command(text)
    if not config.get("enabled") or command is None:
        return False
    # Wake phrases use the local cached greeting; they are not Bot tasks.
    if re.sub(r"[\W_]", "", command) in conn.config.get("wakeup_words", []):
        return False
    from core.handle.sendAudioHandle import send_stt_message
    from core.handle.intentHandler import speak_txt

    conn.bot_input_until = 0
    conn.client_abort = False
    conn.sentence_id = uuid.uuid4().hex
    await send_stt_message(conn, text)
    reply = await submit_command(command, conn.headers.get("device-id", "unknown"),
                                 config.get("config_file", ""))
    if not conn.client_abort:
        speak_txt(conn, reply)
    return True
