"""离线比较唤醒词识别的几种喂法：python tools/xiaoai-debug/kws_eval.py <模型目录> <wav>...

"喊"的位置自动找：高于底噪 4 倍、连续 ≥0.9 秒、峰值 >20000 的段（"在"只有约 0.3 秒，不会算进去）。
每段喊的开始到结束后 2.0 秒内认出来算认出；不在任何一段喊里的认出算误报。
"""
import sys
import wave
from pathlib import Path

import numpy as np
import sherpa_onnx

model = Path(sys.argv[1])
recordings = []
for path in sys.argv[2:]:
    w = wave.open(path)
    rate = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    if w.getnchannels() == 4:  # 4 声道录音：3 个麦克风的平均（和后端认唤醒词用的一样）
        x = x.reshape(-1, 4)[:, :3].mean(axis=1)
    step = rate // 100
    lv = np.sqrt(np.mean(x[: len(x) // step * step].reshape(-1, step) ** 2, axis=1)) * 32768
    floor = np.sort(lv)[len(lv) // 5]
    loud = lv > floor * 4
    calls, k = [], 0
    while k < len(loud):
        if loud[k]:
            j = k
            while j < len(loud) and (loud[j] or (j + 1 < len(loud) and loud[j + 1])):
                j += 1
            if (j - k) >= 90 and lv[k:j].max() > 20000 / 2.5:
                calls.append((k / 100, j / 100))
            k = j
        k += 1
    recordings.append((Path(path).name, x, rate, calls))
    print(f"{Path(path).name}: {len(calls)} 次喊")


def spotter(th):
    return sherpa_onnx.KeywordSpotter(
        tokens=str(model / "tokens.txt"), encoder=str(model / "encoder.onnx"), decoder=str(model / "decoder.onnx"),
        joiner=str(model / "joiner.onnx"), keywords_file=str(model / "keywords.zongzhu.txt"), num_threads=1,
        provider="cpu", max_active_paths=8, keywords_score=2.0, keywords_threshold=th, num_trailing_blanks=0)


def run(mode, th, x, rate):
    s = spotter(th)
    st = s.create_stream()
    hits = []
    chunk = 360
    silent = 0
    active = False
    for i in range(0, len(x), chunk):
        piece = x[i:i + chunk]
        level = np.sqrt(np.mean(piece ** 2)) * 32768 if len(piece) else 0
        if mode == "vad":
            if level > 1500:
                if not active:
                    st = s.create_stream()  # 一段新的说话：新的识别状态
                    active = True
                silent = 0
            elif active:
                silent += 1
                if silent * chunk / rate >= 0.3:
                    active = False
            if not active:
                continue
        st.accept_waveform(rate, piece)
        while s.is_ready(st):
            s.decode_stream(st)
            if s.get_result(st):
                hits.append((i + chunk) / rate)
                if mode == "reset":
                    s.reset_stream(st)
                else:
                    st = s.create_stream()
    return hits


for mode in ("reset", "new", "vad"):
    for th in (0.2, 0.15):
        total = got = false = 0
        detail = []
        for name, x, rate, calls in recordings:
            hits = run(mode, th, x, rate)
            ok = [c for c in calls if any(c[0] < h < c[1] + 2.0 for h in hits)]
            false += sum(1 for h in hits if not any(c[0] < h < c[1] + 2.0 for c in calls))
            total += len(calls)
            got += len(ok)
            detail.append(f"{name[4:17]} 漏 {[round(c[0], 1) for c in calls if c not in ok]}")
        print(f"{mode:5} 阈值 {th}: 认出 {got}/{total}，误报 {false}；" + "；".join(detail))
