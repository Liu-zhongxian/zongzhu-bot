import threading
import time
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest import mock

from core.providers.tts import base
from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO


class SlowTTS(base.TTSProviderBase):
    """每句合成固定耗时，记录合成了哪些文字、何时开始。"""

    DELAY = 0.2

    def __init__(self):
        super().__init__({}, True)
        self.calls = Counter()
        self.started = {}
        self.lock = threading.Lock()

    async def text_to_speak(self, text, output_file):
        with self.lock:
            self.calls[text] += 1
            self.started.setdefault(text, time.monotonic())
        time.sleep(self.DELAY)
        return text.encode()


# 冒号也断句，和 2026-10-22 日志里的实际切分一致
EXPECTED = ["收到", "语音识别正常", "我识别到的内容是", "测试一下", "其中英文词被识别成了 rhythmy", "可以继续说几个英文单词"]
REPLY = "收到，语音识别正常。我识别到的内容是：测试一下。其中英文词被识别成了 rhythmy。可以继续说几个英文单词"


class PrefetchTest(unittest.TestCase):
    def run_reply(self, tts, text=REPLY):
        conn = SimpleNamespace(sentence_id="s1", client_abort=False, stop_event=threading.Event(),
                               sample_rate=16000)
        tts.conn = conn
        tts.opus_encoder = None
        tts.tts_text_queue.put(TTSMessageDTO(sentence_id="s1", sentence_type=SentenceType.FIRST,
                                             content_type=ContentType.ACTION))
        tts.tts_one_sentence(conn, ContentType.TEXT, content_detail=text, sentence_id="s1")
        tts.tts_text_queue.put(TTSMessageDTO(sentence_id="s1", sentence_type=SentenceType.LAST,
                                             content_type=ContentType.ACTION))

        def fake_stream(audio_bytes, **kwargs):
            kwargs["callback"](audio_bytes)

        with mock.patch.object(base, "audio_bytes_to_data_stream", fake_stream):
            worker = threading.Thread(target=tts.tts_text_priority_thread)
            worker.start()
            spoken, deadline = [], time.monotonic() + 10
            while time.monotonic() < deadline:
                item = tts.tts_audio_queue.get(timeout=5)
                if item[0] == SentenceType.LAST:
                    break
                if item[0] == SentenceType.FIRST:
                    spoken.append(item[2])
            conn.stop_event.set()
            worker.join()
        return spoken

    def test_each_sentence_synthesized_once_in_order(self):
        tts = SlowTTS()
        spoken = self.run_reply(tts)
        self.assertEqual(spoken, EXPECTED)
        self.assertEqual(set(tts.calls.values()), {1}, tts.calls)

    def test_later_sentences_start_before_earlier_finish(self):
        tts = SlowTTS()
        self.run_reply(tts)
        # 第 2、3 句在第 1 句合成期间就开始了，不再一句等一句
        first = tts.started["收到"]
        self.assertLess(tts.started["语音识别正常"] - first, SlowTTS.DELAY / 2)
        self.assertLess(tts.started["我识别到的内容是"] - first, SlowTTS.DELAY / 2)

    def test_prediction_matches_segmentation(self):
        tts = SlowTTS()
        tts.conn = SimpleNamespace(sentence_id="s1")
        tts.tts_one_sentence(tts.conn, ContentType.TEXT, content_detail=REPLY, sentence_id="s1")
        tts.tts_text_queue.put(TTSMessageDTO(sentence_id="s1", sentence_type=SentenceType.LAST,
                                             content_type=ContentType.ACTION))
        self.assertEqual(tts._upcoming_segments("s1", 10),
                         EXPECTED)


if __name__ == "__main__":
    unittest.main()
