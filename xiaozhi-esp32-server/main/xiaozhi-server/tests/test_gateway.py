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

    async def test_a_bare_filler_word_is_not_sent(self):
        # G19c 实测：唤醒后只说了"对"，被交给了 Bot
        music, bot = self.patch_handlers(bot=True)
        for text in ("嗯。", "对", "好的！"):
            self.assertTrue(await gateway.dispatch(make_conn(), text))
        music.assert_not_awaited()
        bot.assert_not_awaited()
        self.assertTrue(await gateway.dispatch(make_conn(), "对，就是南乐县"))  # 有内容的照常交
        bot.assert_awaited_once()

    async def test_a_confirmation_goes_to_the_ai_after_it_asked(self):
        music, bot = self.patch_handlers(bot=True)
        conn = make_conn()
        conn.gateway_last_said = (time.time(), "你说的是河南濮阳的南乐县吗？")
        self.assertTrue(await gateway.dispatch(conn, "对"))
        bot.assert_awaited_once()
        conn.gateway_last_said = (time.time() - gateway.CONFIRM_SECONDS - 1, "你说的是南乐县吗？")
        await gateway.dispatch(conn, "对")
        bot.assert_awaited_once()  # 问得太久以前了
        conn.gateway_last_said = (time.time(), "如果是别的地方，告诉我再查。")
        await gateway.dispatch(conn, "嗯")
        bot.assert_awaited_once()  # 语气词什么时候都不交

    async def test_connection_without_skills_goes_straight_to_the_bot(self):
        # 小米音箱那一路设 gateway_skills = []：音乐不管它说的话，板子照旧
        music, bot = self.patch_handlers(music=True, bot=True)
        speaker = make_conn()
        speaker.gateway_skills = []
        self.assertTrue(await gateway.dispatch(speaker, "暂停"))
        music.assert_not_awaited()
        bot.assert_awaited_once()
        self.assertTrue(await gateway.dispatch(make_conn(), "暂停"))
        music.assert_awaited_once()

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
        self.speak_txt.assert_called_once_with(self.conn, "测试 AI做完了：答案。")

    async def test_timeout_when_the_module_stops_waiting(self):
        self.agent.since = time.time()
        await waiting.update_screen(self.conn, self.agent)
        self.agent.since = 0
        await waiting.update_screen(self.conn, self.agent)
        self.assertEqual(self.sent()[-1]["state"], "timeout")
        self.assertFalse(self.conn.bot_ui_waiting)

    async def say(self, text, request_id="r0"):
        """Like a delivered answer whose sentences the TTS queue sent, as far as `sent`."""
        await waiting.say_reply(self.conn, TextDelta(text), request_id)
        self.conn.client_is_speaking = False  # 念完或被打断（abort 清掉说话状态）

    async def test_interrupted_answer_goes_on_after_the_new_question_then_the_new_answer(self):
        # 你定的规则（2026-11-02）：打断后先回新问题的"交给 Bot"，再接着说剩下的，新回复带上问题
        await self.say("南乐县现在晴，15度。明天阴，7到21度。后天有小雨。")
        waiting.note_sentence(self.conn, "南乐县现在晴，15度")
        waiting.note_sentence(self.conn, "明天阴，7到21度")
        waiting.on_abort(self.conn)  # 说第二句时喊了唤醒词
        self.speak_txt.reset_mock()
        self.assertIsNone(await waiting.deliver(self.conn, self.agent))  # 先等新问题
        self.conn.bot_input_until = 0  # 新问题交给 AI 了（hand_over）
        self.agent.ready.append(Reply("r2", "现在下午5点。", created=time.time(), question="现在几点了？"))
        self.assertEqual(await waiting.deliver(self.conn, self.agent), "resumed")
        self.speak_txt.assert_called_once_with(self.conn, "明天阴，7到21度。后天有小雨。")
        self.assertEqual(self.agent.done, [])
        self.conn.client_is_speaking = False
        self.assertTrue(await waiting.deliver(self.conn, self.agent))
        self.speak_txt.assert_called_with(self.conn, "你刚才问「现在几点了」：现在下午5点。")

    async def test_waking_again_lets_the_user_speak_before_the_rest(self):
        await self.say("第一句。第二句。")
        waiting.on_abort(self.conn)
        self.conn.bot_input_until = time.monotonic() - 1  # 等的 15 秒过去了
        waiting.resume_input(self.conn)                    # 又喊了唤醒词
        self.assertIsNone(await waiting.deliver(self.conn, self.agent))

    async def test_rest_is_said_when_nothing_new_is_asked(self):
        await self.say("第一句。第二句。")
        waiting.note_sentence(self.conn, "第一句")
        waiting.on_abort(self.conn)
        self.conn.bot_input_until = time.monotonic() - 1  # RESUME_SECONDS 过去了
        self.speak_txt.reset_mock()
        self.assertEqual(await waiting.deliver(self.conn, self.agent), "resumed")
        self.speak_txt.assert_called_once_with(self.conn, "第一句。第二句。")

    async def test_wake_long_after_the_answer_keeps_nothing(self):
        await self.say("说完了。")
        waiting.note_sentence(self.conn, "说完了")
        waiting.note_stop(self.conn)
        self.conn.gateway_reply_now["stopped_at"] -= waiting.INTERRUPT_GRACE_SECONDS + 1
        waiting.on_abort(self.conn)
        self.assertIsNone(getattr(self.conn, "gateway_resume", None))
        self.agent.ready.append(Reply("r2", "答案。", created=time.time(), question="问题"))
        await waiting.deliver(self.conn, self.agent)
        self.speak_txt.assert_called_with(self.conn, "答案。")  # 没打断：不加问题

    def test_remaining_text_starts_at_the_sentence_being_said(self):
        text = "甲。乙，丙。乙！"
        self.assertEqual(waiting.remaining_text(text, []), text)
        self.assertEqual(waiting.remaining_text(text, ["甲。", "乙"]), "乙，丙。乙！")
        self.assertEqual(waiting.remaining_text(text, ["甲", "乙", "丙", "乙"]), "乙！")
        self.assertEqual(waiting.remaining_text(text, ["对不上"]), text)

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

    async def test_connection_without_skills_warms_only_the_ai_phrases(self):
        with mock.patch("core.handle.grokBotPhrases.warm", mock.AsyncMock()) as warm_phrases, \
                mock.patch("core.gateway.skills.music.command.warm") as start_music, \
                mock.patch("core.gateway.skills.music.command.duck") as duck:
            speaker = make_conn(self.MUSIC_ON)
            speaker.gateway_skills = []
            gateway.warm(speaker)
            gateway.on_listen(speaker)
            await asyncio.sleep(0)
        start_music.assert_not_called()
        duck.assert_not_called()
        texts = warm_phrases.await_args.args[1] if warm_phrases.await_args else []
        self.assertNotIn("已暂停。", texts)

    def test_listen_lowers_the_music(self):
        with mock.patch("core.gateway.skills.music.command.duck") as duck:
            conn = make_conn(self.MUSIC_ON)
            gateway.on_listen(conn)
            gateway.on_listen(make_conn({}))
        duck.assert_called_once_with(conn)


