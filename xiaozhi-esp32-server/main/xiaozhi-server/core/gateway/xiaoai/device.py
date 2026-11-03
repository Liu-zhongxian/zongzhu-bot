"""音箱当成一块小智板子接进后端（G19i 第 3 步）。

ConnectionHandler 只用到 websocket 的几样东西（请求头和路径、对方地址、逐条收消息、send、close），
这里给它一个进程内的 VirtualSocket：板子发给后端的消息由我们塞进去，后端发给板子的交给 SpeakerDevice 处理。
后端那边的识别、网关、TTS、等待和待汇报全部照用，和板子一样。

音箱这一端照板子固件的做法，只有三种状态：
- idle：后端认唤醒词（wake.py）。认出来就回"在"，连上后端（没连着的话）、发 listen start（auto），转到 listening。
- listening：麦克风编成 opus 发给后端，后端自己判断说完（Silero VAD）。后端回 stt 或开始说话就不再发；
  10 秒没认出一句话就回 idle。认出一句话（stt）以后是 thinking，20 秒后端还没开始说也回 idle。
- speaking：后端发 tts start 以后。opus 解码成 24 kHz PCM，分段、按播放速度发给音箱（一次发多了音箱会丢，
  见 protocol.py）。tts stop 并且声音放完以后回 idle：和宗主板子一样，回答完直接待机。
没在 listening 时后端发来的声音（比如 Bot 晚到的回答）照样放。说的时候喊唤醒词就打断（server.py 回"在"前调 interrupt）。
"""
import asyncio
import json
import time
import uuid
from types import SimpleNamespace

import opuslib_next

from config.logger import setup_logging
from core.gateway import status
from core.gateway.xiaoai.protocol import PLAY_CONFIG

TAG = __name__
logger = setup_logging()

BOARD_TYPE = "open-xiaoai"
MIC_RATE = 16000
FRAME_MS = 60
FRAME_BYTES = MIC_RATE * FRAME_MS // 1000 * 2
LISTEN_TIMEOUT = 10        # 唤醒后这么久没认出一句话就回 idle
THINK_TIMEOUT = 20         # 认出一句话以后这么久后端还没开始说就回 idle（Bot 晚到的回答之后照样放）
# 开始听：等音箱真的放完（录音的 ch3 静下来）再过这么久才把麦克风发给后端。2026-11-02 录音：
# "在"发出后约 0.4 秒才从音箱出来，放完后房间回声还拖 0.3–0.5 秒；按"在"的长度估时间开始听，
# 后端把"在"、回声、被打断还没放完的回答当成了你说的话（认出"在""嗯""回复后会显示"）。
ECHO_TAIL = 0.5
PLAYBACK_WAIT = 1.5        # 唤醒回了"在"以后，录音里这么久还没出现音箱出声，就不等了（比如"在"没放出来）
SEND_AHEAD = 1.0           # 发给音箱的声音最多比实际播放领先这么多秒
SEND_PIECE = 0.5           # 每次最多发这么多秒
HELLO = {"type": "hello", "version": 1, "transport": "websocket", "features": {},
         "audio_params": {"format": "opus", "sample_rate": MIC_RATE, "channels": 1, "frame_duration": FRAME_MS}}


class VirtualSocket:
    """ConnectionHandler 看到的 websocket"""

    def __init__(self, headers, address, on_send, on_close):
        self.request = SimpleNamespace(headers=headers, path="/xiaozhi/v1/")
        self.remote_address = (address, 0)
        self.state = SimpleNamespace(name="OPEN")
        self.closed = False
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._on_send = on_send
        self._on_close = on_close

    def put(self, message):
        """板子发给后端的一条消息（str 是 JSON，bytes 是 opus）"""
        if not self.closed:
            self._inbox.put_nowait(message)

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self._inbox.get()
        if message is None:
            raise StopAsyncIteration
        return message

    async def send(self, message):
        if not self.closed:
            await self._on_send(message)

    async def close(self):
        if not self.closed:
            self.closed = True
            self.state.name = "CLOSED"
            self._inbox.put_nowait(None)
            self._on_close()


# 排查卡顿（G19j，2026-11-02 "月亮的小故事中间有点卡顿"，录音里只看得出句子之间停 0.6–1.4 秒）：
# 两句声音之间没接上超过这么久，在调试记录里写一笔"音箱空了"；更久的是两段话之间，不记
GAP_NOTE = (0.05, 5.0)


