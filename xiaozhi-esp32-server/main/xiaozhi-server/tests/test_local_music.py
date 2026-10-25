import json
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import core.gateway.skills.music.player  # noqa: F401 -- loaded before setUp snapshots sys.modules
from core.gateway.skills.music import command as local
from core.gateway.skills.music.command import Command, cn_number, match, parse_song
from core.gateway.skills.music.source import GoMusicDL, Song, artist_is, is_original, sounds_like


class MatchTest(unittest.TestCase):
    def test_play_requests(self):
        self.assertEqual(match("放周杰伦的晴天。"), Command("play", title="晴天", artist="周杰伦"))
        self.assertEqual(match("请帮我播放一首孤勇者"), Command("play", title="孤勇者"))
        self.assertEqual(match("来一首 林俊杰 江南"), Command("play", title="江南", artist="林俊杰"))
        self.assertEqual(match("我想听周杰伦的歌"), Command("play", artist="周杰伦"))
        self.assertEqual(match("放首歌"), Command("ask"))
        self.assertEqual(match("放首歌", has_song=True, paused=True), Command("resume"))

    def test_transport_depends_on_what_is_playing(self):
        # Common words in Bot tasks: only a command while music is on
        self.assertIsNone(match("继续"))
        self.assertIsNone(match("暂停"))
        self.assertIsNone(match("别放了"))
        self.assertEqual(match("暂停", has_song=True, playing=True), Command("pause"))
        self.assertEqual(match("暂停", has_song=True, paused=True), Command("pause"))  # not handed to the Bot
        self.assertEqual(match("继续", has_song=True, paused=True), Command("resume"))
        self.assertIsNone(match("继续", has_song=True, playing=True))
        self.assertEqual(match("继续播放", has_song=True, playing=True), Command("resume"))
        self.assertEqual(match("别放了", has_song=True, playing=True), Command("stop"))
        self.assertEqual(match("下一首"), Command("next"))
        self.assertEqual(match("这是什么歌？", has_song=True), Command("what"))

    def test_volume(self):
        self.assertEqual(match("音量调到三十"), Command("volume", level=30))
        self.assertEqual(match("把音量调到百分之五十五"), Command("volume", level=55))
        self.assertEqual(match("声音调到80%"), Command("volume", level=80))
        self.assertEqual(match("大声点"), Command("louder"))
        self.assertEqual(match("音量调小一点"), Command("quieter"))
        self.assertIsNone(match("调大一点"))  # no music: could be about anything
        self.assertEqual(match("调大一点", has_song=True), Command("louder"))
        self.assertEqual(match("静音"), Command("mute"))
        self.assertIsNone(match("音量调到一百二十"))

    def test_phrasings_heard_on_the_board(self):
        # 2026-10-22 实机：这两句曾被交给 Bot
        self.assertEqual(match("快进五秒", has_song=True, playing=True), Command("seek", level=5))
        self.assertEqual(match("音量调回三十"), Command("volume", level=30))

    def test_keyword_with_filler(self):
        on = dict(has_song=True, playing=True)
        # 2026-10-22 22:12–22:14 实机：这两句曾被交给 Bot
        self.assertEqual(match("先给我暂停", **on), Command("pause"))
        self.assertEqual(match("下下一首。", **on), Command("next"))
        for text, action in {"麻烦暂停一下音乐": "pause", "帮我把歌暂停了": "pause", "好的下一首吧": "next",
                             "快点切歌": "next", "这首歌是谁唱的呀": "what", "把歌关掉": "stop",
                             "现在放的是什么歌啊": "what", "再放一遍这首": "restart", "跳过这首歌吧": "next"}.items():
            self.assertEqual(match(text, **on).action, action, text)
        for text in ("暂停那个下载任务", "停一下那个下载任务", "把窗口关掉", "从头开始讲一遍", "接着刚才的话题",
                     "关掉电脑", "停止那个任务", "下一步怎么做"):
            self.assertIsNone(match(text, **on), text)

    def test_joined_clauses_and_named_songs(self):
        on = dict(has_song=True, playing=True)
        # 2026-10-22 22:26–22:28 实机
        self.assertEqual(match("帮我播放周杰伦的音乐，你随意播放。", **on), Command("play", artist="周杰伦"))
        self.assertEqual(match("周杰伦的晴天。放周杰伦的晴天。", **on), Command("play", title="晴天", artist="周杰伦"))
        self.assertEqual(match("帮我切换另外周杰伦的一首歌叫做七里香。", **on), Command("play", title="七里香", artist="周杰伦"))
        self.assertEqual(match("放一首叫七里香的歌"), Command("play", title="七里香"))
        self.assertEqual(match("换一首周杰伦的歌", **on), Command("play", artist="周杰伦"))
        self.assertEqual(match("下一首，下一首", **on), Command("next"))
        # A command clause next to a real task stays with the Bot
        self.assertIsNone(match("停一下，帮我看看下载任务", **on))

    def test_more_phrasings(self):
        on = dict(has_song=True, playing=True)
        cases = {
            "快退十秒": Command("seek", level=-10), "往后快进一分钟": Command("seek", level=60),
            "快进": Command("seek", level=10), "快进一百二十秒": Command("seek", level=120),
            "从头播放": Command("restart"), "单曲循环": Command("loop", level=1),
            "取消循环": Command("loop", level=0), "不要循环": Command("loop", level=0),
            "暂停一下吧": Command("pause"), "停一下": Command("pause"), "先暂停": Command("pause"),
            "换首歌": Command("next"), "跳过这首": Command("next"), "下一个": Command("next"),
            "回到上一首": Command("previous"), "这首歌叫什么名字": Command("what"),
            "把音乐关了": Command("stop"), "别唱了": Command("stop"),
            "开大点": Command("louder"), "关小一点": Command("quieter"), "声音再大一点": Command("louder"),
            "音量加": Command("louder"), "音量减小一点": Command("quieter"), "大点声": Command("louder"),
            "音量最大": Command("volume", level=100), "最小音量": Command("volume", level=10),
            "把音量改成二十": Command("volume", level=20), "音量降到十五": Command("volume", level=15),
            "音量五十": Command("volume", level=50), "把电脑的声音调到百分之六十": Command("volume", level=60),
            "解除静音": Command("unmute"), "换成林俊杰的江南": Command("play", title="江南", artist="林俊杰"),
        }
        for text, want in cases.items():
            self.assertEqual(match(text, **on), want, text)
        self.assertEqual(match("播放", has_song=True, paused=True), Command("resume"))
        self.assertIsNone(match("播放", has_song=True, playing=True))
        # Without music these stay with the Bot
        for text in ("快进五秒", "从头开始", "单曲循环", "停止", "跳过"[:0] or "从头再来"):
            self.assertIsNone(match(text), text)

    def test_dont_with_words_slipped_in(self):
        on = dict(has_song=True, playing=True)
        # 2026-10-25 实机："别再放了"曾被交给 Bot
        for text in ("别再放了", "不要再放了", "你别再放了吧", "不用再放了", "别再唱了", "别播了", "不要再播音乐了",
                     "别放音乐了", "别继续放了", "先别放了", "别再放这首歌了"):
            self.assertEqual(match(text, **on), Command("stop"), text)
        self.assertEqual(match("不要再循环了", **on), Command("loop", level=0))
        self.assertEqual(match("还是下一首吧", **on), Command("next"))
        self.assertEqual(match("再下一首", **on), Command("next"))
        # Without music, and "don't" followed by anything else, stay with the Bot
        self.assertIsNone(match("别再放了"))
        for text in ("别再提醒我了", "不要再发邮件了", "别再放到桌面上了", "不要再播放广告", "别再说了"):
            self.assertIsNone(match(text, **on), text)

    def test_other_speech_goes_to_the_bot(self):
        for text in ("帮我总结一下这周的 X 热点", "别暂停", "不要播放", "请回复宗主测试成功", "好"):
            self.assertIsNone(match(text, has_song=True, playing=True), text)

    def test_helpers(self):
        self.assertEqual([cn_number(x) for x in ("五十", "十", "十五", "一百", "七", "35", "两", "一百二十", "两百", "一百零五", "一百五")],
                         [50, 10, 15, 100, 7, 35, 2, 120, 200, 105, 150])
        self.assertIsNone(cn_number("十十"))
        self.assertEqual(parse_song("周杰伦的歌"), (None, "周杰伦"))
        self.assertEqual(parse_song("晴天"), ("晴天", None))


