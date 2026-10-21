"""Fixed Bot prompts are synthesized once and replayed from memory.

EdgeTTS needs about 2s even for a short phrase; a cached phrase starts at once.
"""
import asyncio
import uuid

ACK = "好的，正在交给 Bot。"
HERE = "我在。"
PHRASES = (ACK, HERE)

# (tts class, voice, sample rate, text) -> Opus packets. Memory only: a new voice
# or a restart synthesizes again.
_cache = {}
_warming = set()


def _key(conn, text):
    tts = conn.tts
    return type(tts).__name__, getattr(tts, "voice", None), getattr(conn, "sample_rate", None), text


async def warm(conn, texts=PHRASES):
    """Synthesize uncached phrases in the background; failures leave live synthesis in place."""
    # TTS is created by the component initialisation that runs after hello.
    for _ in range(150):
        if getattr(conn, "tts", None):
            break
        await asyncio.sleep(0.1)
    else:
        return
    for text in texts:
        key = _key(conn, text)
        if key in _cache or key in _warming:
            continue
        _warming.add(key)
        try:
            # to_tts runs its own event loop, so it must stay off this one.
            packets = await asyncio.to_thread(conn.tts.to_tts, text)
            if isinstance(packets, list) and packets:
                _cache[key] = packets
                conn.logger.bind(tag=__name__).info(f"Phrase cached: {text}")
        except Exception as error:
            conn.logger.bind(tag=__name__).warning(f"Phrase cache skipped: {type(error).__name__}")
        finally:
            _warming.discard(key)


async def speak(conn, text, send_start=False):
    """Play a fixed phrase; returns False (and plays nothing) when it is not cached yet.

    Without send_start the caller has already sent tts start (send_stt_message
    does), as for the cached wake-word greeting.
    """
    if not getattr(conn, "tts", None):
        return False
    packets = _cache.get(_key(conn, text))
    if not packets:
        asyncio.create_task(warm(conn, (text,)))
        return False
    # Imported here: these modules load the server config on import.
    from core.handle.sendAudioHandle import sendAudioMessage, send_tts_message
    from core.providers.tts.dto.dto import SentenceType
    from core.utils.dialogue import Message

    if send_start:
        await send_tts_message(conn, "start")
        conn.client_is_speaking = True
    conn.client_abort = False
    conn.sentence_id = uuid.uuid4().hex
    await sendAudioMessage(conn, SentenceType.FIRST, packets, text)
    await sendAudioMessage(conn, SentenceType.LAST, [], None)
    conn.dialogue.put(Message(role="assistant", content=text))
    return True
