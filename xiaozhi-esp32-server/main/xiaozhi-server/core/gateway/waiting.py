"""Waiting for an AI whose answer comes back later: the same for every AI module.

While a board has a request out, the gateway shows the waiting screen with its seconds
counter, keeps the connection open, replaces the text with the module's hint when it takes
long, says the answer when it arrives, and announces a timeout. Wake or button resumes
ordinary input. The module only tells (see `Agent` in agent.py):

- `waiting_since(conn)`: when the newest unanswered request was sent (time.time()), else 0
- `next_reply(conn)`: an answer ready to be said, else None; `delivered(conn, reply)` after
- `slow_hint(conn)`: (seconds, text) shown after that long, or None

Optional spoken progress (原清单 A9, off by default; config `gateway.progress_prompts: true`):
30 s after the request "还在处理，请稍等。", then after 60 s more and every 120 s the time so far.

The conn attributes keep their Grok-era names (bot_ui_waiting, bot_input_until ...):
receiveAudioHandle, connection and the music skill read them.
"""
import asyncio
import json
import time

from core.gateway.agent import _bot_ui, say_reply
from core.gateway.agent_session import TextDelta

TAG = "gateway"
# The firmware closes the channel after 120s without any incoming frame.
KEEPALIVE_SECONDS = 30
# Leave time to speak after an explicit wake/button, before delivering an old reply.
RESUME_SECONDS = 15
PROGRESS_FIRST, PROGRESS_SECOND, PROGRESS_EVERY = 30, 60, 120

_delivery_lock = asyncio.Lock()


def _busy(conn):
    return conn.client_is_speaking or conn.client_have_voice or getattr(conn, "just_woken_up", False)


async def deliver(conn, agent):
    """Say the next answer that is ready; True when one was started."""
    async with _delivery_lock:
        if (conn.stop_event.is_set() or _busy(conn) or not conn.tts
                or time.monotonic() < getattr(conn, "bot_input_until", 0)):
            return
        reply = agent.next_reply(conn)
        if reply is None:
            return
        text = reply.text
        # An answer to a request from an earlier connection (interrupted, timed out, or the board
        # slept in between) needs context: "硬件做完了：……"
        if isinstance(reply.created, (int, float)) and reply.created < getattr(conn, "bot_reply_since", 0):
            text = agent.done_prefix(conn) + text
        await say_reply(conn, TextDelta(text), reply.request_id)
        agent.delivered(conn, reply)
        conn.logger.bind(tag=TAG).info(f"迟到的回复已交给板子朗读和显示: {reply.request_id}")
        return True


async def update_screen(conn, agent):
    """Announce each new request once; a timeout once; the slow hint once per request."""
    if not _bot_ui(conn) or _busy(conn):
        return
    latest = agent.waiting_since(conn)
    now = time.time()
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
    hint = agent.slow_hint(conn)
    if (hint and latest and getattr(conn, "bot_ui_waiting", False)
            and now - latest >= hint[0] and getattr(conn, "bot_hint_for", 0) != latest):
        # Replaces the waiting text only; the firmware keeps counting seconds in the status bar.
        await conn.websocket.send(json.dumps({
            "type": "tts", "state": "sentence_start", "text": hint[1],
            "session_id": conn.session_id,
        }, ensure_ascii=False))
        conn.bot_hint_for = latest


def progress_text(elapsed, said):
    """The spoken progress line due after `elapsed` seconds when `said` lines were said, else None."""
    due = PROGRESS_FIRST + (PROGRESS_SECOND if said >= 1 else 0) + PROGRESS_EVERY * max(said - 1, 0)
    if elapsed < due:
        return None
    if said == 0:
        return "还在处理，请稍等。"
    minutes, seconds = divmod(int(elapsed), 60)
    spent = f"{minutes}分{seconds}秒" if minutes else f"{seconds}秒"
    return f"已经等了{spent}，还在处理。"


async def speak_progress(conn, agent):
    if not (conn.config.get("gateway") or {}).get("progress_prompts") or _busy(conn):
        return
    latest = agent.waiting_since(conn)
    if not latest or not getattr(conn, "bot_ui_waiting", False):
        return
    said = conn.gateway_progress[1] if getattr(conn, "gateway_progress", (0, 0))[0] == latest else 0
    text = progress_text(time.time() - latest, said)
    if text:
        from core.handle.intentHandler import speak_txt
        from core.handle.sendAudioHandle import send_tts_message

        conn.gateway_progress = (latest, said + 1)
        await send_tts_message(conn, "start")
        conn.client_is_speaking = True
        speak_txt(conn, text)


async def hold_connection(conn):
    """Keep both the server idle timers and the firmware channel timeout from closing."""
    conn.last_activity_time = time.time() * 1000
    now = time.monotonic()
    if now - getattr(conn, "bot_keepalive_at", 0) >= KEEPALIVE_SECONDS:
        # Unknown types are logged and ignored by the firmware but still count as incoming data.
        await conn.websocket.send(json.dumps({"type": "bot_wait", "session_id": conn.session_id}))
        conn.bot_keepalive_at = now


def resume_input(conn):
    """Wake or button while waiting: listen again, the answer is still said when it comes."""
    if getattr(conn, "bot_ui_waiting", False):
        conn.bot_ui_waiting = False
        conn.bot_input_until = time.monotonic() + RESUME_SECONDS


async def watch(conn, agent):
    # Let hello and the wake greeting initialize before restoring queued replies.
    await asyncio.sleep(2)
    while not conn.stop_event.is_set():
        delivered = False
        try:
            if agent.watches(conn):
                delivered = await deliver(conn, agent)
                if not delivered:
                    await update_screen(conn, agent)
                    await speak_progress(conn, agent)
                playing_reply = (conn.client_is_speaking and
                                 getattr(conn, "bot_reply_sentence_id", None) == getattr(conn, "sentence_id", ""))
                if playing_reply or (not delivered and agent.waiting_since(conn)):
                    await hold_connection(conn)
        except Exception as error:
            # Unanswered requests survive disconnects/restarts and are retried on hello.
            conn.logger.bind(tag=TAG).warning(f"迟到的回复暂缓处理: {type(error).__name__}")
        await asyncio.sleep(10 if delivered else 1)


def start(conn, agent):
    """A board connected (hello): watch for this AI's answers on this connection."""
    if not hasattr(conn, "bot_reply_since"):
        conn.bot_reply_since = time.time()
    task = getattr(conn, "bot_reply_task", None)
    if task is None or task.done():
        conn.bot_reply_task = asyncio.create_task(watch(conn, agent))