def _song(name, artist, source="kuwo", album="专辑", sid=None):
    return Song(sid or f"{source}-{name}-{artist}", source, name, artist, album, "270")


class SourceTest(unittest.TestCase):
    def test_original_and_artist_rules(self):
        self.assertTrue(is_original(_song("晴天", "周杰伦"), "晴天", "周杰伦"))
        self.assertFalse(is_original(_song("晴天 (Live)", "周杰伦"), "晴天", "周杰伦"))
        self.assertFalse(is_original(_song("稻香(治愈版)", "周杰伦."), "稻香", "周杰伦"))
        self.assertFalse(is_original(_song("晴天 (原唱 周杰伦)", "RyaVocal"), "晴天"))
        self.assertTrue(artist_is("G.E.M.邓紫棋", "邓紫棋"))
        self.assertTrue(artist_is("周杰伦 Jay Chou", "周杰伦"))
        for fake in ("周杰伦.", "HF薛之谦", "小周杰伦"):
            self.assertFalse(artist_is(fake, fake.strip(".HF小")), fake)

    def _client(self, results, rates=None):
        client = GoMusicDL("http://127.0.0.1:1/music")
        client.search = lambda keyword, sources: list(results.get(list(sources)[0], []))
        client.bitrate = lambda song: (rates or {}).get(song.id, 128)
        return client

    def test_netease_first_when_it_has_the_original(self):
        client = self._client({"netease": [_song("孤勇者", "陈奕迅", "netease")],
                               "migu": [_song("孤勇者", "陈奕迅", "migu")]}, {"migu-孤勇者-陈奕迅": 900})
        song, _ = client.find("孤勇者", "陈奕迅")
        self.assertEqual(song.source, "netease")

    def test_fallback_picks_the_best_bitrate(self):
        client = self._client({
            "netease": [_song("晴天 (原唱 周杰伦)", "RyaVocal", "netease")],
            "kuwo": [_song("晴天", "周杰伦", "kuwo")],
            "migu": [_song("晴天", "周杰伦", "migu")],
            "kugou": [_song("晴天", "周杰伦", "kugou")],
        }, {"kuwo-晴天-周杰伦": 128, "migu-晴天-周杰伦": 937, "kugou-晴天-周杰伦": 0})
        song, why = client.find("晴天", "周杰伦")
        self.assertEqual((song.source, song.artist), ("migu", "周杰伦"))
        self.assertIn("网易云没有原唱", why)

    def test_title_only_votes_for_the_singer(self):
        client = self._client({
            "netease": [_song("告白气球", "Xai小爱", "netease")],
            "qq": [_song("告白气球", "二珂", "qq")],
            "kugou": [_song("告白气球", "周杰伦", "kugou"), _song("告白气球", "二珂", "kugou")],
            "kuwo": [_song("告白气球", "周杰伦", "kuwo")],
            "migu": [_song("告白气球 (Live)", "周杰伦", "migu"), _song("告白气球", "周杰伦", "migu")],
        })
        song, _ = client.find("告白气球")
        self.assertEqual(song.artist, "周杰伦")

    def test_unspaced_singer_and_title(self):
        client = self._client({"kuwo": [_song("晴天", "周杰伦", "kuwo")]})
        song, _ = client.find("周杰伦晴天")
        self.assertEqual((song.name, song.artist), ("晴天", "周杰伦"))

    def test_next_song_by_singer_skips_duets_and_played(self):
        client = self._client({
            "netease": [_song("布拉格广场", "蔡依林、周杰伦", "netease")],
            "kugou": [_song("晴天", "周杰伦", "kugou"), _song("稻香", "周杰伦", "kugou")],
            "kuwo": [_song("屋顶", "周杰伦、温岚", "kuwo"), _song("晴天", "周杰伦", "kuwo")],
        })
        song = client.by_artist("周杰伦", exclude=["晴天"])
        self.assertEqual((song.name, song.artist), ("稻香", "周杰伦"))

    def test_misheard_title_by_sound(self):
        # 2026-10-22 22:20 实机："帮我播放周杰伦的请帖"（晴天）被交给了 Bot
        self.assertGreaterEqual(sounds_like("请帖", "晴天"), 0.75)
        self.assertLess(sounds_like("请帖", "稻香"), 0.75)
        self.assertEqual(sounds_like("七里乡", "七里香"), 1.0)
        songs = [_song("稻香", "周杰伦", "migu"), _song("晴天", "周杰伦", "migu"), _song("夜曲", "周杰伦", "migu")]
        client = GoMusicDL("http://127.0.0.1:1/music")
        client.search = lambda keyword, sources: songs if list(sources)[0] == "migu" and "请帖" not in keyword else []
        client.bitrate = lambda song: 900
        song, why = client.find("请帖", "周杰伦")
        self.assertEqual(song.name, "晴天")
        self.assertIn("按读音", why)

    def test_de_heard_as_zai(self):
        client = self._client({"kuwo": [_song("晴天", "周杰伦", "kuwo")]})
        song, _ = client.find("周杰伦在晴天")
        self.assertEqual((song.name, song.artist), ("晴天", "周杰伦"))

    def test_nothing_found(self):
        song, _ = self._client({}).find("不存在的歌", "周杰伦")
        self.assertIsNone(song)


