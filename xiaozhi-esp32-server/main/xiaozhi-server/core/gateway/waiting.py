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

Interrupted answer (2026-11-02, 你定的规则): waking the device while it says an answer stops it
(abort). What was left — from the sentence it was on — is said once the next question has been
handed over (or after RESUME_SECONDS when nothing is asked), then answers that came in meanwhile.
An answer to a question asked after the interruption starts with that question
("你刚才问「……」："), so it is clear which one it answers.

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
# A wake this soon after an answer's last sentence was sent still interrupts it: the device
# plays what it has buffered (the Xiaomi speaker up to ~1 s, 2026-11-02 录音) after tts stop.
INTERRUPT_GRACE_SECONDS = 3
_PUNCTUATION = "，。；：！？、,.;:!? \n"

_delivery_lock = asyncio.Lock()


def _busy(conn):
    return conn.client_is_speaking or conn.client_have_voice or getattr(conn, "just_woken_up", False)


def note_sentence(conn, text):
    """The TTS queue sent this sentence of the answer being said (say_reply) to the device."""
    current = getattr(conn, "gateway_reply_now", None)
    if current and conn.sentence_id == current["sentence_id"]:
        current["said"].append(text)


def note_stop(conn):
    current = getattr(conn, "gateway_reply_now", None)
    if current and conn.sentence_id == current["sentence_id"]:
        current["stopped_at"] = time.monotonic()


def remaining_text(text, said):
    """What is left of `text` from the last sentence in `said` (the one being played); the whole
    text when nothing was said yet or the sentence is not found."""
    start = 0
    for sentence in said:
        found = text.find(sentence.strip(_PUNCTUATION), start)
        if found < 0:
            return text if start == 0 else text[start:]
        start = found
    return text[start:]


def on_abort(conn):
    """The device interrupted (abort): keep what is left of the answer it was saying."""
    current = getattr(conn, "gateway_reply_now", None)
    conn.gateway_reply_now = None
    if not current or conn.sentence_id != current["sentence_id"]:
        return
    stopped = current.get("stopped_at")
    if stopped is not None and time.monotonic() - stopped > INTERRUPT_GRACE_SECONDS:
        return
    rest = remaining_text(current["text"], current["said"])
    if not rest.strip(_PUNCTUATION):
        return
    conn.gateway_resume = (rest, current["request_id"])
    conn.gateway_interrupted_at = time.time()
    # Leave time for the new question before saying the rest (a question clears this, hand_over)
    conn.bot_input_until = time.monotonic() + RESUME_SECONDS
    conn.logger.bind(tag=TAG).info(f"回复被打断，剩下的待会接着说: {rest[:30]}")


def _question_prefix(conn, reply):
    """「你刚才问……」 for an answer to a question asked after an interruption, else ""."""
    since = getattr(conn, "gateway_interrupted_at", 0)
    if not (since and reply.question and isinstance(reply.created, (int, float)) and reply.created >= since):
        return ""
    return f"你刚才问「{reply.question.strip(_PUNCTUATION)}」："


async def deliver(conn, agent):
    """Say the rest of an interrupted answer, else the next answer that is ready;
    "resumed" / True when one was started."""
    async with _delivery_lock:
        if (conn.stop_event.is_set() or _busy(conn) or not conn.tts
                or time.monotonic() < getattr(conn, "bot_input_until", 0)):
            return
        resume = getattr(conn, "gateway_resume", None)
        if resume:
            conn.gateway_resume = None
            await say_reply(conn, TextDelta(resume[0]), resume[1])
            conn.logger.bind(tag=TAG).info(f"接着说被打断的回复: {resume[1]}")
            return "resumed"
        reply = agent.next_reply(conn)
        if reply is None:
            return
        text = reply.text
        prefix = _question_prefix(conn, reply)
        if prefix:
            text = prefix + text
        # An answer to a request from an earlier connection (interrupted, timed out, or the board
        # slept in between) needs context: "硬件做完了：……"
        elif isinstance(reply.created, (int, float)) and reply.created < getattr(conn, "bot_reply_since", 0):
            text = agent.done_prefix(conn) + text
        await say_reply(conn, TextDelta(text), reply.request_id)
        agent.delivered(conn, reply)
        if prefix and not agent.waiting_since(conn):
            conn.gateway_interrupted_at = 0  # every question since the interruption is answered
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
    if getattr(conn, "gateway_resume", None):
        # Woken again before the rest of an interrupted answer was said: the user speaks first
        # (2026-11-02: the rest started right over a new wake, the question was never heard)
        conn.bot_input_until = time.monotonic() + RESUME_SECONDS
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
        # The rest of an interrupted answer: the next answer may follow as soon as it ends
        await asyncio.sleep(10 if delivered is True else 1)


def start(conn, agent):
    """A board connected (hello): watch for this AI's answers on this connection."""
    if not hasattr(conn, "bot_reply_since"):
        conn.bot_reply_since = time.time()
    task = getattr(conn, "bot_reply_task", None)
    if task is None or task.done():
        conn.bot_reply_task = asyncio.create_task(watch(conn, agent))
