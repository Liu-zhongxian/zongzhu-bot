"""合成识别对比用的测试音频（16kHz 单声道 wav）。

用 macOS 自带的 say 合成（2026-10-22 本机 EdgeTTS 返回 403）；音色名以 zh-CN- 开头时改用 EdgeTTS。
每句用两种音色各合成一遍，再各做一份加噪声的版本（信噪比约 15dB），
输出目录里的 manifest.tsv 记录 文件名<TAB>正确文字。

用法（在后端的 Python 环境里运行）：
  python tools/asr-bench/make_testset.py --out <输出目录> [--sentences tools/asr-bench/sentences.txt]
真实录音可以照 manifest.tsv 的格式自己放进同一个目录，对比脚本一视同仁。
"""

import argparse
import asyncio
import os
import subprocess
import wave

import numpy as np

VOICES = ["Tingting", "Eddy (中文（中国大陆）)"]
SNR_DB = 15


def to_wav16k(src: str, dst: str):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", "16000",
                    "-sample_fmt", "s16", dst], check=True)


async def synthesize(text: str, voice: str, dst: str):
    if voice.startswith("zh-CN-"):
        import edge_tts

        await edge_tts.Communicate(text, voice).save(dst)
    else:
        subprocess.run(["say", "-v", voice, "--file-format=AIFF", "-o", dst, text], check=True)


def add_noise(src: str, dst: str, seed: int):
    with wave.open(src) as f:
        params = f.getparams()
        x = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32)
    rng = np.random.default_rng(seed)
    # 粉红噪声比白噪声更像室内底噪
    white = rng.standard_normal(len(x))
    spectrum = np.fft.rfft(white)
    spectrum /= np.sqrt(np.maximum(np.arange(len(spectrum)), 1))
    noise = np.fft.irfft(spectrum, n=len(x))
    power = np.mean(x ** 2) / (10 ** (SNR_DB / 10))
    noise *= np.sqrt(power / np.mean(noise ** 2))
    y = np.clip(x + noise, -32768, 32767).astype(np.int16)
    with wave.open(dst, "wb") as f:
        f.setparams(params)
        f.writeframes(y.tobytes())


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--sentences", default=os.path.join(os.path.dirname(__file__), "sentences.txt"))
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    with open(args.sentences, encoding="utf-8") as f:
        sentences = [line.strip() for line in f if line.strip()]

    rows = []
    for i, text in enumerate(sentences, 1):
        for v, voice in enumerate(VOICES):
            base = f"s{i:02d}-v{v}"
            raw = os.path.join(args.out, base + ".raw")
            clean = os.path.join(args.out, base + "-clean.wav")
            noisy = os.path.join(args.out, base + "-noisy.wav")
            if not os.path.exists(clean):
                await synthesize(text, voice, raw)
                to_wav16k(raw, clean)
                os.remove(raw)
            if not os.path.exists(noisy):
                add_noise(clean, noisy, seed=i * 10 + v)
            rows += [(os.path.basename(clean), text), (os.path.basename(noisy), text)]
        print(f"{i}/{len(sentences)} {text}")

    with open(os.path.join(args.out, "manifest.tsv"), "w", encoding="utf-8") as f:
        f.writelines(f"{name}\t{text}\n" for name, text in rows)
    print(f"共 {len(rows)} 段，清单：{os.path.join(args.out, 'manifest.tsv')}")


if __name__ == "__main__":
    asyncio.run(main())
