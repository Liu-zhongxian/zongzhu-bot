"""接宗主后端时改的几处（zongzhu 分支）：OTA 要 token、空闲断开后唤醒重连、重复唤醒、小爱放歌不被暂停。"""
import asyncio
import unittest
from unittest import mock

import config
from core.services.protocols.typing import DeviceState
from core.services.protocols.websocket_protocol import WebsocketProtocol
from core.utils.config import ConfigManager
from core.wakeup_session import WakeupSessionManager
from core.xiaozhi import XiaoZhi


class FetchTokenTest(unittest.TestCase):
    def test_posts_device_and_client_id_and_returns_token(self):
        manager = ConfigManager.instance()
        response = mock.Mock(status_code=200)
        response.json.return_value = {"websocket": {"url": "ws://x", "token": "signed"}}
        with mock.patch.object(manager, "get_config", return_value="http://ota/xiaozhi/ota/"), \
                mock.patch("core.utils.config.requests.post", return_value=response) as post:
            self.assertEqual(manager.fetch_websocket_token(), "signed")
        headers = post.call_args.kwargs["headers"]
        # 服务端的签名绑定这两个头，之后连 WebSocket 时要用同样的值
        self.assertEqual(headers["Device-Id"], manager.get_device_id())
        self.assertEqual(headers["Client-Id"], manager.get_client_id())

    def test_no_ota_url_or_no_auth_gives_empty_token(self):
        manager = ConfigManager.instance()
        with mock.patch.object(manager, "get_config", return_value=None):
            self.assertEqual(manager.fetch_websocket_token(), "")
        response = mock.Mock(status_code=200)
        response.json.return_value = {"websocket": {"url": "ws://x"}}
        with mock.patch.object(manager, "get_config", return_value="http://ota/"), \
                mock.patch("core.utils.config.requests.post", return_value=response):
            self.assertEqual(manager.fetch_websocket_token(), "")


class _ClosedSocket:
    """服务端正常关闭：async for 直接结束，不抛异常（给了 closed 就等它再结束）"""

    def __init__(self, closed=None):
        self.closed = closed

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed:
            await self.closed.wait()
        raise StopAsyncIteration


class ServerCloseTest(unittest.IsolatedAsyncioTestCase):
    async def test_normal_close_marks_disconnected(self):
        protocol = WebsocketProtocol()
        protocol.websocket = _ClosedSocket()
        protocol.connected = True
        protocol.on_audio_channel_closed = mock.Mock()
        await protocol._message_handler()
        self.assertFalse(protocol.is_audio_channel_opened())
        protocol.on_audio_channel_closed.assert_called_once()

    async def test_close_of_a_replaced_socket_is_ignored(self):
        protocol = WebsocketProtocol()
        closed = asyncio.Event()
        protocol.websocket = _ClosedSocket(closed)
        protocol.connected = True
        protocol.on_audio_channel_closed = mock.Mock()
        handler = asyncio.ensure_future(protocol._message_handler())
        await asyncio.sleep(0)
        protocol.websocket = object()  # 已经重连上了新的，旧连接这时才结束
        closed.set()
        await handler
        self.assertTrue(protocol.connected)
        protocol.on_audio_channel_closed.assert_not_called()


class ReconnectOnWakeupTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.xiaozhi = object.__new__(XiaoZhi)
        self.xiaozhi.protocol = None
        self.xiaozhi._app = None
        self.xiaozhi.send_abort_speaking = mock.AsyncMock()

    async def test_reconnects_before_the_session(self):
        self.xiaozhi.connect = mock.AsyncMock(return_value=False)
        await self.xiaozhi.start_wakeup_session()
        self.xiaozhi.connect.assert_awaited_once()
        # 连不上就不开会话
        self.xiaozhi.send_abort_speaking.assert_not_awaited()


class WakeupTest(unittest.TestCase):
    def test_duplicate_wakeup_is_ignored_while_a_session_runs(self):
        manager = WakeupSessionManager()
        running = mock.Mock()
        running.done.return_value = False
        manager._xiaozhi_future = running
        with mock.patch("core.wakeup_session.get_xiaozhi") as get_xiaozhi:
            manager.on_wakeup()
        get_xiaozhi.assert_not_called()
        self.assertIs(manager._xiaozhi_future, running)

    def _interrupt(self, state):
        manager = WakeupSessionManager()
        manager._stop_device_playback = mock.Mock()
        xiaozhi = mock.Mock(device_state=state)
        with mock.patch("core.wakeup_session.get_xiaozhi", return_value=xiaozhi), \
                mock.patch.object(manager, "_get_loop", return_value=mock.Mock()), \
                mock.patch("core.wakeup_session.asyncio.run_coroutine_threadsafe") as run, \
                mock.patch("core.xiaoai.XiaoAI.stop_conversation"):
            manager.on_interrupt()
        return run

    def test_xiaoai_own_dialog_does_not_pause_its_music(self):
        # 小爱"播放音乐"后会再开一次麦，走到 on_interrupt；bridge 没在对话就不能 mphelper pause
        self.assertFalse(self._interrupt(DeviceState.IDLE).called)

    def test_interrupt_stops_playback_during_a_bridge_dialog(self):
        self.assertTrue(self._interrupt(DeviceState.SPEAKING).called)


class WakeWordTest(unittest.IsolatedAsyncioTestCase):
    async def test_zongzhu_says_zai_and_goes_to_xiaozhi(self):
        speaker = mock.Mock(play=mock.AsyncMock())
        self.assertEqual(await config.before_wakeup(speaker, "你好宗主", "kws", None), "xiaozhi")
        speaker.play.assert_awaited_once_with(text="在")
        self.assertIn("你好宗主", config.APP_CONFIG["wakeup"]["keywords"])


if __name__ == "__main__":
    unittest.main()
