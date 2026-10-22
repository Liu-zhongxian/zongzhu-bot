"""Music and volume commands run on this Mac before anything reaches the Bot.

"放周杰伦的晴天", "暂停", "下一首", "音量调到三十" take about a second here,
against 16-22s through the Bot. Only these fixed forms are recognised, a song
name is only ever a search keyword, and anything else goes on to the Bot.
"继续", "停一下" and friends are common in Bot tasks too, so they count only
while a song is playing or paused.
"""
import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from typing import Optional

from core.handle import grokBotPhrases as phrases

PUNCT = re.compile(r"[\s，。！？、,.!?~～:：…]+")
POLITE = re.compile(r"^(?:请|麻烦你|麻烦|帮我|帮忙|给我|你|就|嗯|呃|那就|那|然后|再给我|再|先|赶紧|快点|马上|现在|可以|能不能|好的|好)+")
# Trailing particles: "暂停一下吧" is "暂停", "快进十秒好吗" is "快进十秒"
TAIL = re.compile(r"(?:吧|呀|啊|呢|哈|啦|呗|嘛|了|好吗|好不好|可以吗|行吗|谢谢|一下)+$")
NUM = r"\d{1,3}|[零一二两三四五六七八九十百]+"
PLAY = re.compile(r"^(?:我想听|我要听|想听|播放|放|来一首|来首|来点|听一首|听首|换成|换到|切换到|切换成|切换|切到|改放|播|"
                  r"换一首|换首|再来一首|再放一首)(?:一首|一下|首|点|个)?(?P<what>.+?)(?:吧|呗|好吗|可以吗)?$")
# "帮我切换另外周杰伦的一首歌叫做七里香", "放一首叫七里香的歌"
NAMED = re.compile(r"(?:叫做|名叫|名字叫|叫)(?P<title>[^的]{1,20}?)(?:的歌|这首歌|那首歌)?$")
NAMED_ARTIST = re.compile(r"(?P<artist>[^的]{2,12}?)的(?:另外一首|另一首|一首|那首|首)?歌")
MUSIC_VERB = re.compile(r"放|播|听|换|切|来一首|来首")
# Clauses split at sentence punctuation; spaces stay inside a clause ("放 邓紫棋 光年之外")
CLAUSE = re.compile(r"[，。！？、,.!?；;~～…]+")
# A second clause that only adds this much keeps the command: "…的音乐，你随意播放"
MUSICISH = re.compile(r"播放|放|歌|音乐|随意|随便|随机|听|一下|吧")
GENERIC = {"歌", "音乐", "首歌", "点歌", "点音乐", "一首歌", "歌曲", "放歌", "首"}
STOP = {"别放了", "不要放了", "停止播放", "停止音乐", "关掉音乐", "关闭音乐", "关音乐", "不听了", "音乐关掉",
        "把音乐关掉", "把音乐关了", "音乐关了", "关了音乐", "停止", "结束播放", "别唱了", "不要唱了", "关掉歌", "把歌关了"}
PAUSE = {"暂停", "暂停音乐", "暂停播放", "停", "停下", "停下来", "先停", "先暂停", "暂停歌曲", "暂停这首歌", "音乐暂停"}
RESUME = {"继续", "继续播放", "接着放", "接着播放", "恢复播放", "继续放", "继续听", "接着听", "接着唱", "继续唱",
          "继续放歌", "播放", "放", "开始播放"}
NEXT = {"下一首", "下一曲", "下一个", "下首", "切歌", "换一首", "换首", "换首歌", "换一首歌", "换一个", "跳过",
        "跳过这首", "跳过这首歌", "播放下一首", "放下一首", "切下一首", "下一首歌", "不想听这首", "换歌"}
PREVIOUS = {"上一首", "上一曲", "上一个", "上首", "播放上一首", "放上一首", "回到上一首", "上一首歌", "切回上一首"}
WHAT = {"这是什么歌", "现在放的是什么", "现在放的什么歌", "现在放的是什么歌", "这首歌叫什么", "这首歌叫什么名字",
        "这是谁唱的", "这首歌是谁唱的", "放的是什么歌", "这是啥歌", "这首叫什么", "这是谁的歌", "歌名是什么",
        "什么歌", "这是哪首歌", "正在放什么", "正在放什么歌", "现在在放什么"}
