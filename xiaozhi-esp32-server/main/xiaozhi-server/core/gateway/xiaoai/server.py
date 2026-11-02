"""在宗主后端开 4399 端口接小米音箱（G19i）。第 1 步：连上后放提示音、报麦克风音量；第 2 步：认唤醒词，回"在"；
第 3 步：唤醒后当成一块板子和后端对话（device.py）。"""
import asyncio
import math
import struct
import time
from http import HTTPStatus
from pathlib import Path

import websockets

from config.logger import setup_logging
from core.gateway import status
from core.gateway.xiaoai import debug, prompts, wake
from core.gateway.xiaoai.device import BOARD_TYPE, SpeakerDevice
from core.gateway.xiaoai.protocol import PLAY_CONFIG, ClientError, SpeakerLink, silence

TAG = __name__
logger = setup_logging()

DEFAULT_PORT = 4399
LEVEL_REPORT_SECONDS = 15  # 连上后这么久里每秒报一次麦克风音量（第 1 步验收用）
WAKE_REPLY = "在"
# 放"在"后再多这么久不认唤醒词（音箱放出来比发出去晚约 0.1 秒，加上房间回声）
REPLY_ECHO_SECONDS = 0.2
LISTEN_AFTER_REPLY = 0.15  # "在"放完再过这么久开始把麦克风发给后端（别把"在"的回声当成你说的话）


def settings(config):
    return (config.get("gateway") or {}).get("xiaoai") or {}


def read_token(xiaoai):
    """token 文件的内容；没配或读不到返回空串（这时拒绝所有连接）"""
    path = str(xiaoai.get("token_file") or "").strip()
    if not path:
        return ""
    try:
        return Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def beep(freq=880, ms=150, rate=PLAY_CONFIG["sample_rate"], volume=0.3):
    """一声提示音（16 位单声道 PCM），首尾各 10 毫秒淡入淡出，免得咔哒一声"""
    count = rate * ms // 1000
    fade = rate // 100
    samples = []
    for i in range(count):
        gain = min(1.0, i / fade, (count - 1 - i) / fade)
        samples.append(int(32767 * volume * gain * math.sin(2 * math.pi * freq * i / rate)))
    return struct.pack(f"<{count}h", *samples)


class LevelMeter:
    """把麦克风 PCM 攒满一秒报一次音量（均方根，0–32767），只报连上后的头几秒"""

    def __init__(self, report, seconds=LEVEL_REPORT_SECONDS, rate=16000):
        self.report = report
        self.until = time.monotonic() + seconds
        self.window = rate * 2  # 一秒的字节数
        self.buffer = bytearray()

    def feed(self, pcm):
        if time.monotonic() > self.until:
            return
        self.buffer += pcm
        while len(self.buffer) >= self.window:
            chunk, self.buffer = bytes(self.buffer[:self.window]), self.buffer[self.window:]
            count = len(chunk) // 2
            values = struct.unpack(f"<{count}h", chunk)
            self.report(int(math.sqrt(sum(v * v for v in values) / count)))