class Player:
    """把后端发来的 PCM 分段、按播放速度发给音箱。

    note（调试记录）里写：每句的第一段声音什么时候发给音箱（mark），音箱什么时候空着等声音（缓冲断了）。
    """

    def __init__(self, link, rate=PLAY_CONFIG["sample_rate"], clock=time.monotonic, sleep=asyncio.sleep,
                 note=lambda text: None):
        self.link = link
        self.bytes_per_second = rate * 2
        self.clock = clock
        self.sleep = sleep
        self.note = note
        self.buffer = bytearray()
        self.play_end = 0.0  # 已经发出去的声音大约放到什么时候
        self.received = 0    # 一共收到多少字节
        self.sent = 0        # 一共发出去多少字节（清掉的也算，和 received 对齐）
        self.marks = []      # (收到第几个字节时开始的, 句子)
        self.wakeup = asyncio.Event()
        self.task = asyncio.create_task(self._run())

    def add(self, pcm):
        self.buffer += pcm
        self.received += len(pcm)
        self.wakeup.set()

    def mark(self, text):
        """接下来收到的声音是这一句的"""
        self.marks.append((self.received, text))

    def clear(self):
        self.sent += len(self.buffer)
        self.buffer.clear()
        self.marks.clear()

    def playing_recently(self, seconds):
        """还在放，或者放完不到 seconds 秒"""
        return bool(self.buffer) or self.clock() < self.play_end + seconds

    def busy(self):
        """还有没发的，或者发出去的还没放完"""
        return bool(self.buffer) or self.clock() < self.play_end

    async def _run(self):
        piece = int(self.bytes_per_second * SEND_PIECE) // 2 * 2
        while True:
            if not self.buffer:
                self.wakeup.clear()
                await self.wakeup.wait()
                continue
            now = self.clock()
            ahead = self.play_end - now
            if ahead > SEND_AHEAD:
                await self.sleep(ahead - SEND_AHEAD)
                continue
            chunk = bytes(self.buffer[:piece])
            del self.buffer[:piece]
            gap = now - self.play_end
            if self.play_end and GAP_NOTE[0] < gap < GAP_NOTE[1]:
                self.note(f"音箱空了 {gap:.2f} 秒（上一段放完，下一段还没到）")
            while self.marks and self.marks[0][0] <= self.sent:
                self.note(f"开始放：{self.marks.pop(0)[1]}（约 {max(0.0, self.play_end - now):.2f} 秒后出声）")
            self.sent += len(chunk)
            self.play_end = max(now, self.play_end) + len(chunk) / self.bytes_per_second
            try:
                await self.link.play(chunk)
            except Exception as e:
                logger.bind(tag=TAG).warning(f"发给音箱的声音没发出去：{type(e).__name__} {e}")

    def close(self):
        self.task.cancel()


