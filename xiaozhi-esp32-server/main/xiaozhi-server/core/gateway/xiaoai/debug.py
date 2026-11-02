"""排查用：把音箱麦克风收到的声音存成 WAV，旁边的 events.tsv 记下后端每个动作的时间（G19i，2026-11-02）。

音箱放出来的声音会被它自己的麦克风录到，所以 WAV 里能看出放出来的是什么、什么时候出来的。
只在配置了 gateway.xiaoai.debug_dir 时开；文件里有你说的话，只放本机。

    gateway:
      xiaoai:
        debug_dir: /path/to/logs/xiaoai-debug   # 每次连上一组文件
        debug_probe: true                       # 连上后放一组测试音（见 probe）
"""
import time
import wave
from datetime import datetime
from pathlib import Path

from core.gateway.xiaoai.protocol import PLAY_CONFIG, silence

MIC_RATE = 16000


class Recorder:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.wav_path = directory / f"mic-{stamp}.wav"
        self.events_path = directory / f"mic-{stamp}.events.tsv"
        self.wav = wave.open(str(self.wav_path), "wb")
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(MIC_RATE)
        self.events = open(self.events_path, "w", encoding="utf-8")
        self.events.write("墙钟秒\t录音位置秒\t事件\n")
        self.start = time.monotonic()
        self.samples = 0

    def mic(self, pcm):
        self.wav.writeframes(pcm)
        self.samples += len(pcm) // 2

    def event(self, text):
        """墙钟秒：从开始录到现在过了多久；录音位置秒：这时已经收到多少秒麦克风声音（两者之差是网络和缓冲的延迟）"""
        self.events.write(f"{time.monotonic() - self.start:.3f}\t{self.samples / MIC_RATE:.3f}\t{text}\n")
        self.events.flush()

    def close(self):
        self.wav.close()
        self.events.close()


def click_train(count=8, gap_ms=200, click_ms=40, freq=1000):
    """count 声短"嘀"，每隔 gap_ms 一声，用来数放出来了几声"""
    from core.gateway.xiaoai.server import beep

    one = beep(freq, click_ms) + silence(gap_ms - click_ms)
    return one * count


async def probe(link, recorder, sleep):
    """连上后放几组测试音。每组 8 声、间隔 0.2 秒；组和组之间空 3 秒。

    A 播放器刚启动、不垫静音，一次发完；B 空闲 3 秒后，不垫静音，一次发完；
    C 空闲 3 秒后，切成 20 毫秒一段、按实时速度发；D 空闲 3 秒后，先发 1 秒静音再发测试音（一次发完）；
    E 重启 aplay 后一次发完；F 4 秒长测试音、分段发且最多领先 1 秒；G 连上时的两声提示音。
    """
    rate = PLAY_CONFIG["sample_rate"]
    train = click_train()

    async def raw_play(pcm, label):
        recorder.event(f"发出 {label}：{len(pcm) / 2 / rate:.3f} 秒")
        await link.send_play(pcm)

    await link.call("start_play", PLAY_CONFIG)
    recorder.event("start_play 已回应")
    await raw_play(train, "A 刚启动")
    await sleep(len(train) / 2 / rate + 3)
    await raw_play(train, "B 空闲 3 秒后")
    await sleep(len(train) / 2 / rate + 3)
    chunk = rate * 2 * 20 // 1000
    recorder.event("开始 C 分段实时发")
    for i in range(0, len(train), chunk):
        await link.send_play(train[i:i + chunk])
        await sleep(0.02)
    recorder.event("C 发完")
    await sleep(3)
    await raw_play(silence(1000) + train, "D 先 1 秒静音")
    await sleep(len(train) / 2 / rate + 3)

    # E 空闲后先重启 aplay（stop_play + start_play）再一次发完
    await link.call("stop_play")
    await link.call("start_play", PLAY_CONFIG)
    recorder.event("E 重启 aplay 已回应")
    await raw_play(train, "E 重启后")
    await sleep(len(train) / 2 / rate + 3)

    # F 4 秒长测试音（20 声），重启 aplay 后每次发 0.5 秒、始终最多领先 1 秒
    long_train = click_train(count=20)
    await link.call("stop_play")
    await link.call("start_play", PLAY_CONFIG)
    recorder.event(f"F 开始：{len(long_train) / 2 / rate:.3f} 秒，分段发")
    piece = rate  # 0.5 秒的字节数
    start = None
    import time
    for i in range(0, len(long_train), piece):
        if start is None:
            start = time.monotonic()
        ahead = i / 2 / rate - (time.monotonic() - start)
        if ahead > 1.0:
            await sleep(ahead - 1.0)
        await link.send_play(long_train[i:i + piece])
    recorder.event("F 发完")
    await sleep(len(long_train) / 2 / rate + 2)

    # G 连上时的那两声提示音（880 和 1320 赫兹），重启 aplay 后原样放
    from core.gateway.xiaoai.server import beep
    await link.call("stop_play")
    await link.call("start_play", PLAY_CONFIG)
    await raw_play(beep(880) + silence(100) + beep(1320) + silence(200), "G 连上提示音两声（880、1320 赫兹）")
    await sleep(3)
    recorder.event("测试音结束")