RESTART = {"从头播放", "从头开始", "从头放", "重新播放", "重头播放", "重头开始", "重放", "再放一遍", "重新放",
           "从头再来", "再听一遍"}
LOOP_ON = {"单曲循环", "循环播放", "循环这首", "循环这首歌", "重复播放", "一直放这首", "单曲重复"}
LOOP_OFF = {"取消循环", "取消单曲循环", "关闭循环", "不要循环", "别循环了", "不循环", "顺序播放"}
UNMUTE = {"取消静音", "打开声音", "解除静音", "恢复声音"}
MUTE = {"静音", "关掉声音", "把声音关了"}
VOL = r"(?:把)?(?:电脑的?)?(?:音量|声音)"
SET_VOLUME = re.compile(
    rf"^{VOL}(?:调到|调成|调回到|调回|调为|开到|开成|设为|设到|设成|设置为|设置成|设置到|改成|改为|改到|降到|降低到|"
    rf"调低到|调高到|升到|提高到|加到|减到|到|为)?(?:百分之)?(?P<n>{NUM})(?:%|的音量)?$")
VOLUME_EXTREME = re.compile(rf"^(?:{VOL}(?:调到|开到|调成|开)?(?P<a>最大|最小)|(?P<b>最大|最小)音量)$")
UP = r"(?:调|开|加|放|提|升)?(?:大|高)"
DOWN = r"(?:调|开|关|减|降|放)?(?:小|低)"
AMOUNT = r"(?:一点|一些|点|些)?(?:声)?"
LOUDER = re.compile(rf"^{VOL}?(?:再)?{UP}{AMOUNT}$|^(?:再)?大(?:一)?点声$|^大声(?:一)?点$|^{VOL}(?:加|加大|增大|大){AMOUNT}$")
QUIETER = re.compile(rf"^{VOL}?(?:再)?{DOWN}{AMOUNT}$|^(?:再)?小(?:一)?点声$|^小声(?:一)?点$|^{VOL}(?:减|减小|降|小){AMOUNT}$")
SEEK = re.compile(rf"^(?:往后|向后|往前|向前)?(?P<dir>快进|快退|倒退|后退|往回退|往回|退回|前进)(?P<n>{NUM})?(?P<unit>秒钟?|分钟|分)?$")
# Keyword commands: the keyword plus only filler characters around it ("先给我暂停",
# "帮我把歌暂停了", "好的下一首吧"). Anything else left over ("暂停那个下载任务") means
# it is not a music command. Longer keywords first.
FILLER = set("先给我帮请麻烦你就把那个这首歌曲音乐一下吧呀啊呢了嘛哈好的嗯呃然后再快点马上赶紧现在立刻可以能")
WHAT_FILLER = FILLER | set("是在正放现名字啥呀")
KEYWORDS = [
    ("不要放了", "stop"), ("别放了", "stop"), ("停止播放", "stop"), ("不听了", "stop"), ("别唱了", "stop"),
    ("关掉", "stop"), ("关了", "stop"), ("停止", "stop"),
    ("暂停", "pause"), ("停一下", "pause"), ("停下", "pause"), ("停", "pause"),
    ("恢复播放", "resume"), ("继续", "resume"), ("接着", "resume"),
    ("下一首", "next"), ("下一曲", "next"), ("下一个", "next"), ("下首", "next"), ("切歌", "next"),
    ("换一首", "next"), ("换首", "next"), ("换歌", "next"), ("跳过", "next"),
    ("上一首", "previous"), ("上一曲", "previous"), ("上一个", "previous"), ("上首", "previous"),
    ("重新播放", "restart"), ("再放一遍", "restart"), ("放一遍", "restart"), ("再来一遍", "restart"), ("再听一遍", "restart"), ("从头", "restart"), ("重头", "restart"), ("重放", "restart"),
    ("取消循环", "loop_off"), ("单曲循环", "loop_on"), ("循环", "loop_on"),
    ("谁唱的", "what"), ("什么歌", "what"), ("叫什么", "what"), ("谁的歌", "what"), ("哪首歌", "what"),
]
KEYWORDS.sort(key=lambda kv: -len(kv[0]))
STEP = 10
SEEK_DEFAULT = 10
# Fixed replies are synthesized when the board connects and replayed at once: EdgeTTS needs
# 1-3s per sentence, the slowest step of a command (2026-10-22 logs). Song names and levels
# vary, so those go to the screen and the voice says one of these.
OK = "好的。"
# In warm-up order, most used first: each takes 1-3s to synthesize, one after another
FIXED_REPLIES = (OK, "已暂停。", "继续播放。", "下一首。", "上一首。", "已停止播放。", "从头播放。",
                 "已静音。", "已取消静音。", "现在没有在放歌。", "单曲循环。", "已取消循环。", "前面没有歌了。",
                 "想听什么歌？可以说：放周杰伦的晴天。")
