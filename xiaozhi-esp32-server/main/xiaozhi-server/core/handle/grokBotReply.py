"""Local result files bridge the existing Bot back to device speech and subtitles."""
import asyncio
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from pathlib import Path


_delivery_lock = asyncio.Lock()
# Bot replies usually take longer than the idle timeout, so a session with an
# outstanding request stays open for up to this long.
REPLY_WAIT_SECONDS = 300
# The firmware closes the channel after 120s without any incoming frame.
KEEPALIVE_SECONDS = 30
# A posted reply is accepted this long after the request.
REPLY_TOKEN_SECONDS = 24 * 3600
# Bot replies normally arrive within ~15s; a longer wait is often an approval
# prompt in the Grok UI, which the server cannot see.
APPROVAL_HINT_SECONDS = 30
APPROVAL_HINT = "等待时间较长。\n如果 Grok 界面在请求授权，请在那里确认。"


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def prepare_reply(directory, request_id, device, token=None):
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Bot reply directory must be absolute")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending = directory / (request_id + ".pending.json")
    metadata = {"request_id": request_id, "device": device, "created": time.time()}
    if token:
        # Only the hash is kept, so the reply directory never holds a usable token.
        metadata["token_sha256"] = _token_hash(token)
    with pending.open("x", encoding="utf-8") as file:
        pending.chmod(0o600)
        json.dump(metadata, file)
    return pending, directory / (request_id + ".json")


def accept_reply(directory, request_id, token, text):
    """Store a reply posted over HTTP; returns an HTTP status code.

    The posted reply becomes the same result file the Bot used to write locally,
    so delivery, retries and the waiting UI stay unchanged.
    """
    if not isinstance(request_id, str) or not re.fullmatch(r"ESP32-[0-9a-f]{32}", request_id):
        return 400
    if not isinstance(token, str) or not token or not isinstance(text, str):
        return 400
    if not text.strip() or len(text) > 8000:
        return 400
    directory = Path(directory)
    pending = directory / (request_id + ".pending.json")
    try:
        if pending.is_symlink() or pending.stat().st_size > 4096:
            return 404
        metadata = json.loads(pending.read_text(encoding="utf-8"))
        expected = metadata.get("token_sha256")
        if not isinstance(expected, str) or not hmac.compare_digest(expected, _token_hash(token)):
            return 403
        # Late replies are still delivered (timed-out requests are kept), within a day.
        if time.time() - float(metadata["created"]) > REPLY_TOKEN_SECONDS:
            return 404
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 404
    result = directory / (request_id + ".json")
    if result.exists() or result.is_symlink():
        return 409
    temp = directory / f".{request_id}.{uuid.uuid4().hex}.tmp"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump({"request_id": request_id, "text": text.strip()}, file, ensure_ascii=False)
        temp.rename(result)
    except OSError:
        temp.unlink(missing_ok=True)
        return 500
    return 200


def read_reply(pending, device):
    """Only accept a bounded reply for a request created for this device."""
    try:
        request_id = pending.name.removesuffix(".pending.json")
        if not re.fullmatch(r"ESP32-[0-9a-f]{32}", request_id) or pending.is_symlink():
            return None
        if pending.stat().st_size > 4096:
            return None
        metadata = json.loads(pending.read_text(encoding="utf-8"))
        if metadata.get("request_id") != request_id or metadata.get("device") != device:
            return None
        reply = pending.with_name(request_id + ".json")
        if reply.is_symlink() or reply.stat().st_size > 65536:
            return None
        data = json.loads(reply.read_text(encoding="utf-8"))
        text = data.get("text")
        if data.get("request_id") != request_id or not isinstance(text, str):
            return None
        if not text.strip() or len(text) > 8000:
            return None
        reply.chmod(0o600)
        return request_id, text.strip(), metadata.get("created")
    except (OSError, ValueError, AttributeError, TypeError):
        # The Bot may still be writing. Invalid/incomplete files are not displayed.
        return None


async def deliver_replies(conn, directory):
    async with _delivery_lock:
        if (conn.stop_event.is_set() or conn.client_is_speaking or conn.client_have_voice
                or getattr(conn, "just_woken_up", False) or not conn.tts
                or time.monotonic() < getattr(conn, "bot_input_until", 0)):
            return
        device = conn.headers.get("device-id", "unknown")
        for pending in sorted(Path(directory).glob("ESP32-*.pending.json"), key=lambda p: p.stat().st_mtime):
            reply = read_reply(pending, device)
            if reply is None:
                continue
            request_id, text, created = reply
            # A reply left over from an earlier session needs context on screen.
            if isinstance(created, (int, float)) and created < getattr(conn, "bot_reply_since", 0):
                text = "稍早的 Bot 回复：" + text
            from core.handle.intentHandler import speak_txt

            sentence_id = uuid.uuid4().hex
            conn.sentence_id = sentence_id
            conn.bot_reply_sentence_id = sentence_id
            conn.client_abort = False
            conn.client_is_speaking = True
            conn.last_activity_time = time.time() * 1000
            try:
                if (getattr(conn, "features", None) or {}).get("bot_ui"):
                    await conn.websocket.send(json.dumps({
                        "type": "bot_wait", "state": "reply", "text": text,
                        "session_id": conn.session_id,
                    }, ensure_ascii=False))
                    conn.bot_ui_waiting = False
                await conn.websocket.send(json.dumps({
                    "type": "tts", "state": "start", "session_id": conn.session_id,
                    "request_id": request_id,
                }))
                # Show the complete answer while synthesis starts; the existing
                # TTS queue then supplies audio, sentence subtitles and stop.
                if not conn.client_abort and conn.sentence_id == sentence_id:
                    await conn.websocket.send(json.dumps({
                        "type": "tts", "state": "sentence_start", "text": text,
                        "session_id": conn.session_id, "request_id": request_id,
                    }, ensure_ascii=False))
                if not conn.client_abort and conn.sentence_id == sentence_id:
                    speak_txt(conn, text)
            except Exception:
                if conn.sentence_id == sentence_id:
                    conn.client_is_speaking = False
                    try:
                        await conn.websocket.send(json.dumps({
                            "type": "tts", "state": "stop", "session_id": conn.session_id,
                        }))
                    except Exception:
                        pass
                raise
            pending.rename(pending.with_name(request_id + ".sent.json"))
            conn.logger.bind(tag=__name__).info(f"Bot reply dispatched for speech and display: {request_id}")
            return True


