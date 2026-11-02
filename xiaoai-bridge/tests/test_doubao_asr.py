import base64
import wave
from io import BytesIO

from core.services.audio.asr.doubao import _DoubaoASR


def test_pcm_to_wav_wraps_int16_mono_audio():
    pcm = (b"\x01\x00\xff\x7f") * 4

    wav_bytes = _DoubaoASR._pcm_to_wav(pcm, 16000)

    with wave.open(BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        assert wav_file.readframes(wav_file.getnframes()) == pcm

    assert base64.b64decode(base64.b64encode(wav_bytes)) == wav_bytes


def test_extract_text_supports_dict_and_list_results():
    client = _DoubaoASR()

    assert client._extract_text({"result": {"text": " 你好 "}}) == "你好"
    assert client._extract_text({"result": [{"text": "你"}, {"text": "好"}]}) == "你好"
    assert client._extract_text({"result": {}}) == ""