# Said at once for the slow ones, while the song is looked up
ACK = {"play": OK, "next": "下一首。", "previous": "上一首。"}
# Shown in full, spoken as "好的。"
QUIET = {"seek", "volume", "louder", "quieter"}

DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_number(text: str) -> Optional[int]:
    """0-999 in digits or Chinese ("三十五", "一百二十", "两百")."""
    if text.isdigit():
        return int(text)
    value, rest = 0, text
    if "百" in rest:
        hundreds, _, rest = rest.partition("百")
        n = DIGITS.get(hundreds, None) if hundreds else 1
        if n is None:
            return None
        value += n * 100
        if not rest.startswith("零") and len(rest) == 1 and rest in DIGITS:  # "一百五" = 150
            return value + DIGITS[rest] * 10
        rest = rest.lstrip("零")  # "一百零五" = 105
    if "十" in rest:
        tens, _, ones = rest.partition("十")
        n = DIGITS.get(tens, None) if tens else 1
        m = DIGITS.get(ones, None) if ones else 0
        if n is None or m is None:
            return None
        return value + n * 10 + m
    if rest:
        if len(rest) != 1 or rest not in DIGITS:
            return None
        value += DIGITS[rest]
    return value if text else None


def _keyword(t: str) -> Optional[str]:
    """The action of a keyword command, or None. ASR stutter ("下下一首") is folded first."""
    for text in dict.fromkeys((t, re.sub(r"(.)\1+", r"\1", t))):
        for word, action in KEYWORDS:
            if word in text:
                rest = text.replace(word, "", 1)
                allowed = WHAT_FILLER if action == "what" else FILLER
                if all(c in allowed for c in rest):
                    return action
    return None


@dataclass
class Command:
    action: str
    title: Optional[str] = None
    artist: Optional[str] = None
    level: Optional[int] = None


def parse_song(what: str):
    """"周杰伦的晴天" → (晴天, 周杰伦); "周杰伦的歌" → (None, 周杰伦); "晴天" → (晴天, None)."""
    what = what.strip()
    m = re.fullmatch(r"(?P<artist>.+?)的(?:歌|歌曲|音乐)(?:随便|随意|随机)?(?:放|播放|听)?", what)
    if m:
        return None, m.group("artist")
    for sep in ("的", " "):
        if sep in what:
            artist, title = what.split(sep, 1)
            if artist.strip() and title.strip():
                return title.strip(), artist.strip()
    return what, None


def match(text: str, has_song: bool = False, playing: bool = False, paused: bool = False) -> Optional[Command]:
    """The command in an utterance, or None for anything that should go to the Bot.

    ASR often joins clauses ("周杰伦的晴天。放周杰伦的晴天。", "放周杰伦的音乐，你随意播放"):
    a clause that is a command wins when the other clauses only repeat it or add music words.
    """
    clauses = [c.strip() for c in CLAUSE.split(text) if c.strip()]
    if len(clauses) > 1:
        for i, clause in enumerate(clauses):
            cmd = _match_one(clause, has_song, playing, paused)
            if cmd and all(_goes_with(other, clause) for other in clauses[:i] + clauses[i + 1:]):
                return cmd
    return _match_one(text, has_song, playing, paused)


def _goes_with(other: str, clause: str) -> bool:
    a, b = POLITE.sub("", other.replace(" ", "")), POLITE.sub("", clause.replace(" ", ""))
    return not a or a in b or b in a or bool(MUSICISH.search(a)) or all(c in FILLER for c in a)


