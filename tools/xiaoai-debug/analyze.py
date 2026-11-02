"""分析音箱调试录音：python tools/xiaoai-debug/analyze.py <mic-*.wav> [--kws <模型目录>] [--from 秒] [--to 秒]

1. 每 10 毫秒的音量（均方根），找出响的段落（高于底噪 4 倍且持续 ≥20 毫秒）
2. --kws：把录音离线喂给唤醒词模型，列出认出的位置
"""
import argparse
import math
import struct
import sys
import wave
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("wav")
ap.add_argument("--kws")
ap.add_argument("--from", dest="start", type=float, default=0)
ap.add_argument("--to", dest="end", type=float, default=1e9)
ap.add_argument("--profile", action="store_true", help="打印每 10 毫秒的音量")
args = ap.parse_args()

w = wave.open(args.wav)
rate = w.getframerate()
data = w.readframes(w.getnframes())
samples = struct.unpack(f"<{len(data)//2}h", data)
if w.getnchannels() == 4:  # 4 声道录音：只看 3 个麦克风的平均（和后端认唤醒词用的一样）
    samples = [int(sum(samples[i:i + 3]) / 3) for i in range(0, len(samples), 4)]
print(f"录音 {len(samples)/rate:.2f} 秒")

step = rate // 100
levels = []
for i in range(0, len(samples) - step, step):
    chunk = samples[i:i + step]
    levels.append(math.sqrt(sum(v * v for v in chunk) / step))
floor = sorted(levels)[len(levels) // 5] or 1
print(f"底噪（20% 分位）{floor:.0f}")

segs, cur = [], None
for k, lv in enumerate(levels):
    t = k / 100
    if lv > floor * 4:
        if cur is None:
            cur = [t, t, lv]
        cur[1], cur[2] = t, max(cur[2], lv)
    elif cur is not None:
        if cur[1] - cur[0] >= 0.02:
            segs.append(cur)
        cur = None
for a, b, peak in segs:
    if args.start <= a <= args.end:
        print(f"响 {a:7.2f} – {b+0.01:7.2f} 秒（{(b-a)*1000+10:4.0f} 毫秒）峰值 {peak:6.0f}")

if args.profile:
    for k, lv in enumerate(levels):
        if args.start <= k / 100 <= args.end:
            print(f"{k/100:7.2f} {lv:7.0f} {'#' * int(min(60, lv / floor))}")

if args.kws:
    sys.path.insert(0, str(Path(args.kws).resolve().parents[1]))
    import numpy as np
    import sherpa_onnx
    m = Path(args.kws)
    spotter = sherpa_onnx.KeywordSpotter(
        tokens=str(m / "tokens.txt"), encoder=str(m / "encoder.onnx"), decoder=str(m / "decoder.onnx"),
        joiner=str(m / "joiner.onnx"), keywords_file=str(m / "keywords.zongzhu.txt"), num_threads=1,
        provider="cpu", max_active_paths=8, keywords_score=2.0, keywords_threshold=0.2, num_trailing_blanks=0)
    stream = spotter.create_stream()
    chunk = 360  # 和音箱一样每次 22.5 毫秒
    arr = np.array(samples, dtype=np.float32) / 32768
    for i in range(0, len(arr), chunk):
        stream.accept_waveform(rate, arr[i:i + chunk])
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
            r = spotter.get_result(stream)
            if r:
                print(f"模型认出 {r} @ 录音 {(i + chunk) / rate:.2f} 秒")
                spotter.reset_stream(stream)
