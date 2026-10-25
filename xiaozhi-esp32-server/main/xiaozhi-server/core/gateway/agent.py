"""AI modules: what the gateway does around any AI, so a new one only implements a session.

An AI module is an `Agent` (name, phrases, start-up hooks) whose `session(conn)` returns an
`AgentSession` (core/gateway/agent_session.py, from xiaozhi-hub-server). `hand_over` runs
one sentence through it and turns the events into speech and screens:

- Activity(HANDING_OVER)       sent off; say the module's cached `ack`
- Activity(WAITING_FOR_REPLY)  same, and the answer comes later: the board shows its waiting screen
- TextDelta                    said after the ack
- Error                        before any Activity: not sent (repeat, missing config), the voice
                               is said at once; after it: said after the ack, and shown on screen
                               unless the kind is UNKNOWN (it may still have been sent)
- Done                         finished

An AI whose answers come back later (`answers_later = True`) also answers the questions in
waiting.py, which shows the waiting screen and says each answer through `say_reply`.
"""
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from core.gateway.agent_session import Activity, AgentSession, Done, Error, ErrorKind, TextDelta
from core.handle import grokBotPhrases as phrases

HANDING_OVER = "handing_over"
WAITING_FOR_REPLY = "waiting_for_reply"


@dataclass
class Reply:
    """An answer that came back after the hand-over."""
    request_id: str
    text: str
    created: Optional[float] = None  # when the request was sent (time.time())
    ref: object = None  # whatever the module needs back in `delivered`


class Agent:
    name = ""
    title = ""  # shown on the gateway page
    ack = ""  # cached phrase said while the sentence is sent off
    accepted = ""  # said instead when the ack is not cached yet and the AI accepted the sentence
    answers_later = False  # True: answers come back after the hand-over (see waiting.py)
    earlier = "稍早的回复："  # put before an answer to a request from an earlier connection

    def enabled(self, config) -> bool:
        return True

    def phrases(self, config) -> tuple:
        # HERE: said when the wake word is repeated while talking to the AI
        return tuple(text for text in (self.ack, phrases.HERE) if text)

    def warm(self, conn):
        """A board connected: start whatever the AI needs in the background."""

    def on_listen(self, conn):
        """The board started listening (button or wake word)."""

    def session(self, conn) -> AgentSession:
        raise NotImplementedError

    # Only for answers_later; see waiting.py
    def watches(self, conn) -> bool:
        """Whether answers can come back now (e.g. the return path is configured)."""
        return self.answers_later

    def waiting_since(self, conn) -> float:
        return 0

    def next_reply(self, conn) -> Optional[Reply]:
        return None

    def delivered(self, conn, reply: Reply):
        pass

    def slow_hint(self, conn):
        """(seconds, text) to show when the answer takes that long, or None."""
        return None


def _bot_ui(conn):
    return bool((getattr(conn, "features", None) or {}).get("bot_ui"))


def _session(conn, agent):
    sessions = getattr(conn, "gateway_sessions", None)
    if sessions is None:
        sessions = conn.gateway_sessions = {}
    if agent.name not in sessions:
        sessions[agent.name] = agent.session(conn)
    return sessions[agent.name]


async def hand_over(conn, agent, text) -> bool:
    """True when the AI took the sentence (or it was only the wake word again)."""
    from core.handle.grokBotHandle import extract_command, strip_wake_phrase

    command = extract_command(text)
    if not agent.enabled(conn.config) or command is None:
        return False
    device_wake = getattr(conn, "device_wake_word", None)
    # Wake phrases use the local cached greeting; they are not tasks.
    if re.sub(r"[\W_]", "", command) in [*conn.config.get("wakeup_words", []), device_wake]:
        return False
    from core.handle.intentHandler import speak_txt
    from core.handle.sendAudioHandle import send_stt_message

    had_wake, rest = strip_wake_phrase(command, [device_wake] if device_wake else ())
    if had_wake:
        if not rest.strip("，。！？,.!? "):
            # The user repeated the wake word mid-conversation: acknowledge, send nothing.
            conn.logger.bind(tag="gateway").info(f"忽略重复唤醒词，不提交: {text}")
            conn.client_abort = False
            if not await phrases.speak(conn, phrases.HERE, send_start=True):
                speak_txt(conn, phrases.HERE)
            return True
        command = rest

    conn.bot_input_until = 0
    conn.client_abort = False
    conn.sentence_id = uuid.uuid4().hex
    await send_stt_message(conn, text)
    acked, said, error = None, "", None
    async for event in _session(conn, agent).send(command):
        if isinstance(event, Activity) and event.label in (HANDING_OVER, WAITING_FOR_REPLY):
            if event.label == WAITING_FOR_REPLY and _bot_ui(conn):
                # Stop ordinary input now: speech that continues past the hand-over would otherwise
                # become separate tasks before the waiting screen appears (three in a row, 2026-10-22).
                # Wake or button resumes input; a rejection or a delivered reply clears it as before.
                conn.bot_ui_waiting = True
                conn.reset_audio_states()
            # The ack plays while the AI is still being reached, so it does not claim success.
            acked = await phrases.speak(conn, agent.ack)
        elif isinstance(event, TextDelta):
            said += event.text
        elif isinstance(event, Error):
            error = event
            break
        elif isinstance(event, Done):
            break
    if error is not None and acked is None:
        conn.gateway_not_sent = error.voice_message  # shown on the gateway page as not sent
        if not conn.client_abort:
            speak_txt(conn, error.voice_message)
        return True
    if conn.client_abort:
        return True
    text = error.voice_message if error else said
    if not acked:
        speak_txt(conn, text or agent.accepted)
    elif text:
        await _say_after_ack(conn, text, show=error is not None and error.kind != ErrorKind.UNKNOWN)
    return True


async def _say_after_ack(conn, text, show):
    """A second sentence after the cached acknowledgement, which already ended with tts stop."""
    from core.handle.intentHandler import speak_txt
    from core.handle.sendAudioHandle import send_tts_message

    if show and _bot_ui(conn):
        # Leaves any waiting screen and keeps the reason on screen, like a delivered reply.
        await conn.websocket.send(json.dumps({
            "type": "bot_wait", "state": "reply", "text": text, "session_id": conn.session_id,
        }, ensure_ascii=False))
        conn.bot_ui_waiting = False
    conn.sentence_id = uuid.uuid4().hex
    await send_tts_message(conn, "start")
    conn.client_is_speaking = True
    speak_txt(conn, text)


async def say_reply(conn, reply: TextDelta, request_id):
    """Speak and show an answer that arrived after the hand-over; raises if it could not start."""
    from core.handle.intentHandler import speak_txt

    text = reply.text
    sentence_id = uuid.uuid4().hex
    conn.sentence_id = sentence_id
    conn.bot_reply_sentence_id = sentence_id
    conn.client_abort = False
    conn.client_is_speaking = True
    conn.last_activity_time = time.time() * 1000
    try:
        if _bot_ui(conn):
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