def _match_one(text: str, has_song: bool, playing: bool, paused: bool) -> Optional[Command]:
    raw = PUNCT.sub(" ", text).strip()
    full = POLITE.sub("", raw.replace(" ", ""))
    t = TAIL.sub("", full) or full
    if not t:
        return None
    if t in LOOP_OFF or full in LOOP_OFF:
        return Command("loop", level=0) if has_song else None
    if re.match(r"^(?:别|不要|不用)(?!放了|唱了)", full):
        return None
    if t in STOP or full in STOP:
        return Command("stop") if has_song else None
    if t in PAUSE or full in PAUSE:
        return Command("pause") if has_song else None  # paused or finished already: still ours
    if t in RESUME or full in RESUME:
        # "继续"/"播放" alone are everyday words: only while a song is paused
        return Command("resume") if paused or (has_song and t not in ("继续", "播放", "放")) else None
    if t in NEXT or full in NEXT:
        return Command("next")
    if t in PREVIOUS or full in PREVIOUS:
        return Command("previous")
    if t in WHAT or full in WHAT:
        return Command("what") if has_song else None
    if t in RESTART or full in RESTART:
        return Command("restart") if has_song else None
    if t in LOOP_ON or full in LOOP_ON:
        return Command("loop", level=1) if has_song else None
    action = (_keyword(t) or _keyword(full)) if has_song else None
    if action in ("stop", "next", "previous", "what", "restart"):
        return Command(action)
    if action == "pause":
        return Command("pause")
    if action == "resume" and paused:
        return Command("resume")
    if action in ("loop_on", "loop_off"):
        return Command("loop", level=int(action == "loop_on"))
    if action is None:
        folded = _keyword(t)
        if folded in ("next", "previous"):
            return Command(folded)  # "下下一首" with nothing playing: answered, not sent to the Bot
    m = SEEK.match(t)
    if m and has_song:
        n = cn_number(m.group("n")) if m.group("n") else SEEK_DEFAULT
        if n is None:
            return None
        seconds = n * 60 if (m.group("unit") or "").startswith("分") else n
        backward = m.group("dir") not in ("快进", "前进")
        return Command("seek", level=-seconds if backward else seconds)
    if t in MUTE or full in MUTE:
        return Command("mute")
    if t in UNMUTE or full in UNMUTE:
        return Command("unmute")
    m = VOLUME_EXTREME.match(t)
    if m:
        return Command("volume", level=100 if (m.group("a") or m.group("b")) == "最大" else 10)
    m = SET_VOLUME.match(t)
    if m:
        level = cn_number(m.group("n"))
        return Command("volume", level=level) if level is not None and level <= 100 else None
    if LOUDER.match(t) and ("音量" in t or "声" in t or has_song):
        return Command("louder")
    if QUIETER.match(t) and ("音量" in t or "声" in t or has_song):
        return Command("quieter")
    m = NAMED.search(t)
    if m and MUSIC_VERB.search(t) and re.search(r"歌|首", t):
        title = m.group("title").strip()
        a = NAMED_ARTIST.search(t[:m.start()])
        artist = None
        if a:
            # "帮我切换另外周杰伦" → "周杰伦": drop the verbs in front of the singer
            artist = re.sub(r"^(?:帮我|给我|把歌|切换到|切换成|切换|换成|换到|换|播放|放|来|听|另外|另一个|另一|再)+", "",
                            a.group("artist")) or None
        if title and title not in GENERIC:
            return Command("play", title=title, artist=artist)
    # Matched with single spaces kept: "放 周杰伦 晴天" splits singer and title at the space
    m = PLAY.match(POLITE.sub("", raw))
    if m:
        what = m.group("what").strip()
        if what.replace(" ", "") in GENERIC or all(c in FILLER for c in what.replace(" ", "")):
            return Command("resume") if paused else Command("ask")
        if len(what) > 30:
            return None
        title, artist = parse_song(what)
        return Command("play", title=title, artist=artist)
    return None


