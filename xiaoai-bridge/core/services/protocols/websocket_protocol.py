import asyncio
import inspect
import json

import websockets

from core.ref import get_xiaozhi
from core.services.protocols.protocol import Protocol
from core.services.protocols.typing import DeviceState
from core.utils.config import ConfigManager
from core.utils.logger import logger


class WebsocketProtocol(Protocol):
    def __init__(self):
        super().__init__()
        # 获取配置管理器实例
        self.config = ConfigManager.instance()
        self.websocket = None
        self.server_sample_rate = 24000
        self.server_frame_duration = 60
        self.server_frame_size = int(
            self.server_sample_rate * (self.server_frame_duration / 1000)
        )
        self.connected = False
        self.hello_received = None  # 初始化时先设为 None
        self._handler_task = None
        self.WEBSOCKET_URL = self.config.get_config("NETWORK.WEBSOCKET_URL")
        self.WEBSOCKET_ACCESS_TOKEN = self.config.get_config(
            "NETWORK.WEBSOCKET_ACCESS_TOKEN"
        )
        self.CLIENT_ID = self.config.get_client_id()
        self.DEVICE_ID = self.config.get_device_id()

    async def _close_websocket(self):
        if self.websocket:
            try:
                await self.websocket.close()
                self.websocket = None
                self.connected = False
            except Exception:
                pass

    async def _invoke_callback(self, callback, *args):
        """Run sync or async callbacks transparently."""
        if not callback:
            return None

        result = callback(*args)
        if inspect.isawaitable(result):
            return await result
        return result

    async def connect(self) -> bool:
        """连接到WebSocket服务器"""
        try:
            await self._close_websocket()
            self.WEBSOCKET_URL = self.config.get_config("NETWORK.WEBSOCKET_URL")
            self.WEBSOCKET_ACCESS_TOKEN = self.config.get_config(
                "NETWORK.WEBSOCKET_ACCESS_TOKEN"
            )
            self.CLIENT_ID = self.config.get_client_id()
            self.DEVICE_ID = self.config.get_device_id()
            if not self.WEBSOCKET_ACCESS_TOKEN:
                # 没配固定 token 就每次连接前向 OTA 要一个（服务端没开 auth 时拿到的是空串，照常连）
                try:
                    self.WEBSOCKET_ACCESS_TOKEN = await asyncio.to_thread(
                        self.config.fetch_websocket_token
                    )
                except Exception as e:
                    logger.warning(f"[WebSocket] 从 OTA 获取 token 失败: {e}")

            # 在连接时创建 Event，确保在正确的事件循环中
            self.hello_received = asyncio.Event()

            # 配置连接
            headers = {
                "Authorization": f"Bearer {self.WEBSOCKET_ACCESS_TOKEN}",
                "Protocol-Version": "1",
                "Device-Id": self.DEVICE_ID,  # 获取设备MAC地址
                "Client-Id": self.CLIENT_ID,
            }

            # 建立WebSocket连接
            self.websocket = await websockets.connect(
                uri=self.WEBSOCKET_URL, additional_headers=headers
            )

            # Cancel stale handler task from previous connection
            if self._handler_task and not self._handler_task.done():
                self._handler_task.cancel()

            # 启动消息处理循环
            self._handler_task = asyncio.create_task(self._message_handler())

            # 发送客户端hello消息
            hello_message = {
                "type": "hello",
                "version": 1,
                "transport": "websocket",
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 16000,
                    "channels": 1,
                    "frame_duration": 60,
                },
            }
            await self.send_text(json.dumps(hello_message))

            # 等待服务器hello响应
            try:
                await asyncio.wait_for(self.hello_received.wait(), timeout=10.0)
                self.connected = True
                logger.info(f"[xiaozhi-esp32-server] 连接 {self.WEBSOCKET_URL} 成功")
                return True
            except asyncio.TimeoutError:
                if self.on_network_error:
                    self.on_network_error("等待响应超时")
                return False
        except Exception as e:
            if self.on_network_error:
                self.on_network_error(f"无法连接服务: {str(e)}")
            return False

    async def _message_handler(self):
        """处理接收到的WebSocket消息"""
        websocket = self.websocket
        try:
            async for message in websocket:
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                        session_id = data.get("session_id")
                        if session_id and session_id != self.session_id:
                            self.session_id = session_id
                            logger.info(
                                f"[xiaozhi-esp32-server] Updated session_id: {session_id}"
                            )
                        msg_type = data.get("type")
                        if msg_type == "hello":
                            await self._handle_server_hello(data)
                        else:
                            if self.on_incoming_json:
                                self.on_incoming_json(data)
                    except json.JSONDecodeError:
                        pass
                elif self.on_incoming_audio:
                    self.on_incoming_audio(message)
        except Exception as exc:
            logger.error(
                f"[xiaozhi-esp32-server] Message handler stopped: {type(exc).__name__}: {exc}"
            )
            self.connected = False
            if self.on_audio_channel_closed:
                await self._invoke_callback(self.on_audio_channel_closed)
            return

        # 服务端正常关闭（宗主后端会断开空闲连接）时 async for 直接结束、不抛异常；
        # 不标记断开的话 is_connected() 一直为 True，下次唤醒就不会重连
        if websocket is self.websocket:
            logger.info("[xiaozhi-esp32-server] 服务端关闭了连接，下次唤醒时重连")
            self.connected = False
            if self.on_audio_channel_closed:
                await self._invoke_callback(self.on_audio_channel_closed)

    async def send_audio(self, frames: list[bytes]):
        """发送音频数据"""
        if not self.is_audio_channel_opened():  # 使用已有的 is_connected 方法
            return

        try:
            for frame in frames:
                await self.websocket.send(frame)
        except Exception as exc:
            logger.error(
                f"[xiaozhi-esp32-server] Failed to send audio: {type(exc).__name__}: {exc}"
            )

    async def send_text(self, message: str):
        """发送文本消息"""
        if self.websocket:
            try:
                await self.websocket.send(message)
            except Exception as e:
                raise e

    def is_audio_channel_opened(self) -> bool:
        """检查音频通道是否打开"""
        return self.websocket is not None and self.connected

    _is_heartbeat_running = False

    async def open_audio_channel(self):
        if not self._is_heartbeat_running:
            self._is_heartbeat_running = True
            asyncio.create_task(self.heartbeat())
        await self.connect()

    async def _handle_server_hello(self, data: dict):
        """处理服务器的 hello 消息

        解析服务器返回的 hello 消息，设置相关参数并通知音频通道已打开

        Args:
            data: 服务器返回的 hello 消息数据
        """
        try:
            # 验证传输方式
            transport = data.get("transport")
            if not transport or transport != "websocket":
                return

            # TODO 使用默认的 24k 采样率
            # xiaozhi-esp32-server 返回的参数是 16k 采样率，但实际用的是 24k 采样率

            # 获取音频参数
            # audio_params = data.get("audio_params")
            # if audio_params:
            #     # 获取服务器的采样率
            #     sample_rate = audio_params.get("sample_rate")
            #     if sample_rate:
            #         self.server_sample_rate = sample_rate
            #     frame_duration = audio_params.get("frame_duration")
            #     if frame_duration:
            #         self.server_frame_duration = frame_duration
            #     self.server_frame_size = int(
            #         self.server_sample_rate * (self.server_frame_duration / 1000)
            #     )

            # 设置 hello 接收事件
            self.hello_received.set()

            # 通知音频通道已打开
            if self.on_audio_channel_opened:
                await self._invoke_callback(self.on_audio_channel_opened)

        except Exception as e:
            if self.on_network_error:
                self.on_network_error(f"处理服务器响应失败: {str(e)}")

    _reconnect_attempts = 0

    async def close_audio_channel(self):
        """关闭音频通道"""
        if self.websocket:
            try:
                await self.websocket.close()
                self.websocket = None
                self.connected = False
                if self.on_audio_channel_closed:
                    await self._invoke_callback(self.on_audio_channel_closed)
            except Exception:
                pass

        self._reconnect_attempts += 1
        delay = min(5 * (2 ** (self._reconnect_attempts - 1)), 60)
        logger.info(
            f"[xiaozhi-esp32-server] {self.WEBSOCKET_URL} 通道被关闭, "
            f"{delay}s 后尝试重连 (第 {self._reconnect_attempts} 次)..."
        )
        await asyncio.sleep(delay)
        success = await self.connect()
        if success:
            self._reconnect_attempts = 0

    async def heartbeat(self):
        while True:
            if self.websocket and get_xiaozhi().device_state == DeviceState.IDLE:
                try:
                    await self.websocket.ping()
                except Exception:
                    logger.error(
                        "发送心跳失败，准备重连",
                        module="xiaozhi-esp32-server",
                    )
                    # 发送心跳失败，重新连接
                    await self.open_audio_channel()
            await asyncio.sleep(1)