class CallNameMatchTest(unittest.TestCase):
    """Cases from xiaozhi-hub-server tests/agent/test_call_names.py, with our Bot's name."""

    NAMES = {"grok_bot": ["硬件"], "other": ["Grok Bot", "Grok"]}

    def test_only_the_name(self):
        for text in ["Hi, 硬件.", "Hi, 硬件. Hi, 硬件.", "High 硬件.", "嗨 硬件", "hey，硬件！",
                     "He 硬件.", "Heい 硬件。", "Hei 硬件", "H, 硬件.", "嘿，硬件。"]:
            self.assertEqual(match_call_name(text, self.NAMES), ("grok_bot", ""), text)
        self.assertEqual(match_call_name("嗨 Grok Bot", self.NAMES), ("other", ""))

    def test_name_with_a_task(self):
        for text, rest in [("嗨硬件帮我查天气。", "帮我查天气。"), ("嗨，硬件，今天天气怎么样？", "今天天气怎么样？"),
                           ("hi硬件,今天天气怎么样？", "今天天气怎么样？"), ("Hi 硬件, 用 Python 写个脚本", "用 Python 写个脚本"),
                           ("嘿，硬件，嘿，硬件，整理新闻", "整理新闻")]:
            self.assertEqual(match_call_name(text, self.NAMES), ("grok_bot", rest), text)

    def test_not_a_call(self):
        for text in ["硬件怎么选", "嗨你好。", "嗨,你怎么看？", "嗨 grokking 是什么", "今天嗨 硬件一下",
                     "Hello 硬件", "Help grok 怎么用", "Hey.", "H5 硬件 页面", ""]:
            self.assertIsNone(match_call_name(text, self.NAMES), text)

    def test_name_written_as_a_string(self):
        self.assertEqual(match_call_name("嗨 硬件", {"a": "硬件"}), ("a", ""))
        self.assertIsNone(match_call_name("嗨 硬 一下", {"a": "硬件"}))


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
        self.config = {"grok_bot": {"enabled": True, "bot_name": "硬件"}, "wakeup_words": ["你好宗主"]}

    def conn(self):
        return SimpleNamespace(config=self.config, logger=mock.MagicMock(), device_id="aa:bb:cc:dd:ee:01",
                               client_abort=False, device_wake_word="你好宗主")

    async def test_name_alone_answers_here_and_sends_nothing(self):
        conn = self.conn()
        self.assertTrue(await gateway.dispatch(conn, "嗨，硬件。"))
        self.audio.send_stt_message.assert_awaited_once_with(conn, "嗨，硬件。")
        self.cached.assert_awaited_once_with(conn, "我在。")
        self.assertEqual(self.handed, [])
        self.music.assert_not_awaited()
        self.assertTrue(conn.gateway_listen_again)  # 音箱说完"我在。"接着听问题

    def test_call_names_are_wake_words_for_the_speaker(self):
        self.assertEqual(gateway.call_words(self.config)["硬件"], "grok_bot")

    async def test_name_with_a_task_goes_straight_to_that_ai(self):
        conn = self.conn()
        self.music.return_value = True  # music would take "暂停" if it were asked
        self.assertTrue(await gateway.dispatch(conn, "你好宗主，嗨硬件，暂停"))
        self.assertEqual(self.handed, [("grok_bot", "暂停")])
        self.music.assert_not_awaited()

    async def test_calling_another_ai_switches_and_is_remembered(self):
        conn = self.conn()
        await gateway.dispatch(conn, "嗨 小助手，讲个笑话")
        await gateway.dispatch(conn, "再讲一个")
        self.assertEqual(self.handed, [("other_ai", "讲个笑话"), ("other_ai", "再讲一个")])
        # a reconnect (new conn) or a restart keeps the choice
        self.assertEqual(gateway.agent_name(self.conn()), "other_ai")
        await gateway.dispatch(self.conn(), "嗨 硬件")
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
        self.assertIn("硬件", gateway.hotwords(self.config))

    def test_bot_name_is_the_call_name_and_the_label(self):
        bot = gateway.AGENTS["grok_bot"]
        self.assertEqual(gateway.agent_call_names(self.config)["grok_bot"], ("硬件",))
        self.assertEqual(bot.label(self.config), "Grok Bot · 硬件")
        # without a configured name: the module's own call names
        plain = {"grok_bot": {"enabled": True}}
        self.assertEqual(gateway.agent_call_names(plain)["grok_bot"], ("Grok Bot", "Grok"))
        self.assertEqual(bot.label(plain), "Grok Bot")