def _strong_music_request(text: str, cmd=None, why: str = "") -> bool:
    """Said like a song request; when nothing is found we answer instead of passing it to the Bot.
    "来一首…", anything with 歌/首, or a singer the platforms know ("播放周杰伦的请帖").
    A bare "播放…"/"放…" is not enough: "播放器怎么用", "放到桌面上" belong to the Bot."""
    if re.search(r"首|歌|音乐|我想听|我要听|想听|来一首|来首|听一首|听首", text):
        return True
    return bool(cmd and cmd.artist and why and "没找到这位歌手" not in why)


def _run(music, cmd: Command):
    """Blocking work; returns the reply, or None to hand the utterance to the Bot."""
    from core.music.player import set_muted, set_system_volume, system_volume

    if cmd.action == "ask":
        return "想听什么歌？可以说：放周杰伦的晴天。"
    if cmd.action == "play":
        song = music.find_and_play(cmd.title, cmd.artist)
        if song and cmd.title and "按读音" in getattr(music, "last_why", ""):
            return f"没找到{cmd.title}，给你放{song.title}。"
        if song:
            return f"正在播放：{song.title}"
        return None
    if cmd.action == "pause":
        music.pause()
        return "已暂停。"
    if cmd.action == "resume":
        music.resume()
        return "继续播放。"
    if cmd.action == "stop":
        music.stop()
        return "已停止播放。"
    if cmd.action == "next":
        if not music.current:
            return "现在没有在放歌。"
        song = music.next()
        return f"正在播放：{song.title}" if song else "没找到下一首。"
    if cmd.action == "previous":
        song = music.previous()
        return f"正在播放：{song.title}" if song else "前面没有歌了。"
    if cmd.action == "what":
        return f"现在放的是{music.current.title}。"
    if cmd.action == "restart":
        music.seek(0, absolute=True)
        return "从头播放。"
    if cmd.action == "loop":
        music.loop(bool(cmd.level))
        return "单曲循环。" if cmd.level else "已取消循环。"
    if cmd.action == "seek":
        music.seek(cmd.level)
        amount = abs(cmd.level)
        spoken = f"{amount // 60}分钟" if amount >= 60 and amount % 60 == 0 else f"{amount}秒"
        return f"{'快进' if cmd.level > 0 else '快退'}{spoken}。"
    if cmd.action == "mute":
        set_muted(True)
        return "已静音。"
    if cmd.action == "unmute":
        set_muted(False)
        return "已取消静音。"
    if cmd.action in ("louder", "quieter"):
        level = set_system_volume(system_volume() + (STEP if cmd.action == "louder" else -STEP))
        return f"音量{level}。"
    if cmd.action == "volume":
        return f"音量调到{set_system_volume(cmd.level)}。"
    return None


def duck(conn) -> None:
    """The board started listening: lower the music so it hears the user."""
    if not conn.config.get("local_music", {}).get("enabled"):
        return
    from core.music.player import current_music
    music = current_music()
    if music:
        asyncio.get_running_loop().run_in_executor(None, music.duck)


async def handle_local_command(conn, text) -> bool:
    config = conn.config.get("local_music", {})
    if not config.get("enabled"):
        return False
    from core.handle.grokBotHandle import extract_command, strip_wake_phrase
    from core.music.player import MusicError, get_music

    command = extract_command(text)
    if command is None:
        return False
    device_wake = getattr(conn, "device_wake_word", None)
    if re.sub(r"[\W_]", "", command) in [*conn.config.get("wakeup_words", []), device_wake]:
        return False  # the wake greeting, not a command
    _, command = strip_wake_phrase(command, [device_wake] if device_wake else ())
    if not command.strip("，。！？,.!? "):
        return False

    music = get_music(config)
    try:
        state = await asyncio.to_thread(lambda: (bool(music.current), music.playing(), music.paused()))
    except Exception:
        state = (bool(music.current), False, False)
    await asyncio.to_thread(music.unduck)
    cmd = match(command, *state)
    if cmd is None:
        if state[1] or state[2]:
            # Said while music is on and not understood: recorded to find missing phrasings
            conn.logger.bind(tag=__name__).info(f"放歌期间未匹配，交给 Bot: {command}")
        return False

    log = conn.logger.bind(tag=__name__)
    log.info(f"本地指令 {cmd.action}: {command}")
    started = asyncio.get_running_loop().time()
    work = asyncio.create_task(asyncio.to_thread(_run, music, cmd))
    ack = ACK.get(cmd.action)
    if ack and (cmd.action != "play" or cmd.artist or _strong_music_request(command)):
        # Slow: say a cached phrase now, show the song when it is found
        await _answer(conn, text, ack, screen="正在找歌……" if cmd.action == "play" else ack)
        reply = await _finish(work, log)
        if reply is None:
            reply = f"没找到{cmd.artist + '的' if cmd.artist else ''}{cmd.title or '这首歌'}的原唱。"
        if reply.startswith("正在播放："):
            await _show(conn, reply)
        else:
            await _say_more(conn, reply)
    else:
        reply = await _finish(work, log)
        if reply is None:
            if not _strong_music_request(command, cmd, getattr(music, "last_why", "")):
                return False  # "放到桌面上" and the like: not a song, the Bot handles it
            reply = f"没找到{cmd.artist + '的' if cmd.artist else ''}{cmd.title or '这首歌'}的原唱。"
        spoken = OK if cmd.action in QUIET and not reply.startswith(("电脑", "播放器", "音乐服务")) else reply
        await _answer(conn, text, spoken, screen=reply)
    log.info(f"本地指令 {cmd.action} 完成，用时 {asyncio.get_running_loop().time() - started:.2f}s: {reply}")
    return True


