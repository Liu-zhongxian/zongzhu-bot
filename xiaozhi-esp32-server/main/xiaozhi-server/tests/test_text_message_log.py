import json
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

# The handler registry loads the server config on import; the processor only needs its type.
with mock.patch.dict(sys.modules, {"core.handle.textMessageHandlerRegistry":
                                   SimpleNamespace(TextMessageHandlerRegistry=object)}):
    from core.handle.textMessageProcessor import LOG_PREVIEW_CHARS, TextMessageProcessor, preview


class MessageLogTest(unittest.IsolatedAsyncioTestCase):
    def test_short_message_is_logged_whole(self):
        self.assertEqual(preview('{"type":"listen"}'), '{"type":"listen"}')

    def test_long_message_is_cut_and_says_how_long(self):
        message = "x" * 5000
        text = preview(message)
        self.assertTrue(text.startswith("x" * LOG_PREVIEW_CHARS))
        self.assertLess(len(text), LOG_PREVIEW_CHARS + 40)
        self.assertIn("5000", text)

    async def test_mcp_tool_list_info_line_stays_short(self):
        # The board's MCP tools/list reply is the message that used to flood the terminal.
        message = json.dumps({"type": "mcp", "payload": {"result": {"tools": ["t" * 100] * 60}}})
        logger = mock.MagicMock()
        handler = SimpleNamespace(handle=mock.AsyncMock())
        conn = SimpleNamespace(logger=logger)
        processor = TextMessageProcessor(SimpleNamespace(get_handler=lambda kind: handler))
        await processor.process_message(conn, message)
        bound = logger.bind.return_value
        info = bound.info.call_args.args[0]
        self.assertLess(len(info), LOG_PREVIEW_CHARS + 60)
        self.assertIn(message, bound.debug.call_args.args[0])
        handler.handle.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