class SpeakerDevice:
    def __init__(self, link, ws_server, device_id, address, wake_word, note=lambda text: None,
                 clock=time.monotonic):
        self.link = link
        self.ws_server = ws_server
        self.device_id = device_id
        self.address = address
        self.wake_word = wake_word
        self.note = note
        self.clock = clock
        self.state = "idle"
        self.listen_since = 0.0
        self.think_since = 0.0
        self.handler = None
        self.socket = None
        self.hello = None
        self.player = Player(link, clock=clock, note=note)
        self.encoder = opuslib_next.Encoder(MIC_RATE, 1, opuslib_next.APPLICATION_VOIP)
        self.decoder = None
        self.mic = bytearray()
        self.heard = 0.0            # 收到的录音一共多少秒（开始听的判断都按录音的时间算，和网络延迟无关）
        self.last_playback = -1e9   # 录音里最后一次音箱出声在哪
        self.listen_mark = 0.0      # 开始听时录音到哪
        self.waiting_playback = False
        self.mic_open = False
        self.call_agent = None      # 喊了某个 AI 的呼名唤醒：连上后换成它
        self.tts_done = False
        self.client_id = str(uuid.uuid4())
        self.watch = asyncio.create_task(self._watch())

    # 连后端

    def connected(self):
        return self.socket is not None and not self.socket.closed

    async def connect(self):
        if self.connected():
            return True
        from core.connection import ConnectionHandler

        server = self.ws_server
        self.hello = asyncio.Event()
        self.socket = VirtualSocket({"device-id": self.device_id, "client-id": self.client_id},
                                    self.address, self._from_server, self._closed)
        self.handler = ConnectionHandler(server.config, server._vad, server._asr, server._llm,
                                         server._memory, server._intent, server)
        # 音箱是单独的一路：不用网关技能（本地音乐在这台 Mac 上放，和音箱无关），话只交给 AI。
        # 要在 hello 之前设：后端收到 hello 就按它预合成短句、预启动技能
        self.handler.gateway_skills = []
        asyncio.create_task(self.handler.handle_connection(self.socket))
        self.socket.put(json.dumps(HELLO))
        try:
            await asyncio.wait_for(self.hello.wait(), 5)
        except asyncio.TimeoutError:
            logger.bind(tag=TAG).warning("音箱连后端：5 秒没收到 hello 回应")
            return False
        self.decoder = opuslib_next.Decoder(self.handler.sample_rate, 1)
        # 板子在 detect 里报唤醒词，网关靠它去掉句首的唤醒词（我们不发 detect，免得后端再回一句问候）
        self.handler.device_wake_word = self.wake_word
        self.note("连上后端")
        return True

    def _closed(self):
        # 后端主动断开（空闲约 2 分钟），或者我们关掉；下次唤醒再连，和板子一样
        self.note("后端连接断开")
        self.state = "idle"
        self.mic.clear()

    async def close(self):
        self.watch.cancel()
        self.player.close()
        if self.handler and self.connected():
            await self.handler.close(self.socket)

    # 唤醒、听

    async def interrupt(self):
        """唤醒时后端还在说（比如晚到的回答）：打断，和板子在说话时被唤醒一样。

        没发出去的不发了；已经发到音箱的也让它停掉（stop_play 结束 aplay，下次放再起）：
        2026-11-02 录音，只清这边的话被打断的回答在音箱上还接着放了约 2 秒。
        """
        speaking = self.state == "speaking"
        playing = self.player.busy()
        if speaking and self.connected():
            self.socket.put(json.dumps({"type": "abort", "session_id": self.handler.session_id}))
            self.note("打断后端说话")
        self.player.clear()
        if speaking or playing:
            self.player.play_end = 0.0
            try:
                await self.link.stop_play()
                self.note("音箱停止播放")
            except Exception as e:
                logger.bind(tag=TAG).warning(f"让音箱停止播放失败：{type(e).__name__} {e}")

    async def start_listening(self, expect_playback=True):
        """唤醒以后：连后端、发 listen start。expect_playback：刚让音箱回了"在"，
        要等录音里出现它、放完、回声过去（ECHO_TAIL）才开始发麦克风"""
        if not await self.connect():
            return
        if self.call_agent:
            from core import gateway

            gateway.use_agent(self.handler, self.call_agent)
            self.call_agent = None
        self.socket.put(json.dumps({"type": "listen", "state": "start", "mode": "auto",
                                    "session_id": self.handler.session_id}))
        self.mic.clear()
        self.state = "listening"
        self.listen_since = self.clock()
        self.listen_mark = self.heard
        self.waiting_playback = expect_playback
        self.mic_open = False
        self.note("开始听")

    def on_mic(self, pcm, playing=False):
        """pcm：麦克风（单声道）；playing：这段录音里音箱在出声（protocol.playback_active）"""
        self.heard += len(pcm) / (2 * MIC_RATE)
        if playing:
            self.last_playback = self.heard
            self.waiting_playback = False
        if self.state != "listening" or not self.connected():
            return
        if self.mic_open:
            self.mic += pcm
            self._send_frames()
            return
        if self.waiting_playback:
            if self.heard - self.listen_mark < PLAYBACK_WAIT:
                return
            self.waiting_playback = False
        if self.heard - self.last_playback < ECHO_TAIL:
            return
        self.mic_open = True  # 开了就一直发到这次听完：中途不再看音箱有没有出声
        self.note("开始把麦克风发给后端")
        self.mic += pcm
        self._send_frames()

    def _send_frames(self):
        while len(self.mic) >= FRAME_BYTES:
            frame, self.mic = bytes(self.mic[:FRAME_BYTES]), self.mic[FRAME_BYTES:]
            self.socket.put(self.encoder.encode(frame, FRAME_BYTES // 2))

    # 后端发来的

    async def _from_server(self, message):
        if isinstance(message, (bytes, bytearray)):
            if self.decoder is None:
                return
            pcm = self.decoder.decode(bytes(message), self.handler.sample_rate * 120 // 1000)
            self.player.add(pcm)
            return
        try:
            data = json.loads(message)
        except ValueError:
            return
        kind, state = data.get("type"), data.get("state")
        if kind == "hello":
            self.hello.set()
        elif kind == "stt":
            self.note(f"后端认出：{data.get('text')}")
            if self.state == "listening":
                self.state = "thinking"
                self.think_since = self.clock()
        elif kind == "tts" and state == "start":
            self.state = "speaking"
            self.tts_done = False
            self.mic.clear()
        elif kind == "tts" and state == "sentence_start":
            self.note(f"后端说：{data.get('text')}")
            self.player.mark(str(data.get("text") or "")[:20])
        elif kind == "tts" and state == "stop":
            self.tts_done = True

    async def _watch(self):
        """说完回 idle、听太久没结果回 idle"""
        while True:
            await asyncio.sleep(0.1)
            now = self.clock()
            if self.state == "speaking" and self.tts_done and not self.player.busy():
                self.state = "idle"
                if self.handler is not None and getattr(self.handler, "gateway_listen_again", False):
                    # 只叫了名字（"我在。"）：接着听问题，不待机
                    self.handler.gateway_listen_again = False
                    self.note("只叫了名字，接着听")
                    asyncio.create_task(self.start_listening(expect_playback=False))
                else:
                    self.note("说完，待机")
            elif self.state == "listening" and now - self.listen_since > LISTEN_TIMEOUT:
                self.state = "idle"
                self.mic.clear()
                self.note(f"{LISTEN_TIMEOUT} 秒没听到一句话，待机")
            elif self.state == "thinking" and now - self.think_since > THINK_TIMEOUT:
                self.state = "idle"
                self.note(f"认出一句话后 {THINK_TIMEOUT} 秒还没开始说，待机")