async def _finish(work, log):
    from core.music.player import MusicError
    try:
        return await work
    except MusicError as error:
        return str(error)
    except Exception as error:  # a failed command must not drop the utterance silently
        log.error(f"本地指令出错: {error!r}")
        return "电脑上的音乐出了点问题，请看后端日志。"


def _bot_ui(conn) -> bool:
    return bool((getattr(conn, "features", None) or {}).get("bot_ui")) and not getattr(conn, "bot_ui_waiting", False)


async def _show(conn, text):
    """Update the screen after the spoken reply: kept for the idle screen and drawn now."""
    from core.handle.sendAudioHandle import send_tts_message
    if _bot_ui(conn):
        await conn.websocket.send(json.dumps({
            "type": "bot_wait", "state": "reply", "text": text, "session_id": conn.session_id,
        }, ensure_ascii=False))
    await send_tts_message(conn, "sentence_start", text)


async def _say_more(conn, text):
    """A second spoken sentence after the first one has finished, as for a Bot rejection."""
    from core.handle.intentHandler import speak_txt
    from core.handle.sendAudioHandle import send_tts_message
    if _bot_ui(conn):
        await conn.websocket.send(json.dumps({
            "type": "bot_wait", "state": "reply", "text": text, "session_id": conn.session_id,
        }, ensure_ascii=False))
    conn.client_abort = False
    conn.sentence_id = uuid.uuid4().hex
    await send_tts_message(conn, "start")
    conn.client_is_speaking = True
    if text not in FIXED_REPLIES or not await phrases.speak(conn, text):
        speak_txt(conn, text)


def warm(conn) -> None:
    """When the board connects: synthesize the fixed replies and start the music programs."""
    config = conn.config.get("local_music", {})
    if not config.get("enabled"):
        return
    from core.music.player import get_music
    asyncio.create_task(phrases.warm(conn, FIXED_REPLIES))
    music = get_music(config)

    def start():
        try:
            music.service.ensure()
            music.mpv.ensure()
        except Exception as error:  # reported again when a command needs them
            conn.logger.bind(tag=__name__).warning(f"音乐程序预启动失败: {error}")
    asyncio.get_running_loop().run_in_executor(None, start)


async def _answer(conn, heard, reply, screen=None):
    from core.handle.intentHandler import speak_txt
    from core.handle.sendAudioHandle import send_stt_message

    conn.client_abort = False
    conn.sentence_id = uuid.uuid4().hex
    await send_stt_message(conn, heard)
    if _bot_ui(conn):
        # Like a delivered Bot reply: the board shows it and goes idle after speaking,
        # so the music from the Mac is not taken for the next command.
        await conn.websocket.send(json.dumps({
            "type": "bot_wait", "state": "reply", "text": screen or reply, "session_id": conn.session_id,
        }, ensure_ascii=False))
    if reply not in FIXED_REPLIES or not await phrases.speak(conn, reply):
        speak_txt(conn, reply)
