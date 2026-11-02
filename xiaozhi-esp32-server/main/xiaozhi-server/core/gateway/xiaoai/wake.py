"""音箱的唤醒词识别（G19i 第 2 步）：sherpa-onnx 的 KeywordSpotter，在后端直接听音箱的麦克风。

模型用原来的 bridge 一直在用的那套（coderzc/open-xiaoai-bridge 发布的 models.zip 里的
encoder.onnx、decoder.onnx、joiner.onnx、tokens.txt、bpe.model），放在 `gateway.xiaoai.kws_model_dir`
（默认 models/sherpa-onnx-kws-open-xiaoai/，.gitignore 已排除 models/sherpa-onnx*）。
"""
import queue
import threading
from pathlib import Path

import numpy as np

DEFAULT_MODEL_DIR = "models/sherpa-onnx-kws-open-xiaoai"
DEFAULT_WAKE_WORDS = ("你好宗主", "宗主你好")
# 2026-11-02 两段音箱录音（47 次喊、共 19 分钟，tools/xiaoai-debug/kws_eval.py）离线比较：
# 0.2（bridge 原来的值）认出 33 次，0.1 认出 34 次，0.05 认出 43 次，都没有误唤醒；实测 11 喊 11 应，
# 放视频、说话 2 分钟没有误唤醒。加分（keywords_score）调高反而认出得少，保持 2.0。
DEFAULT_THRESHOLD = 0.05
SAMPLE_RATE = 16000


def keyword_lines(words, tokens, bpe_model):
    """唤醒词 → KeywordSpotter 的关键词行（"你 好 宗 主 @你好宗主"），英文用 bpe 切"""
    import sherpa_onnx

    lowered = [w.strip().lower() for w in words if w and w.strip()]
    pieces = sherpa_onnx.text2token(lowered, tokens=tokens, tokens_type="cjkchar+bpe", bpe_model=bpe_model)
    return [" ".join(p) + " @" + w for p, w in zip(pieces, lowered)]


class Spotter:
    """一套模型，多条音箱各用一个 stream"""

    def __init__(self, model_dir, words, score=2.0, threshold=0.2):
        import sherpa_onnx

        model = Path(model_dir)
        missing = [n for n in ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt", "bpe.model")
                   if not (model / n).exists()]
        if missing:
            raise FileNotFoundError(f"唤醒词模型缺文件：{model} {missing}")
        keywords = model / "keywords.zongzhu.txt"
        keywords.write_text("\n".join(keyword_lines(words, str(model / "tokens.txt"), str(model / "bpe.model"))) + "\n",
                            encoding="utf-8")
        self.spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(model / "tokens.txt"), encoder=str(model / "encoder.onnx"),
            decoder=str(model / "decoder.onnx"), joiner=str(model / "joiner.onnx"),
            keywords_file=str(keywords), num_threads=1, provider="cpu", max_active_paths=8,
            keywords_score=score, keywords_threshold=threshold, num_trailing_blanks=0)

    def create_stream(self):
        return self.spotter.create_stream()

    def feed(self, stream, pcm):
        """喂一段 16 kHz 16 位 PCM，认出唤醒词就返回它（同时清掉这个 stream 的状态）"""
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        stream.accept_waveform(SAMPLE_RATE, samples)
        found = None
        while self.spotter.is_ready(stream):
            self.spotter.decode_stream(stream)
            result = self.spotter.get_result(stream)
            if result:
                found = result
                self.spotter.reset_stream(stream)
        return found


class WakeListener:
    """一台音箱的唤醒词识别，放在自己的线程里跑（别占住后端的事件循环）。

    feed() 由收麦克风的地方调用；认出来时在那个线程里调 on_wake(word)。
    mute() 期间（比如音箱自己在放"在"）认出来的不算，免得自己唤醒自己；声音照样送进去，
    不然紧跟着"在"喊的唤醒词开头被丢掉，就认不出来了（2026-11-02 实测连着喊没反应）。
    """

    def __init__(self, spotter, on_wake, clock=None, on_ignored=None):
        import time

        self.spotter = spotter
        self.stream = spotter.create_stream()
        self.on_wake = on_wake
        self.on_ignored = on_ignored  # (word) -> None：mute 期间认出来、没算数的
        self.clock = clock or time.monotonic
        self.muted_until = 0.0
        self.queue: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True, name="xiaoai-wake")
        self.thread.start()

    def feed(self, pcm):
        self.queue.put(pcm)

    def mute(self, seconds):
        self.muted_until = max(self.muted_until, self.clock() + seconds)

    def close(self):
        self.queue.put(None)

    def _run(self):
        while (pcm := self.queue.get()) is not None:
            word = self.spotter.feed(self.stream, pcm)
            if not word:
                continue
            if self.clock() >= self.muted_until:
                self.on_wake(word)
            elif self.on_ignored:
                self.on_ignored(word)
