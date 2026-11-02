"""音箱上 open-xiaoai Client 的连接协议（照 xiaoai-bridge/speaker/client/client-rust/src/services/connect/ 写）。

- WebSocket，Client 连上来时带 `Authorization: Bearer <token>`。
- 文本消息是 JSON，外面包一层类型：`{"Request": {id, command, payload}}`、
  `{"Response": {id, code, msg, data}}`、`{"Event": {id, event, data}}`。
- 二进制消息是 JSON 序列化的 Stream：`{id, tag, bytes: [0-255, ...], data}`，没有外层类型。
  麦克风 tag 是 "record"（16 kHz 16 位 PCM，声道数由 start_recording 定，多声道是交错的）；要放的声音 tag 是 "play"（格式由 start_play 定）。
- Client 能执行的指令：get_version、start_recording、stop_recording、start_play、stop_play、run_shell。
"""
import asyncio
import json
import uuid

# 录音：音箱的 noop 是 4 声道的录音设备（hw:0,3）。2026-11-02 分声道录实测：ch0–2 是 3 个麦克风，
# ch3 是音箱自己放的声音（硬件回环，不出声时正好是 0）。录成单声道会把 4 个混在一起，放声音时 ch3 盖住人声、
# 大量削顶，喊唤醒词认不出；所以按 4 声道录、只用 3 个麦克风的平均（mic_mono）。
RECORD_CHANNELS = 4
MIC_CHANNELS = 3
RECORD_CONFIG = {"pcm": "noop", "channels": RECORD_CHANNELS, "bits_per_sample": 16, "sample_rate": 16000,
                 "period_size": 1440 // 4, "buffer_size": 1440}
# 放音：24 kHz（宗主后端 TTS 出来就是 24 kHz），aplay 缓冲 200 毫秒；和 bridge 用的一样
PLAY_CONFIG = {"pcm": "noop", "channels": 1, "bits_per_sample": 16, "sample_rate": 24000,
               "period_size": 1200, "buffer_size": 4800}
CALL_TIMEOUT = 10


def mic_mono(pcm):
    """4 声道录音（交错）里 3 个麦克风的平均，16 kHz 单声道 16 位 PCM"""
    import numpy as np

    frame = 2 * RECORD_CHANNELS
    samples = np.frombuffer(pcm[:len(pcm) // frame * frame], dtype="<i2").reshape(-1, RECORD_CHANNELS)
    return samples[:, :MIC_CHANNELS].astype(np.int32).mean(axis=1).astype("<i2").tobytes()


def playback_active(pcm, threshold=1000):
    """这段录音里音箱是不是在出声（看 ch3：音箱实际放出的声音）。

    看起伏（最大减最小），不看数值大小：不出声时一般是 0，但 stop_play 停掉 aplay 以后
    ch3 会一直停在 -256（2026-11-02 录音，停了 7 秒一直是 -256），偶尔有 ±256 的跳动。
    """
    frame = 2 * RECORD_CHANNELS
    playback = memoryview(pcm[:len(pcm) // frame * frame]).cast("h")[RECORD_CHANNELS - 1::RECORD_CHANNELS]
    return bool(len(playback)) and max(playback) - min(playback) > threshold


def silence(ms, rate=PLAY_CONFIG["sample_rate"]):
    return b"\0\0" * (rate * ms // 1000)


class ClientError(Exception):
    """Client 回了错误（code 不是 0 也不是空）"""


class SpeakerLink:
    """一条音箱连接：发指令等回应、收麦克风、发要放的声音。ws 是 websockets 的连接（测试里可以换成假的）。"""

    def __init__(self, ws, on_record=None, on_event=None):
        self.ws = ws
        self.on_record = on_record  # (bytes) -> None，麦克风 PCM
        self.on_event = on_event    # (event, data) -> None
        self._pending: dict[str, asyncio.Future] = {}
        self._playing = False

    async def run(self):
        """收消息直到连接断开"""
        try:
            async for message in self.ws:
                if isinstance(message, (bytes, bytearray)):
                    self._on_stream(json.loads(message))
                else:
                    await self._on_text(json.loads(message))
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("音箱断开了"))
            self._pending.clear()

    async def _on_text(self, message):
        if "Response" in message:
            response = message["Response"]
            future = self._pending.pop(response.get("id"), None)
            if future and not future.done():
                future.set_result(response)
        elif "Event" in message:
            event = message["Event"]
            if self.on_event:
                self.on_event(event.get("event"), event.get("data"))
        elif "Request" in message:
            # Client 不会主动调我们；回个错误，免得它等到超时
            request = message["Request"]
            await self.ws.send(json.dumps({"Response": {
                "id": request.get("id"), "code": -1, "msg": "command not found"}}))

    def _on_stream(self, stream):
        if stream.get("tag") == "record" and self.on_record:
            self.on_record(bytes(stream.get("bytes") or ()))

    async def call(self, command, payload=None, timeout=CALL_TIMEOUT):
        """让 Client 执行一条指令，返回它的 data；出错抛 ClientError"""
        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self.ws.send(json.dumps({"Request": {"id": request_id, "command": command, "payload": payload}}))
            response = await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(request_id, None)
        if response.get("code") not in (None, 0):
            raise ClientError(f"{command}: {response.get('msg')}")
        return response.get("data")

    async def start_recording(self):
        await self.call("start_recording", RECORD_CONFIG)

    async def play(self, pcm: bytes):
        """放一段 24 kHz 单声道 16 位 PCM。第一次放之前先让音箱起 aplay。

        开头不用垫静音：2026-11-02 录音实测，aplay 刚起来、或空了几秒以后发的声音，第一声都在
        发出后约 0.09 秒完整放出来（xiaoai/debug.py 的测试音 A、B、E、G）。
        一次发的声音要短于约 1 秒：音箱 Client 往 aplay 写时只等 100 毫秒，写不进去的直接丢，
        一次发 2.6 秒只放出前 1.5 秒左右（测试音 D）；长的要分段、按播放速度发（测试音 F）。
        """
        if not self._playing:
            await self.call("start_play", PLAY_CONFIG)
            self._playing = True
        await self.send_play(pcm)

    async def send_play(self, pcm: bytes):
        """原样发一段要放的声音（不起 aplay、不垫静音）"""
        stream = {"id": str(uuid.uuid4()), "tag": "play", "bytes": list(pcm)}
        await self.ws.send(json.dumps(stream, separators=(",", ":")).encode())

    async def stop_play(self):
        if self._playing:
            self._playing = False
            await self.call("stop_play")
