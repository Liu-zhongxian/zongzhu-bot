"""在宗主后端开 4399 端口接小米音箱（G19i）。第 1 步：连上后放提示音、报麦克风音量。"""
import asyncio
import math
import struct
import time
from http import HTTPStatus
from pathlib import Path

import websockets

from config.logger import setup_logging
from core.gateway.xiaoai.protocol import PLAY_CONFIG, ClientError, SpeakerLink

TAG = __name__
logger = setup_logging()

DEFAULT_PORT = 4399
LEVEL_REPORT_SECONDS = 15  # 连上后这么久里每秒报一次麦克风音量（第 1 步验收用）


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


def silence(ms, rate=PLAY_CONFIG["sample_rate"]):
    return b"\0\0" * (rate * ms // 1000)


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
    def __init__(self, config):
        self.config = config
        self.links: set[SpeakerLink] = set()

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
        try:
            async with websockets.serve(self._handle, "0.0.0.0", port, process_request=self._check_auth,
                                        ping_interval=None, max_size=None):
                logger.bind(tag=TAG).info(f"小米音箱接入：ws://0.0.0.0:{port}")
                await asyncio.Future()
        except OSError as e:
            # 多半是 xiaoai-bridge 还在跑，占着 4399
            logger.bind(tag=TAG).error(f"小米音箱接入没有启动：端口 {port} 被占用（xiaoai-bridge 还在跑？）{e}")

    async def _handle(self, ws):
        address = ws.remote_address[0]
        meter = LevelMeter(lambda level: logger.bind(tag=TAG).info(f"音箱麦克风音量：{level}"))
        link = SpeakerLink(ws, on_record=meter.feed,
                           on_event=lambda event, data: logger.bind(tag=TAG).debug(f"音箱事件 {event}: {data}"))
        self.links.add(link)
        runner = asyncio.create_task(link.run())
        try:
            version = await link.call("get_version")
            logger.bind(tag=TAG).info(f"小米音箱已连接：{address}，Client 版本 {version}")
            await link.start_recording()
            await link.play(beep(880) + silence(100) + beep(1320) + silence(200))
            await runner
        except (ConnectionError, ClientError, asyncio.TimeoutError, websockets.ConnectionClosed) as e:
            logger.bind(tag=TAG).warning(f"小米音箱连接出错：{address} {type(e).__name__} {e}")
        finally:
            runner.cancel()
            self.links.discard(link)
            logger.bind(tag=TAG).info(f"小米音箱断开：{address}")
