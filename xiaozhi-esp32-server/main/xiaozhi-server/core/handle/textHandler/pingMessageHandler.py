import json
import time
from typing import Dict, Any

from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType

TAG = __name__


class PingMessageHandler(TextMessageHandler):
    """Ping消息处理器，用于保持WebSocket连接"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.PING

    async def handle(self, conn, msg_json: Dict[str, Any]) -> None:
        """
        处理PING消息，发送PONG响应
        消息格式：{"type": "ping"}
        Args:
            conn: WebSocket连接对象
            msg_json: PING消息的JSON数据
        """
        # 检查是否启用了WebSocket心跳功能
        enable_websocket_ping = conn.config.get("enable_websocket_ping", False)
        if not enable_websocket_ping:
            conn.logger.debug(f"WebSocket心跳功能未启用，忽略PING消息")
            return

        try:
            conn.logger.debug(f"收到PING消息，发送PONG响应")
            conn.last_activity_time = time.time() * 1000
            # 构造PONG响应消息
            pong_message = {
                "type": "pong",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            }

            # 发送PONG响应
            await conn.websocket.send(json.dumps(pong_message))

        except Exception as e:
            conn.logger.error(f"处理PING消息时发生错误: {e}")
