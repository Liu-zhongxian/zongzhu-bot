import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core import gateway
from core.gateway import agent_store, waiting
from core.gateway.call_names import match_call_name
from core.gateway.agent import HANDING_OVER, WAITING_FOR_REPLY, Agent, Reply, hand_over, say_reply
from core.gateway.agent_session import Activity, AgentSession, Done, Error, ErrorKind, TextDelta


def make_conn(config=None):
    return SimpleNamespace(config=config or {}, logger=mock.MagicMock())


class GatewayDispatchTest(unittest.IsolatedAsyncioTestCase):
    def patch_handlers(self, music=False, bot=False):
        music_mock = mock.AsyncMock(return_value=music)
        bot_mock = mock.AsyncMock(return_value=bot)

        async def hand_over(conn, agent, text):
            return await bot_mock(conn, text)
        for target, new in (("core.gateway.skills.music.command.handle_local_command", music_mock),
                            ("core.gateway.hand_over", hand_over)):
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

        async def hand_over(conn, module, text):
            return await agent(conn, module.name, text)
        gateway.register_skill(Clock())
        gateway.register_agent(FakeAgent())
        self.addCleanup(gateway.SKILLS.pop, "test_clock")
        self.addCleanup(gateway.AGENTS.pop, "test_agent")
        conn = make_conn({"gateway": {"skills": ["test_clock"], "agent": "test_agent"}})
        with mock.patch("core.gateway.hand_over", hand_over):
            self.assertTrue(await gateway.dispatch(conn, "现在几点"))
            agent.assert_not_awaited()
            self.assertTrue(await gateway.dispatch(conn, "讲个笑话"))
        agent.assert_awaited_once_with(conn, "test_agent", "讲个笑话")


class FakeSession(AgentSession):
    """Plays back a fixed list of events for every sentence."""

    def __init__(self, events):
        self.events, self.sent = events, []

    @property
    def session_id(self):
        return None

    async def start(self):
        pass

    async def send(self, text):
        self.sent.append(text)
        for event in self.events:
            yield event

    async def interrupt(self):
        pass

    async def close(self):
        pass


class FakeAgent(Agent):
    name = "test_agent"
    title = "测试 AI"
    ack = "好的，交给测试 AI。"
    accepted = "测试 AI 收到了。"
    events = ()

    def session(self, conn):
        return FakeSession(list(self.events))