def waiting_for_reply(directory, device, wait_seconds, now=None):
    """True while a recent request from this device has no delivered reply."""
    now = time.time() if now is None else now
    for pending in Path(directory).glob("ESP32-*.pending.json"):
        try:
            if pending.is_symlink() or pending.stat().st_size > 4096:
                continue
            metadata = json.loads(pending.read_text(encoding="utf-8"))
            if metadata.get("device") == device and 0 <= now - float(metadata["created"]) < wait_seconds:
                return True
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return False


async def hold_connection(conn):
    """Keep both the server idle timers and the firmware channel timeout from closing."""
    conn.last_activity_time = time.time() * 1000
    now = time.monotonic()
    if now - getattr(conn, "bot_keepalive_at", 0) >= KEEPALIVE_SECONDS:
        # Unknown types are logged and ignored by the firmware but still count as incoming data.
        await conn.websocket.send(json.dumps({"type": "bot_wait", "session_id": conn.session_id}))
        conn.bot_keepalive_at = now


async def update_wait_ui(conn, directory, wait_seconds, hint_seconds=APPROVAL_HINT_SECONDS):
    """Announce each pending request once; waking explicitly resumes input."""
    if not (getattr(conn, "features", None) or {}).get("bot_ui"):
        return
    if conn.client_is_speaking or conn.client_have_voice or getattr(conn, "just_woken_up", False):
        return
    device = conn.headers.get("device-id", "unknown")
    latest = 0
    now = time.time()
    for pending in Path(directory).glob("ESP32-*.pending.json"):
        try:
            if pending.is_symlink() or pending.stat().st_size > 4096:
                continue
            data = json.loads(pending.read_text(encoding="utf-8"))
            created = float(data["created"])
            if data.get("device") == device and 0 <= now - created < wait_seconds:
                latest = max(latest, created)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    if latest > getattr(conn, "bot_ui_seen_at", 0):
        await conn.websocket.send(json.dumps({
            "type": "bot_wait", "state": "waiting", "elapsed": int(now - latest),
            "session_id": conn.session_id,
        }))
        conn.bot_ui_seen_at = latest
        conn.bot_ui_waiting = True
        conn.reset_audio_states()
    elif not latest and getattr(conn, "bot_ui_waiting", False):
        await conn.websocket.send(json.dumps({
            "type": "bot_wait", "state": "timeout", "session_id": conn.session_id,
        }))
        conn.bot_ui_waiting = False
    if (hint_seconds and latest and getattr(conn, "bot_ui_waiting", False)
            and now - latest >= hint_seconds and getattr(conn, "bot_hint_for", 0) != latest):
        # Replaces the waiting text only; the firmware keeps counting seconds in the status bar.
        await conn.websocket.send(json.dumps({
            "type": "tts", "state": "sentence_start", "text": APPROVAL_HINT,
            "session_id": conn.session_id,
        }, ensure_ascii=False))
        conn.bot_hint_for = latest


def resume_bot_input(conn):
    if getattr(conn, "bot_ui_waiting", False):
        conn.bot_ui_waiting = False
        # Leave time to speak after an explicit wake/button, before delivering an old reply.
        conn.bot_input_until = time.monotonic() + 15


async def watch_replies(conn):
    config_file = conn.config.get("grok_bot", {}).get("config_file", "")
    # Let hello and the wake greeting initialize before restoring queued replies.
    await asyncio.sleep(2)
    while not conn.stop_event.is_set():
        delivered = False
        try:
            config = json.loads(Path(config_file).read_text(encoding="utf-8"))
            directory = config.get("reply_dir")
            if directory:
                delivered = await deliver_replies(conn, directory)
                wait_seconds = config.get("reply_wait_seconds", REPLY_WAIT_SECONDS)
                device = conn.headers.get("device-id", "unknown")
                if not delivered:
                    await update_wait_ui(conn, directory, wait_seconds,
                                         config.get("approval_hint_seconds", APPROVAL_HINT_SECONDS))
                playing_reply = (conn.client_is_speaking and
                                 getattr(conn, "bot_reply_sentence_id", None) == getattr(conn, "sentence_id", ""))
                if playing_reply or (not delivered and waiting_for_reply(directory, device, wait_seconds)):
                    await hold_connection(conn)
        except Exception as error:
            # Pending files survive disconnects/restarts and are retried on hello.
            conn.logger.bind(tag=__name__).warning(f"Bot reply delivery deferred: {type(error).__name__}")
        await asyncio.sleep(10 if delivered else 1)


def start_reply_watcher(conn):
    if not conn.config.get("grok_bot", {}).get("enabled"):
        return
    if not hasattr(conn, "bot_reply_since"):
        conn.bot_reply_since = time.time()
    task = getattr(conn, "bot_reply_task", None)
    if task is None or task.done():
        conn.bot_reply_task = asyncio.create_task(watch_replies(conn))
    from core.handle import grokBotPhrases
    asyncio.create_task(grokBotPhrases.warm(conn))
