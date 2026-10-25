import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from core import gateway


def make_conn(config=None):
    return SimpleNamespace(config=config or {}, logger=mock.MagicMock())


class GatewayDispatchTest(unittest.IsolatedAsyncioTestCase):
    def patch_handlers(self, music=False, bot=False):
        music_mock = mock.AsyncMock(return_value=music)
        bot_mock = mock.AsyncMock(return_value=bot)
        for target, new in (("core.gateway.skills.music.command.handle_local_command", music_mock),
                            ("core.handle.grokBotHandle.handle_grok_bot", bot_mock)):
            patcher = mock.patch(target, new)
            patcher.start()
            self.addCleanup(patcher.stop)
        return music_mock, bot_mock

    async def test_without_config_music_runs_before_the_bot(self):
        music, bot = self.patch_handlers(music=True, bot=True)
        self.assertTrue(await gateway.dispatch(make_conn(), "暂停"))
        music.assert_awaited_once()
        bot.assert_not_awaited()

    async def test_sentence_music_skips_goes_to_the_bot(self):
        music, bot = self.patch_handlers(music=False, bot=True)
        conn = make_conn()
        self.assertTrue(await gateway.dispatch(conn, "帮我查天气"))
        bot.assert_awaited_once_with(conn, "帮我查天气")

    async def test_nobody_takes_it_falls_back_to_upstream_chat(self):
        self.patch_handlers()
        self.assertFalse(await gateway.dispatch(make_conn(), "你好宗主"))

    async def test_empty_skill_list_goes_straight_to_the_bot(self):
        music, bot = self.patch_handlers(music=True, bot=True)
        self.assertTrue(await gateway.dispatch(make_conn({"gateway": {"skills": []}}), "暂停"))
        music.assert_not_awaited()
        bot.assert_awaited_once()

    async def test_empty_agent_leaves_the_rest_to_upstream_chat(self):
        music, bot = self.patch_handlers(bot=True)
        self.assertFalse(await gateway.dispatch(make_conn({"gateway": {"agent": ""}}), "帮我查天气"))
        bot.assert_not_awaited()

    async def test_unknown_names_are_skipped_with_a_warning(self):
        music, bot = self.patch_handlers(bot=True)
        conn = make_conn({"gateway": {"skills": ["nope", "local_music"], "agent": "missing"}})
        self.assertFalse(await gateway.dispatch(conn, "帮我查天气"))
        music.assert_awaited_once()
        bot.assert_not_awaited()
        self.assertEqual(conn.logger.bind.return_value.warning.call_count, 2)

    async def test_registered_skill_and_agent_are_used(self):
        self.patch_handlers()

        class Clock(gateway.Skill):
            name = "test_clock"

            async def handle(self, conn, text):
                return text == "现在几点"

        agent = mock.AsyncMock(return_value=True)
        gateway.register_skill(Clock())
        gateway.register_agent("test_agent", agent)
        self.addCleanup(gateway.SKILLS.pop, "test_clock")
        self.addCleanup(gateway.AGENTS.pop, "test_agent")
        conn = make_conn({"gateway": {"skills": ["test_clock"], "agent": "test_agent"}})
        self.assertTrue(await gateway.dispatch(conn, "现在几点"))
        agent.assert_not_awaited()
        self.assertTrue(await gateway.dispatch(conn, "讲个笑话"))
        agent.assert_awaited_once_with(conn, "讲个笑话")


class SkillCollectionTest(unittest.IsolatedAsyncioTestCase):
    """Hotwords, fixed replies and listen hooks come from the skills that are switched on."""

    MUSIC_ON = {"local_music": {"enabled": True, "hotwords": [" 告五人 ", "", "晴天"]}}

    def test_music_hotwords_follow_the_switch(self):
        from core.utils import asr_text

        base = len(asr_text.DEFAULT_HOTWORDS)
        words = asr_text.hotwords_of(self.MUSIC_ON)
        self.assertEqual(len(words), base + 61 + 1)  # extra "晴天" is not repeated, blanks dropped
        self.assertIn("周杰伦", words)
        self.assertIn("告五人", words)
        self.assertEqual(len(asr_text.hotwords_of({})), base)
        self.assertEqual(len(asr_text.hotwords_of(self.MUSIC_ON | {"gateway": {"skills": []}})), base)

    async def test_warm_collects_the_fixed_replies_once_per_board(self):
        warm_phrases = mock.AsyncMock()
        with mock.patch("core.handle.grokBotPhrases.warm", warm_phrases), \
                mock.patch("core.gateway.skills.music.command.warm") as start_music:
            conn = make_conn(self.MUSIC_ON)
            gateway.warm(conn)
            await asyncio.sleep(0)
        texts = warm_phrases.await_args.args[1]
        self.assertEqual(len(texts), 14)
        self.assertEqual(texts[0], "好的。")
        start_music.assert_called_once_with(conn)

    async def test_nothing_is_warmed_when_music_is_off(self):
        with mock.patch("core.handle.grokBotPhrases.warm", mock.AsyncMock()) as warm_phrases, \
                mock.patch("core.gateway.skills.music.command.warm") as start_music:
            gateway.warm(make_conn({}))
            await asyncio.sleep(0)
        warm_phrases.assert_not_awaited()
        start_music.assert_not_called()

    def test_listen_lowers_the_music(self):
        with mock.patch("core.gateway.skills.music.command.duck") as duck:
            conn = make_conn(self.MUSIC_ON)
            gateway.on_listen(conn)
            gateway.on_listen(make_conn({}))
        duck.assert_called_once_with(conn)


if __name__ == "__main__":
    unittest.main()
