import asyncio
import importlib
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

# The logger loads data/.config.yaml on import; the published copy has none.
with mock.patch.dict(sys.modules, {"config.logger": SimpleNamespace(setup_logging=lambda: mock.MagicMock())}):
    send = importlib.import_module("core.handle.sendAudioHandle")
    AudioRateController = importlib.import_module("core.utils.audioRateController").AudioRateController


def make_conn(config=None):
    return SimpleNamespace(config=config or {}, client_abort=False, conn_from_mqtt_gateway=False,
                           websocket=SimpleNamespace(send=mock.AsyncMock()), last_activity_time=0)


class PrebufferTest(unittest.IsolatedAsyncioTestCase):
    async def push(self, conn, count, flow, controller):
        await send._send_audio_with_rate_control(conn, [b"x"] * count, controller, flow, 0)

    async def test_turn_start_sends_fifteen_packets_directly(self):
        conn, flow, controller = make_conn(), {"packet_count": 0, "sequence": 0}, AudioRateController(60)
        await self.push(conn, 40, flow, controller)
        self.assertEqual(conn.websocket.send.await_count, 15)
        self.assertEqual(len(controller.queue), 25)

    async def test_next_sentence_only_tops_up_to_fifteen(self):
        conn, controller = make_conn(), AudioRateController(60)
        # The device still holds about 10 packets of the previous sentence
        flow = {"packet_count": 30, "sequence": 30, "play_end": time.monotonic() + 0.6}
        await self.push(conn, 20, flow, controller)
        self.assertEqual(conn.websocket.send.await_count, 5)
        self.assertEqual(len(controller.queue), 15)

    async def test_full_device_buffer_sends_nothing_directly(self):
        conn, controller = make_conn(), AudioRateController(60)
        flow = {"packet_count": 30, "sequence": 30, "play_end": time.monotonic() + 1.5}
        await self.push(conn, 10, flow, controller)
        self.assertEqual(conn.websocket.send.await_count, 0)
        self.assertEqual(len(controller.queue), 10)

    async def test_packets_queue_behind_a_non_empty_queue(self):
        conn, controller = make_conn(), AudioRateController(60)
        controller.add_audio(b"pending")
        flow = {"packet_count": 30, "sequence": 30}
        await self.push(conn, 10, flow, controller)
        self.assertEqual(conn.websocket.send.await_count, 0)
        self.assertEqual(len(controller.queue), 11)

    async def test_count_is_configurable_and_bad_values_fall_back(self):
        for config, expected in (({"tts_audio_prebuffer_count": 5}, 5), ({"tts_audio_prebuffer_count": "x"}, 15),
                                 ({"tts_audio_prebuffer_count": 0}, 1)):
            conn, flow, controller = make_conn(config), {"packet_count": 0, "sequence": 0}, AudioRateController(60)
            await self.push(conn, 20, flow, controller)
            self.assertEqual(conn.websocket.send.await_count, expected, config)

    async def test_play_end_advances_one_frame_per_packet(self):
        conn, flow, controller = make_conn(), {"packet_count": 0, "sequence": 0}, AudioRateController(60)
        before = time.monotonic()
        await self.push(conn, 15, flow, controller)
        self.assertAlmostEqual(flow["play_end"] - before, 0.9, delta=0.05)

    async def test_wait_for_completion_covers_the_device_buffer(self):
        conn = make_conn()
        conn.audio_rate_controller = AudioRateController(60)
        conn.audio_flow_control = {"play_end": time.monotonic() + 0.3}
        conn.logger = mock.MagicMock()
        with mock.patch.object(send.asyncio, "sleep", new=mock.AsyncMock()) as sleep:
            await send._wait_for_audio_completion(conn)
        self.assertAlmostEqual(sleep.await_args.args[0], 0.42, delta=0.05)


if __name__ == "__main__":
    unittest.main()
