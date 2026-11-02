import open_xiaoai_server

from core.ref import (
    get_speech_frames,
    get_xiaozhi,
    set_audio_codec,
    set_speech_frames,
)
from core.services.audio.stream import MyAudio
from core.services.protocols.typing import AudioConfig


class AudioCodec:
    """音频编解码器类，处理音频的录制和播放"""

    def __init__(self):
        """初始化音频编解码器"""
        self.audio = None
        self.input_stream = None
        self.output_stream = None
        self.opus_encoder = None
        self.opus_decoder = None
        self._is_closing = False

        self._initialize_audio()
        set_audio_codec(self)

    def _get_server_audio_params(self):
        """Get server audio parameters from XiaoZhi protocol, with defaults."""
        xiaozhi = get_xiaozhi()
        if xiaozhi and xiaozhi.protocol:
            return xiaozhi.protocol.server_sample_rate, xiaozhi.protocol.server_frame_size
        # Default values matching WebSocketProtocol defaults
        default_sample_rate = 24000
        default_frame_duration = 60
        return default_sample_rate, int(default_sample_rate * (default_frame_duration / 1000))

    def _initialize_audio(self):
        """初始化音频设备和编解码器"""
        self.audio = MyAudio.create()
        server_sample_rate, server_frame_size = self._get_server_audio_params()

        # 初始化音频输入流
        self.input_stream = self.audio.open(
            format=AudioConfig.FORMAT,
            channels=AudioConfig.CHANNELS,
            rate=AudioConfig.SAMPLE_RATE,
            input=True,
            frames_per_buffer=AudioConfig.FRAME_SIZE,
            input_device_index=MyAudio.get_input_device_index(self.audio),
        )

        # 初始化音频输出流
        self.output_stream = self.audio.open(
            output=True,
            format=AudioConfig.FORMAT,
            channels=AudioConfig.CHANNELS,
            rate=server_sample_rate,
            frames_per_buffer=server_frame_size,
            output_device_index=MyAudio.get_output_device_index(self.audio),
        )

        # 初始化Opus编码器
        self.opus_encoder = open_xiaoai_server.OpusEncoder(
            sample_rate=AudioConfig.SAMPLE_RATE,
            channels=AudioConfig.CHANNELS,
        )

        # 初始化Opus解码器
        self.opus_decoder = open_xiaoai_server.OpusDecoder(
            sample_rate=server_sample_rate,
            channels=AudioConfig.CHANNELS,
        )
        self.temp_frames = bytes([])

    def read_audio(self):
        """读取音频输入数据并编码"""
        try:
            speech_frames = get_speech_frames()

            # 加入语音片段
            if speech_frames:
                self.temp_frames = speech_frames
                set_speech_frames([])

            # 读取音频输入数据
            data = self.input_stream.read(
                num_frames=None,
                exception_on_overflow=False,
            )
            if not data:
                return None

            self.temp_frames += data
            if len(self.temp_frames) < AudioConfig.FRAME_SIZE * 2:
                return None

            opus_frames, remain_frames = self.encode_audio(self.temp_frames)
            self.temp_frames = remain_frames
            return opus_frames
        except Exception:
            return None

    def write_audio(self, opus_data):
        """解码并播放"""
        try:
            pcm_data = self.decode_audio(opus_data)  # 解码
            self.output_stream.write(pcm_data)  # 播放
        except Exception:
            pass

    def decode_audio(self, opus_data):
        """解码音频数据"""
        _, server_frame_size = self._get_server_audio_params()
        return self.opus_decoder.decode(
            opus_data,
            frame_size=server_frame_size,
            decode_fec=False,
        )

    def encode_audio(self, buffer: bytes, frame_size=AudioConfig.FRAME_SIZE):
        """编码音频数据"""
        opus_frames = []
        remain_frames = bytes([])
        try:
            for i in range(0, len(buffer), frame_size * 2):
                chunk = buffer[i : i + frame_size * 2]
                if len(chunk) < frame_size * 2:
                    remain_frames = chunk
                    break
                opus_frame = self.opus_encoder.encode(chunk, frame_size)
                opus_frames.append(opus_frame)
            return opus_frames, remain_frames
        except Exception:
            return None, remain_frames

    def start_streams(self):
        """启动音频流"""
        if not self.input_stream.is_active():
            self.input_stream.start_stream()
        if not self.output_stream.is_active():
            self.output_stream.start_stream()

    def stop_streams(self):
        """停止音频流"""
        if self.input_stream.is_active():
            self.input_stream.stop_stream()
        if self.output_stream.is_active():
            self.output_stream.stop_stream()

    def close(self):
        """关闭音频编解码器，确保资源正确释放"""
        if self._is_closing:  # 防止重复关闭
            return
        self._is_closing = True

        try:
            # 关闭输入流
            if self.input_stream:
                try:
                    if self.input_stream.is_active():
                        self.input_stream.stop_stream()
                    self.input_stream.close()
                except Exception:
                    pass
                self.input_stream = None

            # 关闭输出流
            if self.output_stream:
                try:
                    if self.output_stream.is_active():
                        self.output_stream.stop_stream()
                    self.output_stream.close()
                except Exception:
                    pass
                self.output_stream = None

            # 关闭 PyAudio 实例
            if self.audio:
                try:
                    self.audio.terminate()
                except Exception:
                    pass
                self.audio = None

            # 清理编解码器
            self.opus_encoder = None
            self.opus_decoder = None
        except Exception:
            pass
        finally:
            self._is_closing = False