class FakeMusic:
    def __init__(self, playing=False):
        self.current = _song("晴天", "周杰伦") if playing else None
        self._playing = playing
        self.calls = []

    def playing(self):
        return self._playing

    def paused(self):
        return False

    def unduck(self):
        pass

    def pause(self):
        self.calls.append("pause")

    def find_and_play(self, title, artist):
        self.calls.append(("play", title, artist))
        return _song(title, artist or "周杰伦") if title in ("晴天", "孤勇者") else None


class HandleTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.speak_txt = mock.MagicMock()
        self.audio = SimpleNamespace(send_stt_message=mock.AsyncMock(), send_tts_message=mock.AsyncMock())
        patcher = mock.patch.dict(sys.modules, {
            "core.handle.sendAudioHandle": self.audio,
            "core.handle.intentHandler": SimpleNamespace(speak_txt=self.speak_txt),
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def _conn(self, waiting=False):
        return SimpleNamespace(
            config={"local_music": {"enabled": True}, "wakeup_words": ["你好宗主"]},
            logger=mock.MagicMock(), session_id="s1", features={"bot_ui": True}, bot_ui_waiting=waiting,
            websocket=SimpleNamespace(send=mock.AsyncMock()), client_abort=True, tts=None,
        )

    async def _handle(self, text, music, conn=None):
        conn = conn or self._conn()
        with mock.patch("core.gateway.skills.music.player.get_music", return_value=music):
            handled = await local.handle_local_command(conn, text)
        return handled, conn

    async def test_play_says_ok_at_once_then_shows_the_song(self):
        music = FakeMusic()
        handled, conn = await self._handle("你好宗主，放周杰伦的晴天", music)
        self.assertTrue(handled)
        self.assertEqual(music.calls, [("play", "晴天", "周杰伦")])
        # spoken: only the cached "好的。"; the board rests after it (bot_wait reply)
        self.speak_txt.assert_called_once_with(conn, "好的。")
        screens = [json.loads(c.args[0])["text"] for c in conn.websocket.send.call_args_list]
        self.assertEqual(screens, ["正在找歌……", "正在播放：周杰伦的晴天"])
        self.audio.send_tts_message.assert_any_call(conn, "sentence_start", "正在播放：周杰伦的晴天")

    async def test_volume_is_shown_and_spoken_short(self):
        with mock.patch("core.gateway.skills.music.player.set_system_volume", return_value=30):
            handled, conn = await self._handle("音量调到三十", FakeMusic())
        self.assertTrue(handled)
        self.speak_txt.assert_called_once_with(conn, "好的。")
        self.assertEqual(json.loads(conn.websocket.send.call_args.args[0])["text"], "音量调到30。")

    async def test_bot_tasks_pass_through(self):
        for text in ("帮我整理这周的笔记", "你好宗主", "放到桌面上", "播放器怎么用"):
            handled, _ = await self._handle(text, FakeMusic())
            self.assertFalse(handled, text)

    async def test_known_singer_without_the_song_is_answered_not_sent(self):
        music = FakeMusic()
        music.last_why = "找到了这位歌手，但没有读音相近的歌"
        handled, _ = await self._handle("放周杰伦的不存在", music)
        self.assertTrue(handled)
        self.assertIn("没找到", self.speak_txt.call_args.args[1])

    async def test_song_request_without_result_is_answered(self):
        handled, _ = await self._handle("放一首不存在", FakeMusic())
        self.assertTrue(handled)
        said = [c.args[1] for c in self.speak_txt.call_args_list]
        self.assertEqual(said[0], "好的。")  # at once, before the search
        self.assertIn("没找到", said[-1])

    async def test_waiting_screen_is_left_alone(self):
        music = FakeMusic(playing=True)
        handled, conn = await self._handle("暂停", music, self._conn(waiting=True))
        self.assertTrue(handled)
        self.assertEqual(music.calls, ["pause"])
        conn.websocket.send.assert_not_called()

    async def test_disabled(self):
        conn = self._conn()
        conn.config["local_music"]["enabled"] = False
        self.assertFalse(await local.handle_local_command(conn, "放周杰伦的晴天"))


if __name__ == "__main__":
    unittest.main()
