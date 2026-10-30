import asyncio
import unittest

from core.openclaw import OpenClawManager


class OpenClawResponseEventsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.saved_texts = OpenClawManager._response_texts
        self.saved_events = OpenClawManager._response_events
        self.run_id = "response-events-test"
        self.waiter = asyncio.get_running_loop().create_future()
        OpenClawManager._response_texts = {}
        OpenClawManager._response_events = {self.run_id: self.waiter}

    async def asyncTearDown(self):
        if not self.waiter.done():
            self.waiter.cancel()
        OpenClawManager._response_texts = self.saved_texts
        OpenClawManager._response_events = self.saved_events

    async def emit(self, stream, data):
        await OpenClawManager._handle_agent_event({
            "event": "agent",
            "payload": {"runId": self.run_id, "stream": stream, "data": data},
        })
        await asyncio.sleep(0)

    async def test_initial_snapshot_followed_by_delta_only_events(self):
        await self.emit("assistant", {"text": "这", "delta": "这"})
        await self.emit("assistant", {"delta": "是一段完整的回复，"})
        await self.emit("assistant", {"delta": "不会只留下第一个字。"})
        self.assertEqual("这是一段完整的回复，不会只留下第一个字。",
                         OpenClawManager._response_texts[self.run_id])
        self.assertFalse(self.waiter.done())
        await self.emit("lifecycle", {"phase": "finishing"})
        self.assertFalse(self.waiter.done())
        await self.emit("lifecycle", {"phase": "end"})
        self.assertTrue(self.waiter.done())

    async def test_delta_only_from_first_event(self):
        await self.emit("assistant", {"delta": "完整"})
        await self.emit("assistant", {"delta": "回复"})
        self.assertEqual("完整回复", OpenClawManager._response_texts[self.run_id])
        self.assertFalse(self.waiter.done())

    async def test_snapshot_and_delta_do_not_duplicate_text(self):
        await self.emit("assistant", {"text": "Hello", "delta": "Hello"})
        await self.emit("assistant", {"delta": " world"})
        await self.emit("assistant", {"text": "Hello world!", "delta": "!"})
        self.assertEqual("Hello world!", OpenClawManager._response_texts[self.run_id])

    async def test_legacy_cumulative_snapshots_are_preserved(self):
        await self.emit("assistant", {"text": "Hello"})
        await self.emit("assistant", {"text": "Hello world"})
        await self.emit("assistant", {"delta": ""})
        self.assertEqual("Hello world", OpenClawManager._response_texts[self.run_id])


if __name__ == "__main__":
    unittest.main()
