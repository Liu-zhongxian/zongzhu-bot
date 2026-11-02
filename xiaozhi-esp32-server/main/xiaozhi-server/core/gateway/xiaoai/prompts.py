"""音箱用的固定短句（"在"）：用后端配置的 TTS 合成一次，转成 24 kHz PCM、去掉前后静音存着，唤醒时直接放。"""
import asyncio
from io import BytesIO

import numpy as np

from core.gateway.xiaoai.protocol import PLAY_CONFIG

_cache: dict[str, bytes] = {}


def _to_pcm(audio, file_type, rate):
    from pydub import AudioSegment

    segment = AudioSegment.from_file(BytesIO(audio), format=file_type, parameters=["-nostdin"])
    return trim(segment.set_channels(1).set_frame_rate(rate).set_sample_width(2).raw_data, rate)


def trim(pcm, rate, threshold=500, margin_ms=30):
    """去掉前后的静音（低于 threshold 的部分），两头各留 margin_ms。

    2026-11-02 实测：EdgeTTS 合成的"在"整段 1.872 秒，音箱上真正出声的只有约 0.3 秒，
    前面约 0.33 秒、后面约 1.25 秒是静音。不剪的话"在"晚出来，唤醒后不认唤醒词的时间也按 1.9 秒算，
    紧接着再喊会被丢掉。
    """
    samples = np.frombuffer(pcm, dtype="<i2")
    loud = np.flatnonzero(np.abs(samples.astype(np.int32)) > threshold)
    if not len(loud):
        return pcm
    margin = rate * margin_ms // 1000
    start, end = max(0, loud[0] - margin), min(len(samples), loud[-1] + 1 + margin)
    return samples[start:end].tobytes()


async def speech(config, text):
    """合成 text 的 PCM（24 kHz 单声道 16 位，去掉前后静音），不存；失败抛异常"""
    from core.utils.modules_initialize import initialize_tts

    tts = initialize_tts(config)
    audio = await tts.text_to_speak(text, None)
    if not audio:
        raise RuntimeError(f"TTS 没有返回音频：{text}")
    return await asyncio.to_thread(_to_pcm, audio, tts.audio_file_type, PLAY_CONFIG["sample_rate"])


async def phrase(config, text):
    """固定短句的 PCM，合成过的直接返回；失败抛异常"""
    if text not in _cache:
        _cache[text] = await speech(config, text)
    return _cache[text]
