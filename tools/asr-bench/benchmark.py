"""用同一批音频比较语音识别：错字率、每句耗时、加载时间、内存。

直接调用后端里的识别类（FunASR 用 fun_local，X-ASR 用 sherpa_onnx_local），和板子连上后走的是同一段代码。
每次只跑一种识别，内存数字才不会互相干扰。

用法（工作目录是后端的 main/xiaozhi-server）：
  python <仓库>/tools/asr-bench/benchmark.py --engine funasr --testset <目录> --out result.json
  python <仓库>/tools/asr-bench/benchmark.py --engine xasr   --testset <目录> --out result.json [--no-hotwords]
测试目录里要有 manifest.tsv（文件名<TAB>正确文字），见 make_testset.py。
"""

import argparse
import asyncio
import json
import os
import re
import resource
import sys
import tempfile
import time
import wave

import psutil

sys.path.insert(0, os.getcwd())

PUNCT = re.compile(r"[\s，。？！、,.?!;；:：\"“”'‘’()（）\-]")


def normalize(text: str) -> str:
    return PUNCT.sub("", text or "").lower()


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1024 / 1024


def load_engine(name: str, config: dict, hotwords: bool, tmp: str):
    if name == "funasr":
        from core.providers.asr.fun_local import ASRProvider
        from core.providers.asr.utils import lang_tag_filter

        entry = dict(config["ASR"]["FunASR"], output_dir=tmp)
        provider = ASRProvider(entry, True)

        def recognize(path: str) -> str:
            with wave.open(path) as f:
                pcm = f.readframes(f.getnframes())
            result = provider.model.generate(input=pcm, cache={}, language=provider.language,
                                             use_itn=True, batch_size_s=60)
            return lang_tag_filter(result[0]["text"])["content"]

        return recognize

    from core.utils.asr_text import hotwords_of
    from core.providers.asr.sherpa_onnx_local import ASRProvider

    entry = dict(config["ASR"]["SherpaXASR"], output_dir=tmp)
    if hotwords:
        entry["hotwords"] = hotwords_of(config)
    provider = ASRProvider(entry, True)

    def recognize(path: str) -> str:
        stream = provider.model.create_stream()
        samples, rate = provider.read_wave(path)
        stream.accept_waveform(rate, samples)
        provider.model.decode_stream(stream)
        return stream.result.text

    return recognize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["funasr", "xasr"], required=True)
    parser.add_argument("--testset", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--no-hotwords", action="store_true", help="X-ASR 不加热词（对照用）")
    args = parser.parse_args()

    from config.config_loader import load_config
    from core.utils.asr_text import fix_asr_result

    config = asyncio.run(load_config())
    with open(os.path.join(args.testset, "manifest.tsv"), encoding="utf-8") as f:
        items = [line.rstrip("\n").split("\t", 1) for line in f if line.strip()]

    rss_before = rss_mb()
    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.monotonic()
        recognize = load_engine(args.engine, config, not args.no_hotwords, tmp)
        load_s = time.monotonic() - t0
        rss_loaded = rss_mb()
        recognize(os.path.join(args.testset, items[0][0]))  # 预热，不计时

        rows = []
        for name, ref in items:
            path = os.path.join(args.testset, name)
            with wave.open(path) as f:
                audio_s = f.getnframes() / f.getframerate()
            t = time.monotonic()
            raw = recognize(path)
            cost = time.monotonic() - t
            fixed = fix_asr_result(raw, config)
            r = normalize(ref)
            rows.append({
                "file": name, "ref": ref, "raw": raw, "corrected": fixed,
                "audio_s": round(audio_s, 2), "time_s": round(cost, 3),
                "errors_raw": edit_distance(r, normalize(raw)),
                "errors": edit_distance(r, normalize(fixed)), "chars": len(r),
            })

    def summary(subset):
        chars = sum(x["chars"] for x in subset) or 1
        times = sorted(x["time_s"] for x in subset)
        wake = [x for x in subset if "宗主" in x["ref"]]
        return {
            "clips": len(subset),
            "cer_raw": round(sum(x["errors_raw"] for x in subset) / chars, 4),
            "cer": round(sum(x["errors"] for x in subset) / chars, 4),
            "exact": sum(x["errors"] == 0 for x in subset),
            "zongzhu_ok": f'{sum("宗主" in x["corrected"] for x in wake)}/{len(wake)}',
            "time_avg_s": round(sum(times) / len(times), 3),
            "time_p90_s": times[int(len(times) * 0.9) - 1],
            "rtf": round(sum(times) / sum(x["audio_s"] for x in subset), 4),
        }

    result = {
        "engine": args.engine, "hotwords": args.engine == "xasr" and not args.no_hotwords,
        "load_s": round(load_s, 2), "rss_model_mb": round(rss_loaded - rss_before),
        "rss_peak_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024),
        "all": summary(rows),
        "clean": summary([x for x in rows if "-clean" in x["file"]]),
        "noisy": summary([x for x in rows if "-noisy" in x["file"]]),
        "other": summary([x for x in rows if "-clean" not in x["file"] and "-noisy" not in x["file"]])
        if any("-clean" not in x["file"] and "-noisy" not in x["file"] for x in rows) else None,
        "rows": rows,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