class HandOverTest(unittest.IsolatedAsyncioTestCase):
    """The gateway side of any AI module, driven by a fake one."""

    def setUp(self):
        self.speak_txt = mock.MagicMock()
        self.audio = SimpleNamespace(send_stt_message=mock.AsyncMock(), send_tts_message=mock.AsyncMock())
        patcher = mock.patch.dict(sys.modules, {
            "core.handle.sendAudioHandle": self.audio,
            "core.handle.intentHandler": SimpleNamespace(speak_txt=self.speak_txt),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cached = mock.AsyncMock(return_value=True)  # phrases.speak: the ack is cached
        patcher = mock.patch("core.handle.grokBotPhrases.speak", self.cached)
        patcher.start()
        self.addCleanup(patcher.stop)

    def conn(self):
        return SimpleNamespace(config={"wakeup_words": ["你好宗主"]}, logger=mock.MagicMock(), session_id="s1",
                               features={"bot_ui": True}, websocket=SimpleNamespace(send=mock.AsyncMock()),
                               client_abort=False, reset_audio_states=mock.MagicMock())

    async def run_with(self, events, text="你好宗主，帮我查天气"):
        agent = FakeAgent()
        agent.events = events
        conn = self.conn()
        self.assertTrue(await hand_over(conn, agent, text))
        return conn

    def screens(self, conn):
        return [json.loads(c.args[0]) for c in conn.websocket.send.await_args_list]

    async def test_waiting_for_reply_says_the_ack_and_holds_input(self):
        conn = await self.run_with([Activity(WAITING_FOR_REPLY), Done()])
        self.assertEqual(conn.gateway_sessions["test_agent"].sent, ["帮我查天气"])  # wake word taken off
        self.cached.assert_awaited_once_with(conn, "好的，交给测试 AI。")
        self.assertTrue(conn.bot_ui_waiting)
        conn.reset_audio_states.assert_called_once()
        self.speak_txt.assert_not_called()

    async def test_answer_text_is_said_after_the_ack(self):
        conn = await self.run_with([Activity(HANDING_OVER), TextDelta("今天"), TextDelta("晴。"), Done()])
        self.assertFalse(getattr(conn, "bot_ui_waiting", False))
        self.audio.send_tts_message.assert_awaited_with(conn, "start")
        self.speak_txt.assert_called_once_with(conn, "今天晴。")
        self.assertEqual(self.screens(conn), [])

    async def test_error_before_handing_over_is_not_sent(self):
        conn = await self.run_with([Error(ErrorKind.UNKNOWN, voice="刚才已尝试提交同一条指令。")])
        self.cached.assert_not_awaited()
        self.speak_txt.assert_called_once_with(conn, "刚才已尝试提交同一条指令。")
        self.assertEqual(conn.gateway_not_sent, "刚才已尝试提交同一条指令。")

    async def test_refused_after_the_ack_is_shown_and_ends_the_wait(self):
        conn = await self.run_with([Activity(WAITING_FOR_REPLY), Error(ErrorKind.AUTH, voice="被拒绝了。")])
        self.assertEqual([(m["type"], m["state"], m["text"]) for m in self.screens(conn)],
                         [("bot_wait", "reply", "被拒绝了。")])
        self.assertFalse(conn.bot_ui_waiting)
        self.speak_txt.assert_called_once_with(conn, "被拒绝了。")

    async def test_unknown_after_the_ack_keeps_waiting(self):
        conn = await self.run_with([Activity(WAITING_FOR_REPLY), Error(ErrorKind.UNKNOWN, voice="不确定。")])
        self.assertEqual(self.screens(conn), [])
        self.assertTrue(conn.bot_ui_waiting)
        self.speak_txt.assert_called_once_with(conn, "不确定。")

    async def test_uncached_ack_says_the_outcome_instead(self):
        self.cached.return_value = False
        await self.run_with([Activity(WAITING_FOR_REPLY), Done()])
        self.speak_txt.assert_called_once_with(mock.ANY, "测试 AI 收到了。")

    async def test_wake_word_alone_is_left_to_the_greeting(self):
        agent = FakeAgent()
        self.assertFalse(await hand_over(self.conn(), agent, "你好宗主"))

    async def test_late_reply_is_shown_and_spoken(self):
        conn = self.conn()
        conn.bot_ui_waiting = True
        await say_reply(conn, TextDelta("查好了。"), "req-1")
        sent = self.screens(conn)
        self.assertEqual([(m["type"], m.get("state")) for m in sent],
                         [("bot_wait", "reply"), ("tts", "start"), ("tts", "sentence_start")])
        self.assertFalse(conn.bot_ui_waiting)
        self.speak_txt.assert_called_once_with(conn, "查好了。")


class LaterAgent(FakeAgent):
    """A fake AI whose answers come back later, held in memory."""
    answers_later = True
    earlier = "稍早的测试回复："

    def __init__(self):
        self.since, self.ready, self.done = 0, [], []

    def waiting_since(self, conn):
        return self.since

    def next_reply(self, conn):
        return self.ready[0] if self.ready else None

    def delivered(self, conn, reply):
        self.ready.remove(reply)
        self.done.append(reply.request_id)

    def slow_hint(self, conn):
        return (20, "测试 AI 有点慢。")


class WaitingTest(unittest.IsolatedAsyncioTestCase):
    """Waiting is the gateway's: any AI with answers_later gets the same screen and delivery."""

    def setUp(self):
        self.speak_txt = mock.MagicMock()
        self.audio = SimpleNamespace(send_stt_message=mock.AsyncMock(), send_tts_message=mock.AsyncMock())
        patcher = mock.patch.dict(sys.modules, {
            "core.handle.sendAudioHandle": self.audio,
            "core.handle.intentHandler": SimpleNamespace(speak_txt=self.speak_txt),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        self.agent = LaterAgent()
        self.conn = SimpleNamespace(
            config={}, logger=mock.MagicMock(), session_id="s1", features={"bot_ui": True},
            websocket=SimpleNamespace(send=mock.AsyncMock()), client_abort=False, client_is_speaking=False,
            client_have_voice=False, just_woken_up=False, stop_event=asyncio.Event(), tts=object(),
            reset_audio_states=mock.MagicMock())

    def sent(self):
        return [json.loads(c.args[0]) for c in self.conn.websocket.send.await_args_list]

    async def test_screen_waits_hints_and_says_the_answer(self):
        self.agent.since = time.time() - 25
        await waiting.update_screen(self.conn, self.agent)
        await waiting.update_screen(self.conn, self.agent)  # each only once
        self.assertEqual([(m["type"], m["state"]) for m in self.sent()],
                         [("bot_wait", "waiting"), ("tts", "sentence_start")])
        self.assertEqual(self.sent()[0]["elapsed"], 25)
        self.assertEqual(self.sent()[1]["text"], "测试 AI 有点慢。")
        self.assertTrue(self.conn.bot_ui_waiting)
        self.agent.ready.append(Reply("r1", "答案。", created=self.agent.since))
        self.assertTrue(await waiting.deliver(self.conn, self.agent))
        self.assertEqual(self.agent.done, ["r1"])
        self.assertFalse(self.conn.bot_ui_waiting)
        self.speak_txt.assert_called_once_with(self.conn, "答案。")

    async def test_wake_resumes_input_before_an_old_answer_is_said(self):
        self.agent.since = time.time()
        await waiting.update_screen(self.conn, self.agent)
        waiting.resume_input(self.conn)
        self.assertFalse(self.conn.bot_ui_waiting)
        self.agent.ready.append(Reply("r1", "答案。"))
        self.assertIsNone(await waiting.deliver(self.conn, self.agent))
        self.conn.bot_reply_since = time.time()
        self.conn.bot_input_until = 0
        self.agent.ready[0].created = time.time() - 60
        await waiting.deliver(self.conn, self.agent)
        self.speak_txt.assert_called_once_with(self.conn, "稍早的测试回复：答案。")

    async def test_timeout_when_the_module_stops_waiting(self):
        self.agent.since = time.time()
        await waiting.update_screen(self.conn, self.agent)
        self.agent.since = 0
        await waiting.update_screen(self.conn, self.agent)
        self.assertEqual(self.sent()[-1]["state"], "timeout")
        self.assertFalse(self.conn.bot_ui_waiting)

    def test_progress_lines_follow_30_60_120(self):
        self.assertIsNone(waiting.progress_text(29, 0))
        self.assertEqual(waiting.progress_text(30, 0), "还在处理，请稍等。")
        self.assertIsNone(waiting.progress_text(89, 1))
        self.assertEqual(waiting.progress_text(90, 1), "已经等了1分30秒，还在处理。")
        self.assertIsNone(waiting.progress_text(209, 2))
        self.assertEqual(waiting.progress_text(210, 2), "已经等了3分30秒，还在处理。")
        self.assertEqual(waiting.progress_text(330, 3), "已经等了5分30秒，还在处理。")

    async def test_progress_is_off_unless_switched_on(self):
        self.agent.since = time.time() - 40
        self.conn.bot_ui_waiting = True
        await waiting.speak_progress(self.conn, self.agent)
        self.speak_txt.assert_not_called()
        self.conn.config = {"gateway": {"progress_prompts": True}}
        await waiting.speak_progress(self.conn, self.agent)
        await waiting.speak_progress(self.conn, self.agent)  # the next one is due at 90 s
        self.speak_txt.assert_called_once_with(self.conn, "还在处理，请稍等。")

    async def test_hello_starts_the_watch_and_listen_resumes(self):
        gateway.register_agent(self.agent)
        self.addCleanup(gateway.AGENTS.pop, "test_agent")
        self.conn.config = {"gateway": {"skills": [], "agent": "test_agent"}}
        with mock.patch("core.gateway.waiting.watch", mock.AsyncMock()) as watch, \
                mock.patch("core.handle.grokBotPhrases.warm", mock.AsyncMock()):
            gateway.warm(self.conn)
            await asyncio.sleep(0)
        watch.assert_awaited_once_with(self.conn, self.agent)
        self.conn.bot_ui_waiting = True
        gateway.on_listen(self.conn)
        self.assertFalse(self.conn.bot_ui_waiting)


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


class CallNameMatchTest(unittest.TestCase):
    """Cases from xiaozhi-hub-server tests/agent/test_call_names.py, with our names."""

    NAMES = {"grok_bot": ["孙悟空", "悟空", "Grok Bot", "Grok"]}

    def test_only_the_name(self):
        for text in ["Hi, 孙悟空.", "Hi, 孙悟空. Hi, 孙悟空.", "High grok.", "嗨 孙悟空", "hey，悟空！",
                     "He grok.", "Heい grok。", "Hei 孙悟空", "H, 孙悟空.", "嗨 Grok Bot"]:
            self.assertEqual(match_call_name(text, self.NAMES), ("grok_bot", ""), text)

    def test_name_with_a_task(self):
        for text, rest in [("嗨孙悟空帮我查天气。", "帮我查天气。"), ("嗨悟空,今天天气怎么样？", "今天天气怎么样？"),
                           ("higrok,今天天气怎么样？", "今天天气怎么样？"), ("Hi Grok, 用 Python 写个脚本", "用 Python 写个脚本"),
                           ("嘿，孙悟空，嘿，孙悟空，整理新闻", "整理新闻")]:
            self.assertEqual(match_call_name(text, self.NAMES), ("grok_bot", rest), text)

    def test_not_a_call(self):
        for text in ["孙悟空是谁", "嗨你好。", "嗨,你怎么看？", "嗨 grokking 是什么", "今天嗨 孙悟空一下",
                     "Hello 孙悟空", "Help grok 怎么用", "Hey.", "H5 grok 页面", ""]:
            self.assertIsNone(match_call_name(text, self.NAMES), text)

    def test_name_written_as_a_string(self):
        self.assertEqual(match_call_name("嗨 悟空", {"a": "悟空"}), ("a", ""))
        self.assertIsNone(match_call_name("嗨 悟 一下", {"a": "悟空"}))


class OtherAgent(FakeAgent):
    name = "other_ai"
    title = "另一个 AI"
    call_names = ("小助手",)


class CallNameDispatchTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = mock.patch.object(agent_store, "PATH", Path(self.temp.name) / "agent_sessions.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.speak_txt = mock.MagicMock()
        self.audio = SimpleNamespace(send_stt_message=mock.AsyncMock(), send_tts_message=mock.AsyncMock())
        patcher = mock.patch.dict(sys.modules, {
            "core.handle.sendAudioHandle": self.audio,
            "core.handle.intentHandler": SimpleNamespace(speak_txt=self.speak_txt),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cached = mock.AsyncMock(return_value=True)
        patcher = mock.patch("core.handle.grokBotPhrases.speak", self.cached)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.handed = []

        async def hand_over(conn, agent, text):
            self.handed.append((agent.name, text))
            return True
        patcher = mock.patch("core.gateway.hand_over", hand_over)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.music = mock.AsyncMock(return_value=False)
        patcher = mock.patch("core.gateway.skills.music.command.handle_local_command", self.music)
        patcher.start()
        self.addCleanup(patcher.stop)
        gateway.register_agent(OtherAgent())
        self.addCleanup(gateway.AGENTS.pop, "other_ai")
        self.config = {"grok_bot": {"enabled": True}, "wakeup_words": ["你好宗主"]}

    def conn(self):
        return SimpleNamespace(config=self.config, logger=mock.MagicMock(), device_id="aa:bb:cc:dd:ee:01",
                               client_abort=False, device_wake_word="你好宗主")

    async def test_name_alone_answers_here_and_sends_nothing(self):
        conn = self.conn()
        self.assertTrue(await gateway.dispatch(conn, "嗨，孙悟空。"))
        self.audio.send_stt_message.assert_awaited_once_with(conn, "嗨，孙悟空。")
        self.cached.assert_awaited_once_with(conn, "我在。")
        self.assertEqual(self.handed, [])
        self.music.assert_not_awaited()

    async def test_name_with_a_task_goes_straight_to_that_ai(self):
        conn = self.conn()
        self.music.return_value = True  # music would take "暂停" if it were asked
        self.assertTrue(await gateway.dispatch(conn, "你好宗主，嗨孙悟空，暂停"))
        self.assertEqual(self.handed, [("grok_bot", "暂停")])
        self.music.assert_not_awaited()

    async def test_calling_another_ai_switches_and_is_remembered(self):
        conn = self.conn()
        await gateway.dispatch(conn, "嗨 小助手，讲个笑话")
        await gateway.dispatch(conn, "再讲一个")
        self.assertEqual(self.handed, [("other_ai", "讲个笑话"), ("other_ai", "再讲一个")])
        # a reconnect (new conn) or a restart keeps the choice
        self.assertEqual(gateway.agent_name(self.conn()), "other_ai")
        await gateway.dispatch(self.conn(), "嗨 悟空")
        self.assertEqual(gateway.agent_name(self.conn()), "grok_bot")

    async def test_a_remembered_ai_that_is_switched_off_falls_back(self):
        agent_store.put("aa:bb:cc:dd:ee:01", "missing_ai")
        self.assertEqual(gateway.agent_name(self.conn()), "grok_bot")

    async def test_page_shows_the_call_and_the_board_ai(self):
        conn = self.conn()
        await gateway.dispatch(conn, "嗨 小助手")
        record = gateway.status.snapshot(self.config)["recent"][0]
        self.assertEqual((record["layer"], record["target"]), ("call", "另一个 AI"))

    def test_call_names_are_hotwords(self):
        words = gateway.hotwords(self.config)
        self.assertIn("孙悟空", words)
        self.assertIn("Grok Bot", words)


if __name__ == "__main__":
    unittest.main()