if __name__ == "__main__":
    unittest.main()


class PageSettingsTest(unittest.IsolatedAsyncioTestCase):
    """G8b 第 5 步：唤醒词、呼名在网关页面上改，存在 data/gateway_settings.json，马上生效。"""

    def setUp(self):
        from core.gateway import settings
        from core.gateway.xiaoai import control as speaker_control
        self.settings = settings
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = mock.patch.object(settings, "PATH", Path(directory.name) / "gateway_settings.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = mock.Mock(reload=mock.AsyncMock(return_value=(["宗主"], [])), skipped=[])
        patcher = mock.patch.object(speaker_control, "server", self.server)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = {"grok_bot": {"enabled": True, "bot_name": "硬件"},
                       "gateway": {"call_names": {"grok_bot": ["bot"]}}}

    def test_words_are_checked(self):
        self.assertEqual(self.settings.words("宗主， 你好宗主、宗主,Bot"), ["宗主", "你好宗主", "Bot"])
        for bad in ("", "宗主; rm -rf", "a" * 21, ",".join(str(i) for i in range(11))):
            with self.assertRaises(self.settings.SettingError):
                self.settings.words(bad)
        self.assertEqual(self.settings.words("", allow_empty=True), [])

    async def test_call_names_set_on_the_page_win_and_take_effect_at_once(self):
        from core.gateway import control
        self.assertEqual(gateway.agent_call_names(self.config)["grok_bot"], ["bot"])  # 配置里的
        result = await control.settings_action(self.config, "set_call_names", {"agent": "grok_bot", "names": "bot、but"})
        self.assertIn("bot、but", result["message"])
        self.assertEqual(gateway.agent_call_names(self.config)["grok_bot"], ["bot", "but"])
        self.server.reload.assert_awaited_once()  # 音箱的唤醒词跟着换
        view = control.settings_view(self.config)
        self.assertEqual(view["call_names"][0]["names"], ["bot", "but"])
        with self.assertRaises(control.ControlError):
            await control.settings_action(self.config, "set_call_names", {"agent": "nobody", "names": "x"})

    async def test_speaker_wake_words_set_on_the_page(self):
        from core.gateway import control
        from core.gateway.xiaoai import server
        self.assertEqual(server.wake_words(self.config), ["宗主"])  # 默认
        await control.settings_action(self.config, "set_speaker_wake_words", "宗主、你好宗主")
        self.assertEqual(server.wake_words(self.config), ["宗主", "你好宗主"])
        with self.assertRaises(control.ControlError):
            await control.settings_action(self.config, "set_speaker_wake_words", "")  # 至少留一个


class BoardWakeWordTest(unittest.IsolatedAsyncioTestCase):
    """G8b 第 5 步：网关页面上改板子的唤醒词（和 tools/wake_word.py 同一套）。"""

    def setUp(self):
        from core.gateway import status
        self.status = status
        status._boards["aa:bb:cc:dd:ee:01"] = {"type": "lichuang-dev", "version": "2.5.2.9"}
        self.addCleanup(status._boards.pop, "aa:bb:cc:dd:ee:01", None)
        self.conn = SimpleNamespace(device_id="aa:bb:cc:dd:ee:01", config={})

    async def test_finds_the_same_version_package_and_reboots_the_board(self):
        from core.gateway import control, wake_assets
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "assets.bin"
            source.write_bytes(b"ASSETS")
            with mock.patch.object(wake_assets, "package_assets", return_value=(source, None)) as find, \
                    mock.patch.object(wake_assets, "change_wake_word",
                                      mock.AsyncMock(return_value={"size": 4 * 1024 * 1024})) as change:
                result = await control.board_wake_word({}, self.conn, "你好小雨")
        self.assertEqual(find.call_args.args[1:], ("lichuang-dev", "2.5.2.9"))
        change.assert_awaited_once_with(self.conn, b"ASSETS", "你好小雨", "ni hao xiao yu", reboot=True)
        self.assertIn("你好小雨", result["message"])

    async def test_bad_word_or_wrong_version_is_refused_before_the_board_is_touched(self):
        from core.gateway import control, wake_assets
        # 自带一份 web/boards.json：后端不在仓库里跑时（Docker 镜像里）也能测
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        (Path(directory.name) / "web").mkdir()
        (Path(directory.name) / "web" / "boards.json").write_text(
            '[{"id": "szp", "package": "zongzhu-szp-2.5.2.9", "assets": "generated_assets.bin"}]')
        config = {"gateway": {"firmware_root": directory.name}}
        with mock.patch.object(wake_assets, "change_wake_word", mock.AsyncMock()) as change:
            for word in ("hello", "宗", "你好宗主你好宗主你好"):
                with self.assertRaises(control.ControlError):
                    await control.board_wake_word(config, self.conn, word)
            self.status._boards["aa:bb:cc:dd:ee:01"]["version"] = "2.5.2.1"
            with self.assertRaises(control.ControlError) as caught:
                await control.board_wake_word(config, self.conn, "你好小雨")
        self.assertIn("同一版", str(caught.exception))
        change.assert_not_awaited()