class XiaoaiServer:
    def __init__(self, config, ws_server=None):
        self.config = config
        self.ws_server = ws_server  # 有它才接对话（用它已经加载好的 VAD、ASR 这些）；没有就只认唤醒词
        self.links: set[SpeakerLink] = set()
        self.spotter = None
        self.ready = asyncio.Event()  # 端口开好了（测试用）

    def _load_spotter(self, xiaoai):
        words = xiaoai.get("wake_words") or list(wake.DEFAULT_WAKE_WORDS)
        try:
            self.spotter = wake.Spotter(xiaoai.get("kws_model_dir") or wake.DEFAULT_MODEL_DIR, words,
                                        score=float(xiaoai.get("kws_score", 2.0)),
                                        threshold=float(xiaoai.get("kws_threshold", wake.DEFAULT_THRESHOLD)))
            logger.bind(tag=TAG).info(f"音箱唤醒词：{'、'.join(words)}")
        except Exception as e:
            logger.bind(tag=TAG).error(f"音箱唤醒词识别没有启动：{type(e).__name__} {e}")

    def _check_auth(self, connection, request):
        token = read_token(settings(self.config))
        if not token or request.headers.get("Authorization", "") != f"Bearer {token}":
            logger.bind(tag=TAG).warning(f"音箱连接被拒绝（token 不对）：{connection.remote_address[0]}")
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized\n")
        return None

    async def start(self):
        xiaoai = settings(self.config)
        if not xiaoai.get("enabled"):
            return
        port = int(xiaoai.get("port") or DEFAULT_PORT)
        if not read_token(xiaoai):
            logger.bind(tag=TAG).error("gateway.xiaoai.token_file 没配或读不到，不接音箱")
            return
        await asyncio.to_thread(self._load_spotter, xiaoai)
        try:
            async with websockets.serve(self._handle, "0.0.0.0", port, process_request=self._check_auth,
                                        ping_interval=None, max_size=None):
                logger.bind(tag=TAG).info(f"小米音箱接入：ws://0.0.0.0:{port}")
                self.ready.set()
                await asyncio.Future()
        except OSError as e:
            # 多半是 xiaoai-bridge 还在跑，占着 4399
            logger.bind(tag=TAG).error(f"小米音箱接入没有启动：端口 {port} 被占用（xiaoai-bridge 还在跑？）{e}")

    async def _handle(self, ws):
        address = ws.remote_address[0]
        loop = asyncio.get_running_loop()
        xiaoai = settings(self.config)
        recorder = debug.Recorder(xiaoai["debug_dir"]) if xiaoai.get("debug_dir") else None
        if recorder:
            logger.bind(tag=TAG).info(f"音箱调试录音：{recorder.wav_path}")
        note = recorder.event if recorder else (lambda text: None)
        meter = LevelMeter(lambda level: logger.bind(tag=TAG).info(f"音箱麦克风音量：{level}"))
        link = SpeakerLink(ws, on_event=lambda event, data: logger.bind(tag=TAG).debug(f"音箱事件 {event}: {data}"))
        listener = None
        device = None
        if self.spotter:
            listener = wake.WakeListener(
                self.spotter, lambda word: loop.call_soon_threadsafe(self._woken, link, listener, word, note, device),
                on_ignored=lambda word: loop.call_soon_threadsafe(note, f"认出唤醒词但在放声音，忽略：{word}"))

        def on_record(pcm):
            if recorder:
                recorder.mic(pcm)
            meter.feed(pcm)
            if device:
                device.on_mic(pcm)
                if device.player.busy():
                    # 音箱在放声音时认出来的不算（自己的声音被麦克风录到）
                    listener and listener.mute(device.speaking_for() + REPLY_ECHO_SECONDS)
            if listener:
                listener.feed(pcm)

        link.on_record = on_record
        self.links.add(link)
        runner = asyncio.create_task(link.run())
        warm = asyncio.create_task(prompts.phrase(self.config, WAKE_REPLY))  # 先合成好"在"
        warm.add_done_callback(lambda t: t.cancelled() or t.exception())  # 失败了唤醒时再合成一次
        try:
            version = await link.call("get_version")
            logger.bind(tag=TAG).info(f"小米音箱已连接：{address}，Client 版本 {version}")
            if self.ws_server:
                device_id = str(xiaoai.get("device_id") or f"xiaoai-{address}")
                status.note_ota(device_id, BOARD_TYPE, f"Client {version}", address)
                words = xiaoai.get("wake_words") or list(wake.DEFAULT_WAKE_WORDS)
                device = SpeakerDevice(link, self.ws_server, device_id, address, words[0], note)
            await link.start_recording()
            note("start_recording 已回应")
            if recorder and xiaoai.get("debug_probe"):
                await debug.probe(link, recorder, asyncio.sleep)
                link._playing = True
            else:
                # 一声：以前两声只隔 0.1 秒，录音里两声都放出来了，但被回声连成一片，听起来像一声
                await link.play(beep(1320, 200))
                note("发出连上提示音")
            await runner
        except (ConnectionError, ClientError, asyncio.TimeoutError, websockets.ConnectionClosed) as e:
            logger.bind(tag=TAG).warning(f"小米音箱连接出错：{address} {type(e).__name__} {e}")
        finally:
            runner.cancel()
            warm.cancel()
            if device:
                await device.close()
            if listener:
                listener.close()
            if recorder:
                recorder.close()
            self.links.discard(link)
            logger.bind(tag=TAG).info(f"小米音箱断开：{address}")

    def _woken(self, link, listener, word, note=lambda text: None, device=None):
        logger.bind(tag=TAG).info(f"音箱唤醒：{word}")
        note(f"认出唤醒词：{word}")
        asyncio.create_task(self._reply(link, listener, note, device))

    async def _reply(self, link, listener, note=lambda text: None, device=None):
        """回一声"在"（合成不出来就用提示音代替）；接了对话的话，"在"放完开始听"""
        try:
            pcm = await prompts.phrase(self.config, WAKE_REPLY)
        except Exception as e:
            logger.bind(tag=TAG).warning(f"合成「{WAKE_REPLY}」失败，用提示音代替：{type(e).__name__} {e}")
            pcm = beep(1320)
        length = len(pcm) / (2 * PLAY_CONFIG["sample_rate"])
        # 放的时候认出来的不算
        seconds = length + REPLY_ECHO_SECONDS
        listener.mute(seconds)
        if device:
            device.interrupt()
            device.player.add(pcm)
            note(f"发出「{WAKE_REPLY}」：{length:.3f} 秒，忽略唤醒 {seconds:.3f} 秒")
            await device.start_listening(length + LISTEN_AFTER_REPLY)
            return
        try:
            await link.play(pcm)
            note(f"发出「{WAKE_REPLY}」：{length:.3f} 秒，忽略唤醒 {seconds:.3f} 秒")
        except (ConnectionError, ClientError, asyncio.TimeoutError, websockets.ConnectionClosed) as e:
            logger.bind(tag=TAG).warning(f"放「{WAKE_REPLY}」失败：{type(e).__name__} {e}")
